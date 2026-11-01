"""Render records and render dispatch.

Each queued render creates a ``renders/{render_id}`` document:
``job_id, revision, profile, kind, status, path, url, storage, duration_seconds,
error, created_at, updated_at``. The dispatcher is chosen server-side
(``local`` | ``actions`` | ``modal``); the frontend never chooses it.
"""
import asyncio
import logging
import os
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from app.config import settings
from app.services.firestore_service import JobStateService, get_firestore_client

logger = logging.getLogger("chronocut.services.renders")

RENDERS_COLLECTION = "renders"
ACTIVE_STATUSES = {"QUEUED", "RENDERING"}
TERMINAL_OK = "READY"
TERMINAL_FAIL = "FAILED"


def new_render_id() -> str:
    return f"r-{uuid.uuid4().hex[:10]}"


def _now() -> datetime:
    return datetime.now(timezone.utc)


def create_render(job_id: str, *, revision: int, profile: str, kind: str,
                  dispatcher: str = "local") -> Dict[str, Any]:
    render_id = new_render_id()
    doc = {
        "render_id": render_id,
        "job_id": str(job_id),
        "revision": int(revision),
        "profile": profile,
        "kind": kind if kind in ("preview", "final") else "preview",
        "status": "QUEUED",
        "dispatcher": dispatcher,
        "path": "",
        "url": "",
        "storage": "volume" if dispatcher == "local" else "external",
        "duration_seconds": 0.0,
        "error": "",
        "created_at": _now(),
        "updated_at": _now(),
        "_expire_at": _now().replace(microsecond=0).__class__.fromtimestamp(
            _now().timestamp() + settings.DATA_RETENTION_HOURS * 3600, tz=timezone.utc),
    }
    try:
        JobStateService._put_doc(RENDERS_COLLECTION, render_id, doc)
        JobStateService.update_job(str(job_id), {
            "render_id": render_id, "render_status": "QUEUED",
            "render_profile": profile, "provider": settings.LLM_PROVIDER,
            "dispatcher": dispatcher,
        })
        JobStateService.append_event(str(job_id), {
            "stage": "render_queued", "progress_percent": None,
            "message": f"{kind} render queued ({profile}, rev {revision}).",
            "render_id": render_id,
        })
    except Exception as e:
        logger.error("create_render failed: %s", e)
    return doc


def update_render(render_id: str, updates: Dict[str, Any]) -> None:
    updates = {**updates, "updated_at": _now()}
    try:
        JobStateService._patch_doc(RENDERS_COLLECTION, render_id, updates)
    except Exception as e:
        logger.error("update_render failed for %s: %s", render_id, e)


def list_renders(job_id: str, limit: int = 20) -> List[Dict[str, Any]]:
    """Renders for a job, newest last."""
    try:
        from app.services import firestore_service as _fs
    except Exception:  # pragma: no cover - defensive
        return []
    client = _fs.get_firestore_client()
    if client is None:
        with _fs._local_lock:
            _fs._load_local()
            items = [d for d in _fs._local_data.get(RENDERS_COLLECTION, {}).values()
                     if str(d.get("job_id")) == str(job_id)]
        items.sort(key=lambda d: str(d.get("created_at") or ""))
        return items[-int(limit):]
    try:
        docs = (client.collection(RENDERS_COLLECTION)
                .where("job_id", "==", str(job_id))
                .order_by("created_at").limit(int(limit)).stream())
        return [d.to_dict() for d in docs]
    except Exception as e:  # pragma: no cover
        logger.error("list_renders failed for %s: %s", job_id, e)
        return []


def get_render(render_id: str) -> Optional[Dict[str, Any]]:
    return JobStateService._get_doc(RENDERS_COLLECTION, render_id)


def mark_status(job_id: Optional[str], render_id: str, status: str, *,
                path: str = "", url: str = "", duration: float = 0.0,
                error: str = "") -> None:
    updates: Dict[str, Any] = {"status": status, "path": path, "url": url,
                               "duration_seconds": float(duration), "error": error}
    update_render(render_id, updates)
    fin = status in (TERMINAL_OK, TERMINAL_FAIL)
    if job_id:
        job_updates = {"render_status": status, "render_id": render_id}
        if fin:
            job_updates["timeline_updated_at"] = _now()
            if status == TERMINAL_OK:
                job_updates["last_render_url"] = url or ""
            JobStateService.append_event(str(job_id), {
                "stage": "render_ready" if status == TERMINAL_OK else "render_failed",
                "progress_percent": None,
                "message": (f"Render ready: {url}" if status == TERMINAL_OK
                            else f"Render failed: {error or 'unknown error'}"),
                "render_id": render_id, "status": status, "video_url": url or None,
            })
        JobStateService.update_job(str(job_id), job_updates)


# ---------------------------------------------------------------------------
# dispatch
# ---------------------------------------------------------------------------
def dispatch_actions(job_id: str, render_id: str, revision: int, profile: str) -> bool:
    """GitHub repository_dispatch to the render worker (Path B)."""
    import requests

    token = settings.GH_DISPATCH_TOKEN
    repo = settings.GH_REPO
    if not token or not repo:
        logger.warning("actions dispatcher configured without GH_DISPATCH_TOKEN/GH_REPO; using local")
        return False
    try:
        resp = requests.post(
            f"https://api.github.com/repos/{repo}/dispatches",
            headers={
                "Authorization": f"Bearer {token}",
                "Accept": "application/vnd.github+json",
            },
            json={"event_type": "chronocut-render",
                  "client_payload": {"job_id": job_id, "render_id": render_id,
                                     "revision": int(revision), "profile": profile}},
            timeout=30,
        )
        if resp.status_code in (204, 200):
            logger.info("repository_dispatch accepted (%s/%s rev %s)", job_id, render_id, revision)
            return True
        logger.error("repository_dispatch refused (%s): %s", resp.status_code, resp.text[:200])
        return False
    except Exception as e:
        logger.error("repository_dispatch failed: %s", e)
        return False


def dispatch_modal(job_id: str, render_id: str, revision: int, profile: str) -> bool:
    """Path A (Modal) render spawn — only when MODAL_ENABLED."""
    if not settings.MODAL_ENABLED:
        return False
    try:
        # Modal spawns a detached function; importing inside keeps the API
        # container importable without the modal package installed.
        from app.modal_render import spawn_render  # type: ignore

        asyncio.get_event_loop().create_task(spawn_render(job_id, render_id, revision, profile))
        return True
    except Exception as e:
        logger.warning("modal dispatch unavailable: %s", e)
        return False
