import os
import io
import zipfile
import logging
from logging.handlers import TimedRotatingFileHandler
import uuid
import asyncio
import mimetypes
from datetime import datetime, timezone
from typing import Optional, Dict, Any, List

from fastapi import FastAPI, UploadFile, File, HTTPException, Form, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, FileResponse, StreamingResponse, Response

from app.config import settings
from app.agents.orchestrator import LeadOrchestratorAgent
from app.services.firestore_service import JobStateService
from app.tools.registry import registry
from app.job_runner import runner

logger = logging.getLogger("chronocut.main")


def _setup_logging():
    """Persist server logs to chronocut.log, keeping ~4 hours of history."""
    try:
        log_dir = os.path.dirname(os.path.abspath(__file__))
        log_path = os.path.join(log_dir, "chronocut.log")
        # Rotates the log FILE every hour; keeps current + 3 prior hourly
        # files == roughly the last 4 hours of server logs. The app is NEVER
        # restarted by this handler (see note in chat).
        handler = TimedRotatingFileHandler(
            log_path, when="H", interval=1, backupCount=3, encoding="utf-8"
        )
        handler.setLevel(logging.INFO)
        handler.setFormatter(
            logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s")
        )
        root = logging.getLogger()
        root.setLevel(logging.INFO)
        if not any(isinstance(h, TimedRotatingFileHandler) for h in root.handlers):
            root.addHandler(handler)
    except Exception as e:  # logging must never break startup
        print(f"[logging] setup failed: {e}")


_setup_logging()

app = FastAPI(title="ChronoCut API", version="2.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

orchestrator = LeadOrchestratorAgent()
registry.discover()


@app.on_event("startup")
async def _startup():
    # Free-tier hygiene on boot: drop stale media + expired metadata so the
    # container's ephemeral disk and Firestore free quota stay bounded.
    try:
        from app.services.cleanup import cleanup_temp
        from app.services.firestore_service import JobStateService
        cleanup_temp(settings.DATA_RETENTION_HOURS)
        JobStateService.maintenance()
    except Exception as e:
        logger.warning(f"startup cleanup skipped: {e}")
    # Start the process-isolated job supervisor (Firestore-backed queue). This
    # also reclaims any jobs left QUEUED/PROCESSING by a previous crash.
    try:
        await runner.start()
    except Exception as e:
        logger.warning(f"job runner start skipped: {e}")


@app.on_event("shutdown")
async def _shutdown():
    try:
        await runner.stop()
    except Exception:
        pass

    # Diagnostic snapshot: reveals exactly what the RUNNING container sees,
    # so a "keys are set in Render" claim can be verified from chronocut.log.
    try:
        gk = settings.GOOGLE_API_KEY
        pk = settings.PEXELS_API_KEY
        logger.info("=== ChronoCut startup diagnostics ===")
        logger.info(f"GOOGLE_API_KEY present: {bool(gk)} (ends …{gk[-4:] if gk else 'NONE'})")
        logger.info(f"PEXELS_API_KEY present: {bool(pk)} (ends …{pk[-4:] if pk else 'NONE'})")
        logger.info(f"GEMINI_MODEL: {settings.GEMINI_MODEL}")
        from app.tools.llm.call import validate_model
        res = await validate_model()
        logger.info(f"validate_model: {res}")
        # Firestore connectivity: this triggers client init and logs exactly which
        # auth path succeeded (inline JSON / secret file / default) or why it fell
        # back to the local store. Check chronocut.log to verify credentials.
        fs_ok = JobStateService.using_firestore()
        logger.info(f"Firestore store: {'firestore (durable)' if fs_ok else 'local JSON (not durable across restarts)'}")
    except Exception as e:
        logger.error(f"startup diagnostics failed: {e}")

    # C4: real Pexels self-test (not just key-presence). Logs "Pexels OK (n hits)"
    # or the failure reason so a missing/bad key is diagnosable from chronocut.log
    # instead of silently degrading to matte mid-run.
    try:
        from app.tools.footage.pexels_video import search_pexels_videos
        hits = search_pexels_videos("test", per_page=1)
        logger.info(f"Pexels self-test: Pexels OK ({len(hits)} hits)")
    except Exception as e:
        logger.warning(f"Pexels self-test: FAILED ({type(e).__name__}: {e})")

    # N: HyperFrames readiness probe (non-fatal). If the overlay engine is set to
    # "hyperframes" but Node/Chromium are absent, the renderer self-detects at job
    # time and falls back to drawtext; this just surfaces the status at boot.
    try:
        from app.tools.render.hyperframes_renderer import _hf_available
        if settings.overlay_engine_is_hyperframes:
            logger.info(f"HyperFrames engine: {'AVAILABLE' if _hf_available() else 'UNAVAILABLE (drawtext fallback)'}")
        else:
            logger.info(f"HyperFrames engine: disabled (TEXT_OVERLAY_ENGINE={settings.TEXT_OVERLAY_ENGINE})")
    except Exception as e:
        logger.warning(f"HyperFrames probe skipped: {e}")


@app.get("/health")
async def health():
    return {
        "status": "ok",
        "service": "chronocut-api",
        "env": settings.ENV,
        "model": settings.GEMINI_MODEL,
        "store": "firestore" if JobStateService.using_firestore() else "local",
        "features": {
            "footage_corpus": settings.ENABLE_FOOTAGE_CORPUS,
            "reference_video": settings.ENABLE_REFERENCE_VIDEO,
            "self_review": settings.ENABLE_SELF_REVIEW,
            "rag": settings.ENABLE_RAG,
        },
    }


@app.get("/api/v1/capabilities")
async def capabilities():
    return {"support_envelope": registry.support_envelope(), "provider_menu": registry.provider_menu()}


@app.post("/api/v1/jobs")
async def create_job(
    file: Optional[UploadFile] = File(None),
    prompt: Optional[str] = Form(None),
    mode: str = Form("from_media"),
    reference_url: Optional[str] = Form(None),
    target_language: str = Form("en"),
    output_profiles: Optional[str] = Form(None),
    tone: str = Form("cinematic"),
    length_seconds: int = Form(60),
    target_audience: str = Form("general"),
):
    """Create a job. Supports three input modes: from_media (ZIP), from_reference (URL), from_prompt."""
    job_id = str(uuid.uuid4())
    user_id = "anon"

    temp_dir = os.path.join(os.path.dirname(__file__), "..", "..", "..", "tmp", f"chronocut_{job_id}")
    os.makedirs(temp_dir, exist_ok=True)

    audio_files: List[str] = []
    photo_files: List[str] = []
    video_files: List[str] = []

    if mode == "from_prompt":
        input_files = {
            "mode": "from_prompt",
            "user_prompt": prompt or "a short documentary",
            "tone": tone, "length_seconds": length_seconds, "target_audience": target_audience,
            "target_language": target_language,
            "output_profiles": _parse_profiles(output_profiles),
            "zip_filename": "", "audio_files": [], "photo_files": [], "video_files": [],
        }
    elif mode == "from_reference":
        if not reference_url:
            raise HTTPException(status_code=400, detail="reference_url is required for reference mode")
        input_files = {
            "mode": "from_reference",
            "user_prompt": prompt or "",
            "reference_url": reference_url,
            "target_language": target_language,
            "tone": tone, "length_seconds": length_seconds, "target_audience": target_audience,
            "output_profiles": _parse_profiles(output_profiles),
            "zip_filename": "", "audio_files": [], "photo_files": [], "video_files": [],
        }
    else:
        # from_media (default) — requires a ZIP of raw media
        if not file:
            raise HTTPException(status_code=400, detail="ZIP file is required for media mode")
        if not file.filename or not file.filename.endswith(".zip"):
            raise HTTPException(status_code=400, detail="Only .zip archives are accepted")
        try:
            # V: stream the upload straight to disk in 1 MiB chunks instead of
            # buffering the whole ZIP in RAM (a large upload was a direct OOM
            # source). Extract from the on-disk copy.
            zip_path = os.path.join(temp_dir, "_upload.zip")
            with open(zip_path, "wb") as out:
                while True:
                    chunk = await file.read(1024 * 1024)
                    if not chunk:
                        break
                    out.write(chunk)
            with zipfile.ZipFile(zip_path, "r") as zf:
                zf.extractall(temp_dir)
            try:
                os.remove(zip_path)
            except Exception:
                pass
            for root, dirs, files in os.walk(temp_dir):
                for fname in files:
                    ext = fname.split(".")[-1].lower()
                    full = os.path.join(root, fname)
                    if ext in {"mp3", "wav", "m4a", "aac", "ogg", "flac", "wma", "opus", "aiff", "au"}:
                        audio_files.append(full)
                    elif ext in {"jpg", "jpeg", "png", "webp", "heic", "gif", "bmp", "tiff", "tif", "svg", "avif"}:
                        photo_files.append(full)
                    elif ext in {"mp4", "mov", "avi", "mkv", "webm", "m4v", "mpg", "mpeg"}:
                        video_files.append(full)
        except Exception as e:
            raise HTTPException(status_code=400, detail=f"Failed to process ZIP: {e}")
        if not audio_files and not photo_files and not video_files:
            raise HTTPException(status_code=400, detail="ZIP contains no supported media files")
        input_files = {
            "mode": mode,
            "user_prompt": prompt or "",
            "reference_url": reference_url,
            "target_language": target_language,
            "tone": tone, "length_seconds": length_seconds, "target_audience": target_audience,
            "output_profiles": _parse_profiles(output_profiles),
            "zip_filename": file.filename,
            "audio_files": audio_files, "photo_files": photo_files, "video_files": video_files,
        }

    try:
        JobStateService.create_job(job_id, user_id, input_files)
    except Exception as e:
        logger.error(f"Firestore create failed: {e}")

    # V: enqueue to the Firestore-backed, process-isolated runner instead of
    # running the heavy pipeline inside the web-server process (which previously
    # caused OOM kills of the whole API). The child process re-reads input_files
    # from Firestore, so this stays lightweight.
    await runner.submit(job_id)
    return JSONResponse({
        "job_id": job_id, "status": "QUEUED", "mode": mode,
        "audio_files": len(audio_files), "photo_files": len(photo_files),
        "poll_url": f"/api/v1/jobs/{job_id}",
        "events_url": f"/api/v1/jobs/{job_id}/events",
    })


def _parse_profiles(value: Optional[str]) -> List[str]:
    if not value:
        return settings.output_profiles
    from app.schemas import validate_profiles
    return validate_profiles([p.strip() for p in value.split(",") if p.strip()])


@app.get("/api/v1/jobs/{job_id}")
async def get_job(job_id: str):
    job = JobStateService.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    return job


@app.get("/api/v1/jobs")
async def list_jobs(limit: int = 20):
    return {"jobs": JobStateService.list_jobs(limit=min(limit, 100))}


@app.delete("/api/v1/jobs/{job_id}")
async def delete_job(job_id: str):
    try:
        import shutil
        temp_dir = os.path.join(os.path.dirname(__file__), "..", "..", "..", "tmp", f"chronocut_{job_id}")
        if os.path.exists(temp_dir):
            shutil.rmtree(temp_dir, ignore_errors=True)
        JobStateService.update_job(job_id, {"status": "DELETED"})
        return {"ok": True, "job_id": job_id}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/v1/jobs/{job_id}/cancel")
async def cancel_job(job_id: str):
    JobStateService.update_job(job_id, {"status": "CANCELLED"})
    JobStateService.append_event(job_id, {"stage": "cancelled", "progress_percent": 0, "message": "Job cancelled."})
    return {"ok": True, "status": "CANCELLED"}


@app.get("/api/v1/jobs/{job_id}/events")
async def job_events(job_id: str, request: Request):
    """Server-Sent Events stream of live job progress."""
    job = JobStateService.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    async def event_stream():
        import time as _time
        last_seq = -1
        terminal = False
        start = _time.monotonic()
        MAX_SECONDS = 30 * 60  # real wall-clock cap so a stuck job eventually closes
        while not terminal and (_time.monotonic() - start) < MAX_SECONDS:
            events = JobStateService.get_events(job_id, after_seq=last_seq)
            for ev in events:
                last_seq = max(last_seq, ev.get("seq", last_seq))
                yield f"data: {_json(ev)}\n\n"
            j = JobStateService.get_job(job_id) or {}
            status = j.get("status")
            if status in ("COMPLETE", "FAILED", "NEEDS_REVIEW", "CANCELLED", "DELETED"):
                terminal = True
                yield f"event: done\ndata: {_json({'status': status})}\n\n"
                break
            if events:
                await asyncio.sleep(0.5)
            else:
                # Keep the telemetry stream alive during long renders so the
                # Agent Terminal doesn't freeze when no events arrive for a while.
                yield ": ping\n\n"
                await asyncio.sleep(2.0)
        if not terminal:
            # P3: stuck-job detector. The 30-min wall-clock cap guarantees the SSE
            # closes so the UI shows a message instead of spinning forever (the
            # blank-screen trigger). Mark NEEDS_REVIEW with a human-readable reason.
            final = (JobStateService.get_job(job_id) or {}).get("status", "PROCESSING")
            try:
                JobStateService.update_job(job_id, {
                    "status": "NEEDS_REVIEW",
                    "error_log": {"stage": "event_stream",
                                  "message": "Job exceeded max stream time (30 min) without terminal state."},
                })
            except Exception:
                pass
            yield f"event: done\ndata: {_json({'status': 'NEEDS_REVIEW', 'reason': 'job_stuck'})}\n\n"

    return StreamingResponse(event_stream(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


def _json(obj) -> str:
    import json
    return json.dumps(obj, default=str)


@app.get("/api/v1/jobs/{job_id}/video")
async def get_video(job_id: str, profile: Optional[str] = None, request: Request = None):
    job = JobStateService.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    editor = job.get("editor_output", {})
    paths = editor.get("video_paths", {})
    if not paths:
        raise HTTPException(status_code=404, detail="No video available yet")
    key = profile or editor.get("primary_profile") or next(iter(paths))
    path = paths.get(key) or next(iter(paths.values()))
    if not path or not os.path.exists(path):
        raise HTTPException(status_code=404, detail="Video file missing")
    return _serve_file_range(request, path, media_type="video/mp4")


@app.get("/api/v1/jobs/{job_id}/changelog")
async def get_changelog(job_id: str):
    job = JobStateService.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    return JSONResponse(job.get("editor_output", {}).get("changelog", {}))


@app.get("/api/v1/jobs/{job_id}/ledger")
async def get_ledger(job_id: str):
    ledger = JobStateService.get_ledger(job_id)
    job = JobStateService.get_job(job_id) or {}
    total = sum((c.get("cost_cents", 0.0) for c in ledger if not c.get("cached")))
    return JSONResponse({"job_id": job_id, "calls": ledger, "total_cost_cents": round(total, 4),
                         "per_job_cap_cents": settings.PER_JOB_COST_CAP_CENTS})


@app.get("/api/v1/jobs/{job_id}/review")
async def get_review(job_id: str):
    job = JobStateService.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    return JSONResponse(job.get("review_report", {}))


def _serve_file_range(request, path: str, media_type: str = "application/octet-stream"):
    size = os.path.getsize(path)
    range_header = (request.headers.get("range") if request else None) or ""
    start, end = 0, size - 1
    if range_header and range_header.startswith("bytes="):
        parts = range_header[6:].split("-")
        if parts[0]:
            start = int(parts[0])
        if len(parts) > 1 and parts[1]:
            end = int(parts[1])
    end = min(end, size - 1)
    length = end - start + 1
    with open(path, "rb") as f:
        f.seek(start)
        data = f.read(length)
    headers = {
        "Content-Range": f"bytes {start}-{end}/{size}",
        "Accept-Ranges": "bytes",
        "Content-Length": str(length),
        "Content-Type": media_type,
    }
    return Response(content=data, status_code=206 if range_header else 200, headers=headers)


@app.get("/{full_path:path}")
async def serve_frontend(request: Request, full_path: str):
    """Serve the built React app from the same container (M1 / single-container)."""
    frontend_dir = os.getenv("FRONTEND_DIR", settings.FRONTEND_DIR)
    if not frontend_dir or not os.path.isdir(frontend_dir):
        return JSONResponse({"detail": "Frontend build not found", "api": "/health"}, status_code=200)
    file_path = os.path.join(frontend_dir, full_path)
    if full_path and os.path.isfile(file_path):
        mt = mimetypes.guess_type(file_path)[0] or "application/octet-stream"
        return FileResponse(file_path, media_type=mt)
    index = os.path.join(frontend_dir, "index.html")
    if os.path.isfile(index):
        return FileResponse(index, media_type="text/html")
    return JSONResponse({"detail": "Frontend build not found", "api": "/health"})


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app.main:app", host=settings.HOST, port=settings.PORT, reload=False)
