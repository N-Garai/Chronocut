import os
import io
import zipfile
import logging
import requests
from contextlib import asynccontextmanager
from logging.handlers import TimedRotatingFileHandler
import uuid
import asyncio
from datetime import datetime, timezone
from zoneinfo import ZoneInfo
from typing import Optional, Dict, Any, List

from fastapi import FastAPI, UploadFile, File, HTTPException, Form, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse, Response

from app.config import settings
from app.agents.orchestrator import LeadOrchestratorAgent
from app.services.firestore_service import JobStateService
from app.tools.registry import registry
from app.job_runner import runner

logger = logging.getLogger("chronocut.main")


def _setup_logging():
    """Persist server logs under the centralized tmp root (CHRONOCUT_TMP_DIR),
    keeping ~4 hours of history; the console keeps the live tail."""
    try:
        from app.services.storage import logs_dir
        log_path = os.path.join(logs_dir(), "chronocut.log")
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

# Modern FastAPI lifespan handler — the legacy ``@app.on_event`` decorators
# emit DeprecationWarnings on current FastAPI releases. The body runs after
# this module finishes importing, so the names it calls are all resolvable.
@asynccontextmanager
async def lifespan(_app):
    await _startup()
    yield
    await _shutdown()


app = FastAPI(title="ChronoCut API", version="2.0.0", lifespan=lifespan)

_cors_origins = settings.cors_origin_list or ["*"]
app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,
    # "*" combined with credentials is rejected by browsers; credentials are
    # only sent when the origins are explicitly pinned via CORS_ORIGINS.
    allow_credentials=bool(settings.cors_origin_list),
    allow_methods=["*"],
    allow_headers=["*"],
)

orchestrator = LeadOrchestratorAgent()
registry.discover()

from app.api.timeline import router as timeline_router
app.include_router(timeline_router)

from app.api.agent import router as agent_router
app.include_router(agent_router)


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
    # Layer-1 keep-warm: self-ping the public /health endpoint every ~13.5 min
    # so a free-tier deployment never idles into a ~50 s cold start. Disabled
    # locally and on paid plans via KEEP_WARM=off; a missed ping costs at most
    # one cold start, so failures only log a warning.
    try:
        _start_keep_warm()
    except Exception as e:
        logger.warning(f"keep-warm disabled: {e}")

    # Startup diagnostics: reveal exactly what the RUNNING container sees so a
    # "keys are set in the host" claim can be verified from chronocut.log.
    try:
        mk = settings.provider_api_key
        pk = settings.PEXELS_API_KEY
        logger.info("=== ChronoCut startup diagnostics ===")
        logger.info(f"LLM provider: {settings.LLM_PROVIDER}")
        logger.info(f"provider text model: {settings.model_badge[1]}")
        if (settings.LLM_PROVIDER or "").strip().lower() == "local":
            logger.info(
                f"LOCAL_LLM_BASE_URL: {settings.LOCAL_LLM_BASE_URL} "
                f"(LOCAL_LLM_MODEL: {settings.LOCAL_LLM_MODEL})"
            )
        else:
            # Primary key plus each independent failover slot, so the log
            # reveals exactly which chain hops are available in the container.
            logger.info(f"primary provider API key present: {bool(mk)} (ends …{mk[-4:] if mk else 'NONE'})")
            for slot in ("BASETEN_API_KEY", "OPENROUTER_API_KEY"):
                sk = (getattr(settings, slot) or "").strip()
                logger.info(f"{slot} present: {bool(sk)} (ends …{sk[-4:] if sk else 'NONE'})")
        logger.info(f"PEXELS_API_KEY present: {bool(pk)} (ends …{pk[-4:] if pk else 'NONE'})")
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

    # Real Pexels self-test (not just key-presence). Logs "Pexels OK (n hits)"
    # or the failure reason so a missing/bad key is diagnosable from chronocut.log
    # instead of silently degrading to matte mid-run.
    try:
        from app.tools.footage.pexels_video import search_pexels_videos
        hits = search_pexels_videos("test", per_page=1)
        logger.info(f"Pexels self-test: Pexels OK ({len(hits)} hits)")
    except Exception as e:
        logger.warning(f"Pexels self-test: FAILED ({type(e).__name__}: {e})")

    # HyperFrames readiness probe (non-fatal). If the overlay engine is set to
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


async def _shutdown():
    try:
        await runner.stop()
    except Exception:
        pass


def _start_keep_warm():
    """Self-ping the public /health endpoint inside the idle window.

    Target resolution order: APP_BASE_URL override, then Render's injected
    RENDER_EXTERNAL_URL, then PLATFORM_BASE_URL. Loopback traffic does not
    traverse the public edge router and cannot reset the idle timer, so it is
    never used. Set KEEP_WARM=off (paid plan) to disable.
    """
    if (os.getenv("KEEP_WARM", "on").strip().lower() in {"off", "0", "false", "no"}):
        logger.info("keep-warm disabled by KEEP_WARM=off")
        return
    environment = (os.getenv("ENVIRONMENT") or os.getenv("APP_ENV") or "local").strip().lower()
    if environment not in {"production", "prod", "render"}:
        logger.info("keep-warm skipped outside production (env=%s)", environment)
        return
    base_url = (os.getenv("APP_BASE_URL") or os.getenv("RENDER_EXTERNAL_URL")
                or os.getenv("PLATFORM_BASE_URL") or "").strip().rstrip("/")
    if not base_url:
        logger.info("keep-warm skipped: no public base URL discovered")
        return

    import asyncio

    async def _loop():
        while True:
            try:
                # blocking-but-cheap: run in a thread to keep the loop responsive
                r = await asyncio.to_thread(
                    requests.get, f"{base_url}/health", timeout=15.0)
                if r.status_code == 200:
                    logger.info("keep-warm ping ok (%s)", base_url)
                else:
                    logger.warning("keep-warm ping unexpected status %s", r.status_code)
            except Exception as e:  # never fatal: one cold start worst case
                logger.warning("keep-warm ping failed: %s", e)
            await asyncio.sleep(810)  # 13.5 min, inside a ~15 min idle window

    asyncio.get_event_loop().create_task(_loop())
    logger.info("keep-warm started -> %s/health every 13.5 min", base_url)


@app.get("/", include_in_schema=False)
async def root():
    """API root descriptor. The FastAPI process serves no frontend; the app
    itself is a static build hosted separately (see README architecture)."""
    return {
        "service": "chronocut-api",
        "status": "ok",
        "docs": "/docs",
        "health": "/health",
        "api": "/api/v1",
        "capabilities": "/api/v1/capabilities",
    }


@app.get("/health")
async def health():
    llm_provider = (settings.LLM_PROVIDER or "meta").strip().lower()
    active_model = settings.model_badge[1]
    return {
        "status": "ok",
        "service": "chronocut-api",
        "env": settings.ENV,
        "llm_provider": llm_provider,
        "model": active_model,
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
    media: Optional[List[UploadFile]] = File(None),
    prompt: Optional[str] = Form(None),
    mode: str = Form("from_media"),
    reference_url: Optional[str] = Form(None),
    target_language: str = Form("en"),
    output_profiles: Optional[str] = Form(None),
    tone: str = Form("cinematic"),
    length_seconds: int = Form(60),
    target_audience: str = Form("general"),
):
    """Create a job. Accepts a raw media[] upload (preferred), the legacy ZIP,
    or none at all (prompt / reference modes)."""
    job_id = str(uuid.uuid4())
    user_id = "anon"

    from app.services.storage import job_dir, job_upload_dir
    temp_dir = job_upload_dir(job_id)
    os.makedirs(temp_dir, exist_ok=True)

    audio_files: List[str] = []
    photo_files: List[str] = []
    video_files: List[str] = []
    document_files: List[str] = []

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
        # from_media (default) — accepts a raw media[] upload (preferred) or a
        # ZIP of raw media (kept for compatibility with the original flow).
        _AUDIO_EXT = {"mp3", "wav", "m4a", "aac", "ogg", "flac", "wma", "opus", "aiff", "au"}
        _PHOTO_EXT = {"jpg", "jpeg", "png", "webp", "heic", "gif", "bmp", "tiff", "tif", "svg", "avif"}
        _VIDEO_EXT = {"mp4", "mov", "avi", "mkv", "webm", "m4v", "mpg", "mpeg"}
        # Everything else is ingested as a document and folded into the brief.

        def _category(fname: str) -> Optional[str]:
            ext = (fname.split(".")[-1] or "").lower()
            if ext in _AUDIO_EXT:
                return "audio"
            if ext in _PHOTO_EXT:
                return "photo"
            if ext in _VIDEO_EXT:
                return "video"
            return "document"

        media_list = [f for f in (media or []) if f and f.filename]
        zip_filename = ""
        if media_list:
            if len(media_list) > 200:
                raise HTTPException(status_code=413, detail="Too many files (limit 200 per job)")
            total_downloaded = 0
            _MAX_TOTAL_BYTES = 500 * 1024 * 1024  # 500 MB
            _MAX_FILE_BYTES = 200 * 1024 * 1024   # 200 MB per file (sane upper bound)
            saved: List[str] = []
            try:
                for f in media_list:
                    safe_name = os.path.basename(f.filename or "media.bin")[:120]
                    out_path = os.path.join(temp_dir, f"media_{len(saved):03d}_{safe_name}")
                    size = 0
                    with open(out_path, "wb") as out:
                        while True:
                            chunk = await f.read(1024 * 1024)
                            if not chunk:
                                break
                            size += len(chunk)
                            total_downloaded += len(chunk)
                            if size > _MAX_FILE_BYTES:
                                raise HTTPException(status_code=413, detail=f"File too large: {f.filename}")
                            if total_downloaded > _MAX_TOTAL_BYTES:
                                raise HTTPException(status_code=413, detail="Total upload exceeds 500 MB limit")
                            out.write(chunk)
                    saved.append(out_path)
            except HTTPException:
                raise
            except Exception as e:
                raise HTTPException(status_code=400, detail=f"Failed to process upload: {e}")
            for full in saved:
                cat = _category(os.path.basename(full))
                if cat == "audio":
                    audio_files.append(full)
                elif cat == "photo":
                    photo_files.append(full)
                elif cat == "video":
                    video_files.append(full)
                else:
                    document_files.append(full)
        elif file:
            # Legacy single-archive path (kept for compatibility).
            if not file.filename or not file.filename.endswith(".zip"):
                raise HTTPException(status_code=400, detail="Only .zip archives or raw media files are accepted")
            try:
                # Stream the upload straight to disk in 1 MiB chunks instead of
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
                        elif ext and ext != "zip":
                            document_files.append(full)
            except Exception as e:
                raise HTTPException(status_code=400, detail=f"Failed to process ZIP: {e}")
            if zip_filename == "":
                zip_filename = file.filename

        if not audio_files and not photo_files and not video_files and not document_files:
            raise HTTPException(status_code=400, detail="No supported media or documents in the upload")
        input_files = {
            "mode": mode,
            "user_prompt": prompt or "",
            "reference_url": reference_url,
            "target_language": target_language,
            "tone": tone, "length_seconds": length_seconds, "target_audience": target_audience,
            "output_profiles": _parse_profiles(output_profiles),
            "zip_filename": zip_filename,
            "audio_files": audio_files, "photo_files": photo_files, "video_files": video_files,
            "document_files": document_files,
        }

    try:
        JobStateService.create_job(job_id, user_id, input_files)
    except Exception as e:
        logger.error(f"Firestore create failed: {e}")

    # Enqueue to the Firestore-backed, process-isolated runner instead of
    # running the heavy pipeline inside the web-server process (which previously
    # caused OOM kills of the whole API). The child process re-reads input_files
    # from Firestore, so this stays lightweight.
    await runner.submit(job_id)
    return JSONResponse({
        "job_id": job_id, "status": "QUEUED", "mode": mode,
        "audio_files": len(audio_files), "photo_files": len(photo_files),
        "poll_url": f"/api/v1/jobs/{job_id}",
        "events_url": f"/api/v1/jobs/{job_id}/events",
        "studio_url": f"/studio/{job_id}/timeline",
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
        from app.services.storage import job_dir
        temp_dir = job_dir(job_id)
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
        # Last-Event-ID (or ?after_seq=) replays only what the client missed,
        # preventing gaps or duplicates across reconnects.
        resume = request.headers.get("last-event-id") or request.query_params.get("after_seq")
        try:
            last_seq = int(resume) if resume not in (None, "") else -1
        except (TypeError, ValueError):
            last_seq = -1
        terminal = False
        start = _time.monotonic()
        MAX_SECONDS = 30 * 60  # real wall-clock cap so a stuck job eventually closes
        while not terminal and (_time.monotonic() - start) < MAX_SECONDS:
            events = JobStateService.get_events(job_id, after_seq=last_seq)
            for ev in events:
                last_seq = max(last_seq, ev.get("seq", last_seq))
                sse_id = f"id: {ev.get('seq', last_seq)}\n"
                stage = str(ev.get("stage") or "")
                if stage == "agent_activity":
                    # Telemetry feed row (13.6): named event, replay + live over this bus.
                    yield f"{sse_id}event: agent_activity\ndata: {_json(ev)}\n\n"
                elif stage == "edl_updated":
                    # Live revision sync: the timeline refetches the EDL on this.
                    yield f"{sse_id}event: edl_revision\ndata: {_json(ev)}\n\n"
                else:
                    yield f"{sse_id}data: {_json(ev)}\n\n"
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
async def get_video(job_id: str, profile: Optional[str] = None, request: Request = None, download: Optional[str] = None):
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
    headers = {}
    if download:
        headers["Content-Disposition"] = f'attachment; filename="{job_id}.mp4"'
    return _serve_file_range(request, path, media_type="video/mp4", headers=headers)


@app.get("/api/v1/jobs/{job_id}/assets")
async def get_job_assets(job_id: str):
    """Asset bin data: every EDL source with kind, size, and thumbnail URL."""
    job = JobStateService.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    from app.edl.store import load_edl
    from app.tools.media.thumbnails import list_assets
    edl, revision = load_edl(job_id)
    assets = list_assets(job_id, edl)
    return JSONResponse({
        "job_id": job_id,
        "revision": revision,
        "assets": assets,
        "counts": {
            "total": len(assets),
            "image": sum(1 for a in assets if a["kind"] == "image"),
            "video": sum(1 for a in assets if a["kind"] == "video"),
            "audio": sum(1 for a in assets if a["kind"] in ("narration", "music")),
            "unavailable": sum(1 for a in assets if not a["available"]),
        },
    })


@app.get("/api/v1/jobs/{job_id}/assets/{asset_id}/thumb")
async def get_asset_thumb(job_id: str, asset_id: str):
    """Cached thumbnail PNG for one asset (generated on first request)."""
    job = JobStateService.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    from app.edl.store import load_edl
    from app.tools.media.thumbnails import describe_source
    edl, _ = load_edl(job_id)
    source = next((s for s in ((edl or {}).get("sources") or [])
                   if isinstance(s, dict) and str(s.get("id")) == str(asset_id)), None)
    if not source:
        raise HTTPException(status_code=404, detail="Asset not found")
    row = describe_source(job_id, source)
    if not row["thumb_url"]:
        raise HTTPException(status_code=404, detail="Thumbnail unavailable")
    from app.tools.media.thumbnails import thumb_path
    path = thumb_path(job_id, asset_id)
    if not os.path.isfile(path):
        raise HTTPException(status_code=404, detail="Thumbnail unavailable")
    return _serve_file_range(None, path, media_type="image/png")


@app.get("/api/v1/jobs/{job_id}/waveform")
async def get_job_waveform(job_id: str, asset_id: Optional[str] = None):
    """Cached waveform PNG for one audio asset (defaults to the narration)."""
    job = JobStateService.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    from app.edl.store import load_edl
    from app.services.storage import resolve_job_path
    from app.tools.media.thumbnails import ensure_waveform, waveform_path
    edl, _ = load_edl(job_id)
    sources = [s for s in ((edl or {}).get("sources") or []) if isinstance(s, dict)]
    audio = [s for s in sources if str(s.get("type") or "") in ("narration", "music")]
    if asset_id:
        source = next((s for s in audio if str(s.get("id")) == str(asset_id)), None)
    else:
        source = audio[0] if audio else None
    if not source:
        raise HTTPException(status_code=404, detail="No audio asset for this job")
    path = resolve_job_path(job_id, str(source.get("path") or ""))
    if not ensure_waveform(job_id, str(source.get("id")), path):
        raise HTTPException(status_code=404, detail="Waveform unavailable")
    return _serve_file_range(None, waveform_path(job_id, str(source.get("id"))),
                             media_type="image/png")


@app.get("/api/v1/jobs/{job_id}/ledger")
async def get_ledger(job_id: str):
    ledger = JobStateService.get_ledger(job_id)
    job = JobStateService.get_job(job_id) or {}
    total = sum((c.get("cost_cents", 0.0) for c in ledger if not c.get("cached")))
    # Serialize datetime-like objects (Firestore returns DatetimeWithNanoseconds)
    def _jsonify(v):
        import datetime
        if isinstance(v, datetime.datetime):
            return v.isoformat()
        if hasattr(v, "isoformat"):
            return v.isoformat()
        return v
    return JSONResponse({"job_id": job_id, "calls": ledger, "total_cost_cents": round(total, 4),
                         "per_job_cap_cents": settings.PER_JOB_COST_CAP_CENTS})


@app.get("/api/v1/jobs/{job_id}/review")
async def get_review(job_id: str):
    job = JobStateService.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    return JSONResponse(job.get("review_report", {}))


def _serve_file_range(request, path: str, media_type: str = "application/octet-stream", headers: Optional[Dict[str, str]] = None):
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
    headers = headers or {}
    headers.update({
        "Content-Range": f"bytes {start}-{end}/{size}",
        "Accept-Ranges": "bytes",
        "Content-Length": str(length),
        "Content-Type": media_type,
    })
    return Response(content=data, status_code=206 if range_header else 200, headers=headers)


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app.main:app", host=settings.HOST, port=settings.PORT, reload=False)
