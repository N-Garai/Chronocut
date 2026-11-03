"""Timeline / EDL / render API routes.

Included once from app.main. Every route is scoped by ``job_id`` and reads
EDL state exclusively through :mod:`app.edl.store` so Firestore and the local
JSON fallback behave identically.
"""
import asyncio
import logging
import os
from typing import Any, Dict, List, Optional, Tuple

from fastapi import APIRouter, HTTPException, Request, Response

from app.agents.telemetry import record_activity
from app.config import settings
from app.services.firestore_service import JobStateService
from app.edl.compiler import quick_render_check, render_edl
from app.edl.operations import OperationValidationError, apply_operations, plan_operations
from app.edl.schema import ALLOWED_PROFILE_RESOLUTIONS, EDLValidationError, edl_summary
from app.edl.store import (
    RevisionConflict,
    get_revision,
    list_revisions,
    load_edl,
    save_edl,
)
from app.services.renders import (
    create_render,
    dispatch_actions,
    dispatch_modal,
    get_render,
    list_renders,
    mark_status,
)
from app.services.storage import render_dir, resolve_job_path
from app.tools.audio.silence import audio_silence_context, cached_job_audio, job_audio_paths
from app.tools.otio_export import edl_to_otio_json, write_otio

# Default thresholds for the remove_silence recipe (silence detection + macro).
_SILENCE_NOISE_DB = -35.0
_SILENCE_MIN_DURATION = 0.4

logger = logging.getLogger("chronocut.api.timeline")
router = APIRouter(prefix="/api/v1/jobs/{job_id}")


# --------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------
def _job_or_404(job_id: str) -> Dict[str, Any]:
    from app.services.firestore_service import JobStateService
    job = JobStateService.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    return job


def _edl_or_404(job_id: str) -> Tuple[Dict[str, Any], int]:
    edl, revision = load_edl(job_id)
    if not edl:
        raise HTTPException(status_code=404, detail="EDL not ready for this job yet")
    return edl, revision


def _materialize_generated_now(job_id: str, snapshot: Dict[str, Any]) -> None:
    """Materialize pending generated B-roll sources in the background.

    The apply response returns immediately with the pending source; generated
    stills (or their degrade rows) land as a follow-up revision so the live
    timeline and telemetry see the b-roll arrive.
    """
    try:
        from app.services.storage import asset_dir
        from app.tools.imagegen.muse import ensure_generated_assets
        copy = {**snapshot, "sources": [dict(s) for s in snapshot.get("sources") or []]}
        if not ensure_generated_assets(job_id, copy, asset_dir(str(job_id), "generated")):
            return
        from app.edl.store import save_edl
        # "system" is not an allowed EDL source; pipeline materialization is
        # recorded with source="pipeline" (the set is fixed in edl.store).
        save_edl(job_id, copy, source="pipeline")
    except Exception as e:  # never fatal: the matte fallback still renders
        logger.warning("generated b-roll materialization failed for %s: %s", job_id, e)


def _render_doc_or_404(job_id: str, render_id: str) -> Dict[str, Any]:
    doc = get_render(render_id)
    if not doc or doc.get("job_id") != str(job_id):
        raise HTTPException(status_code=404, detail="Render not found")
    return doc


# --------------------------------------------------------------------------
# EDL read/write
# --------------------------------------------------------------------------
@router.get("/edl")
async def get_edl(job_id: str):
    edl, revision = _edl_or_404(job_id)
    project = edl.get("project") or {}
    return {
        "job_id": job_id,
        "edl": edl,
        "revision": revision,
        "summary": edl_summary(edl),
        "updated_at": project.get("updated_at"),
    }


@router.put("/edl")
async def put_edl(job_id: str, body: Dict[str, Any]):
    """Full-EDL replace with optimistic concurrency."""
    _job_or_404(job_id)
    old_edl, old_revision = load_edl(job_id)
    edl_payload = body.get("edl") if isinstance(body, dict) else None
    if edl_payload is None:
        raise HTTPException(status_code=400, detail="body must contain an 'edl' key")
    try:
        stored, new_rev = save_edl(
            job_id, edl_payload, source="user",
            base_revision=body.get("base_revision") if isinstance(body, dict) else None,
        )
    except RevisionConflict as e:
        raise HTTPException(status_code=409, detail={"stale_revision": e.current_revision})
    except EDLValidationError as e:
        raise HTTPException(status_code=422, detail=str(e))
    record_activity(job_id, "edl_store", "edl_replace", status="succeeded",
                    revision_before=old_revision, revision_after=new_rev,
                    detail=f"Full EDL replace -> rev {new_rev}")
    return {"ok": True, "edl": stored, "revision": new_rev}


@router.post("/edl/operations")
async def post_edl_operations(job_id: str, body: Dict[str, Any]):
    """Apply a batch of structured timeline operations."""
    _job_or_404(job_id)
    edl, revision = _edl_or_404(job_id)
    base = body.get("base_revision")
    if base is not None and int(base) != int(revision):
        raise HTTPException(status_code=409, detail={"stale_revision": revision})
    ops = body.get("operations") or []
    # remove_silence needs server-side macro data; compute the silence ranges
    # from the job's narration/audio sources (empty ranges -> clean 422 later).
    context: Optional[Dict[str, Any]] = None
    silence_ops = [o for o in ops if isinstance(o, dict)
                   and str(o.get("op") or "").strip() == "remove_silence"]
    if silence_ops:
        _nd, _md = _SILENCE_NOISE_DB, _SILENCE_MIN_DURATION
        for o in silence_ops:  # honor the client's thresholds when provided
            args = o.get("args") if isinstance(o.get("args"), dict) else o
            _nd = float(args.get("noise_db", _nd) or _nd)
            _md = float(args.get("min_silence", args.get("min_duration", _md)) or _md)
        # silencedetect shells out to ffmpeg — keep it off the event loop.
        context = await asyncio.to_thread(
            audio_silence_context, edl, revision=revision, job_id=job_id,
            noise_db=_nd, min_silence=_md)
        record_activity(job_id, "audio_analyzer", "silence_scan", status="succeeded",
                        revision_before=revision, revision_after=revision,
                        detail=f"silence ranges for context: "
                               f"{len((context or {}).get('silence_ranges') or [])} found")

    try:
        if body.get("dry_run"):
            _plan, info = plan_operations(edl, ops, context=context)
            return {"ok": True, "dry_run": True, "plan": info, "revision": revision}
        new_edl, results = apply_operations(edl, ops, context=context, strict=False)
    except OperationValidationError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except EDLValidationError as e:
        raise HTTPException(status_code=422, detail=str(e))
    applied = [r for r in results if r.get("ok")]
    if not applied:
        raise HTTPException(status_code=422,
                            detail={"message": "no valid operations applied", "results": results})

    try:
        stored, new_rev = save_edl(job_id, new_edl, source="user", operations=ops)
    except RevisionConflict as e:
        raise HTTPException(status_code=409, detail={"stale_revision": e.current_revision})
    except EDLValidationError as e:
        raise HTTPException(status_code=422, detail=str(e))

    for r in applied:
        record_activity(job_id, "edl_store", str(r.get("op") or "operation"),
                        status="succeeded",
                        clip_ids=(r.get("affected") or [])[:5],
                        revision_before=revision, revision_after=new_rev,
                        detail=str(r.get("note") or r.get("op") or ""))
    if any(str((o.get("args") or {}).get("kind") or "") == "generated" for o in ops):
        asyncio.create_task(asyncio.to_thread(_materialize_generated_now, job_id, stored))
    return {"ok": True, "edl": stored, "revision": new_rev,
            "results": results, "summary": edl_summary(stored)}


@router.post("/timeline/command")
async def post_timeline_command(job_id: str, body: Dict[str, Any]):
    """Low-level single validated command (keyboard fast path / debugging).

    Same operation vocabulary and validation as ``/edl/operations``, limited to
    one operation so a bad command can never partially apply. Returns the
    stored EDL, the new revision, and the command result.
    """
    _job_or_404(job_id)
    edl, revision = _edl_or_404(job_id)
    base = body.get("base_revision")
    if base is not None and int(base) != int(revision):
        raise HTTPException(status_code=409, detail={"stale_revision": revision})
    command = body.get("operation") if isinstance(body.get("operation"), dict) else body
    if not isinstance(command, dict) or not str(command.get("op") or "").strip():
        raise HTTPException(status_code=400, detail="body must contain a single 'op'")
    if isinstance(command.get("operations"), list) and len(command["operations"]) > 1:
        raise HTTPException(status_code=400,
                            detail="this endpoint accepts exactly one operation")

    context: Optional[Dict[str, Any]] = None
    if str(command.get("op")) == "remove_silence":
        context = await asyncio.to_thread(
            audio_silence_context, edl, revision=revision, job_id=job_id,
            noise_db=_SILENCE_NOISE_DB, min_silence=_SILENCE_MIN_DURATION)
    try:
        new_edl, results = apply_operations(edl, [command], context=context, strict=True)
    except OperationValidationError as e:
        record_activity(job_id, "timeline_agent", str(command.get("op")), status="rejected",
                        revision_before=revision, revision_after=revision,
                        detail=str(e)[:240])
        raise HTTPException(status_code=422, detail=str(e))
    except EDLValidationError as e:
        raise HTTPException(status_code=422, detail=str(e))

    try:
        stored, new_rev = save_edl(job_id, new_edl, source="user", operations=[command])
    except RevisionConflict as e:
        raise HTTPException(status_code=409, detail={"stale_revision": e.current_revision})
    except EDLValidationError as e:
        raise HTTPException(status_code=422, detail=str(e))

    result = results[0] if results else {}
    record_activity(job_id, "timeline_agent", str(command.get("op")), status="succeeded",
                    clip_ids=(result.get("affected") or [])[:5],
                    revision_before=revision, revision_after=new_rev,
                    detail=str(result.get("note") or command.get("op") or ""))
    return {"ok": True, "edl": stored, "revision": new_rev, "result": result,
            "summary": edl_summary(stored)}


@router.get("/edl/silence")
async def get_edl_silence(
    job_id: str,
    min_duration: Optional[float] = None,
    noise_db: Optional[float] = None,
):
    """Silence detection endpoint.

    Runs ffmpeg ``silencedetect`` over the job's narration/audio sources and
    returns qualifying ranges in project seconds — the same ranges the
    ``remove_silence`` macro consumes via the server-built op context. Degrades
    to an empty range list when ffmpeg or the temp audio files are unavailable.
    """
    _job_or_404(job_id)
    edl, revision = _edl_or_404(job_id)
    nd = float(noise_db) if noise_db is not None else _SILENCE_NOISE_DB
    md = float(min_duration) if min_duration is not None else _SILENCE_MIN_DURATION
    paths = job_audio_paths(edl)
    # ffprobe/ffmpeg run as subprocesses: keep them off the event loop.
    report = await asyncio.to_thread(
        cached_job_audio, job_id, revision, paths, noise_db=nd, min_silence=md)
    return {
        "job_id": job_id,
        "revision": revision,
        "noise_db": nd,
        "min_silence": md,
        "sources_analyzed": len(paths),
        "silence_ranges": report.get("silence_ranges") or [],
        "duration": report.get("duration") or 0.0,
    }


@router.get("/edl/revisions")
async def get_edl_revisions(job_id: str):
    _job_or_404(job_id)
    return {"job_id": job_id, "revisions": list_revisions(job_id)}


@router.get("/edl/revisions/{revision}")
async def get_edl_revision(job_id: str, revision: int):
    _job_or_404(job_id)
    doc = get_revision(job_id, revision)
    if not doc:
        raise HTTPException(status_code=404, detail=f"revision {revision} not found")
    return doc


@router.get("/edl.otio")
async def get_edl_otio(job_id: str, revision: Optional[int] = None):
    """Download this EDL/revision as an OpenTimelineIO JSON file."""
    _job_or_404(job_id)
    if revision is not None:
        doc = get_revision(job_id, revision)
        if not doc or not doc.get("edl"):
            raise HTTPException(status_code=404, detail=f"revision {revision} not found")
        edl = doc["edl"]
    else:
        edl, _ = _edl_or_404(job_id)
    try:
        payload = edl_to_otio_json(edl)
    except Exception as e:  # pragma: no cover - defensive
        logger.error("OTIO export failed for %s: %s", job_id, e)
        raise HTTPException(status_code=500, detail=f"OTIO export failed: {e}")
    return Response(content=payload, media_type="application/json",
                    headers={"Content-Disposition":
                             f'attachment; filename="{job_id}.otio"'})


# --------------------------------------------------------------------------
# render
# --------------------------------------------------------------------------
@router.post("/render")
async def queue_render(job_id: str, body: Dict[str, Any]):
    """Queue a preview or final render of the current revision."""
    _job_or_404(job_id)
    edl, revision = _edl_or_404(job_id)
    if body.get("revision") is not None and int(body["revision"]) != int(revision):
        raise HTTPException(status_code=409, detail={"stale_revision": revision})
    profile = str(body.get("profile") or "preview_480")
    if profile not in ALLOWED_PROFILE_RESOLUTIONS:
        raise HTTPException(status_code=400, detail=f"unknown profile {profile!r}")
    kind = "final" if str(body.get("kind") or "preview") == "final" else "preview"

    dispatcher = settings.render_dispatcher
    doc = create_render(job_id, revision=revision, profile=profile,
                        kind=kind, dispatcher=dispatcher)
    render_id = doc["render_id"]

    dispatched = False
    try:
        if dispatcher == "modal":
            dispatched = dispatch_modal(job_id, render_id, revision, profile)
        elif dispatcher == "actions":
            dispatched = dispatch_actions(job_id, render_id, revision, profile)
    except Exception as e:  # dispatch failures fall back to the local worker
        logger.warning("render dispatch failed, falling back to local: %s", e)

    if not dispatched:
        asyncio.create_task(_run_local_render(
            job_id, render_id, edl, revision, profile, kind))
    else:
        record_activity(job_id, "render_worker", "render_dispatch", status="succeeded",
                        revision_before=revision, revision_after=revision,
                        detail=f"{kind} render {render_id} dispatched via {dispatcher}")

    JobStateService.append_event(job_id, {
        "stage": "render_queued", "message": f"{kind} render queued ({profile}).",
        "render_id": render_id, "progress_percent": None,
    })
    return {"ok": True, "render_id": render_id, "status": "QUEUED",
            "revision": revision, "profile": profile, "kind": kind,
            "dispatcher": dispatcher}


async def _run_local_render(job_id: str, render_id: str, edl: Dict[str, Any],
                            revision: int, profile: str, kind: str):
    """In-container render used when no external dispatcher is available."""
    try:
        out_dir = render_dir(job_id, render_id)
        os.makedirs(out_dir, exist_ok=True)
        out_path = os.path.join(out_dir, f"{profile}.mp4")

        def progress_cb(pct: int, msg: str) -> None:
            try:
                from app.services.firestore_service import JobStateService
                JobStateService.append_event(job_id, {
                    "stage": "render_progress",
                    "message": f"[{profile}] {msg}",
                    "render_id": render_id,
                    "render_progress": int(pct),
                })
            except Exception:
                pass

        mark_status(job_id, render_id, "RENDERING")
        report = await render_edl(edl, out_path, profile_name=profile,
                                  job_id=job_id, progress_cb=progress_cb)
        if report.get("ok") and os.path.exists(out_path):
            check = quick_render_check(out_path, kind=kind)
            duration = float(check.get("duration") or 0.0)
            mark_status(job_id, render_id, "READY", path=out_path,
                        url=f"/api/v1/jobs/{job_id}/renders/{render_id}/video",
                        duration=duration,
                        error=str(report.get("error") or "") if not check.get("pass") else "")
            try:
                write_otio(edl, os.path.join(out_dir, f"{profile}.otio"))
            except Exception:
                pass
            record_activity(job_id, "render_worker", "render", status="succeeded",
                            revision_before=revision, revision_after=revision,
                            detail=f"{profile} render ready ({duration:.1f}s)")
        else:
            mark_status(job_id, render_id, "FAILED",
                        error=str(report.get("error") or "render failed")[:300])
            record_activity(job_id, "render_worker", "render", status="failed",
                            revision_before=revision,
                            detail=str(report.get("error") or "render failed")[:240])
    except Exception as e:
        logger.exception("local render %s failed", render_id)
        mark_status(job_id, render_id, "FAILED", error=str(e)[:300])
        record_activity(job_id, "render_worker", "render", status="failed",
                        detail=str(e)[:240])


@router.get("/renders")
async def get_renders(job_id: str):
    """Render history for a job (newest last) — powers the stale badge."""
    _job_or_404(job_id)
    return {"job_id": job_id, "renders": list_renders(job_id)}


@router.get("/renders/{render_id}")
async def get_render_status(job_id: str, render_id: str):
    _job_or_404(job_id)
    return _render_doc_or_404(job_id, render_id)


@router.get("/renders/{render_id}/video")
async def render_video(job_id: str, render_id: str, request: Request):
    _job_or_404(job_id)
    doc = _render_doc_or_404(job_id, render_id)
    path = resolve_job_path(job_id, str(doc.get("path") or ""))
    if not doc.get("path") or not path or not os.path.exists(path):
        raise HTTPException(status_code=404, detail="Render file missing")
    if not resolve_job_path(job_id, str(doc.get("path") or "")):
        raise HTTPException(status_code=403, detail="Invalid render path")
    # Deferred import: main.py imports this router at startup.
    from app.main import _serve_file_range
    return _serve_file_range(request, path, media_type="video/mp4")
