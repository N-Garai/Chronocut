"""Path resolution for uploads, generated assets, renders, and logs.

Every temporary path in the app flows through this module so containers can
mount the working volume wherever the host provides it (Modal volume at
``/data``, local ``/tmp``, a Render ephemeral dir, or a repo-local ``tmp``).
Set ``CHRONOCUT_TMP_DIR`` to move the whole tree; nothing else needs changing.
"""
import os
import re
import uuid
from typing import Optional

from app.config import settings

_JOB_ID_RE = re.compile(r"[^a-zA-Z0-9_-]")


def _base_dir() -> str:
    """Root tmp dir: CHRONOCUT_TMP_DIR if set, else `tmp/` in the repo root."""
    d = (settings.CHRONOCUT_TMP_DIR or "").strip()
    if d:
        return d
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "..", "tmp")


def ensure_dir(path: str) -> str:
    os.makedirs(path, exist_ok=True)
    return path


def tmp_dir() -> str:
    """The single source of truth for all root-level temporary paths."""
    return ensure_dir(_base_dir())


def safe_job_id(job_id: str) -> str:
    return _JOB_ID_RE.sub("", str(job_id or ""))[:80]


def job_dir(job_id: str) -> str:
    return ensure_dir(os.path.join(tmp_dir(), f"chronocut_{safe_job_id(job_id)}"))


def job_upload_dir(job_id: str) -> str:
    return ensure_dir(os.path.join(job_dir(job_id), "input"))


def asset_dir(job_id: str, subdir: str = "") -> str:
    base = job_dir(job_id)
    out = ensure_dir(os.path.join(base, "assets")) if not subdir else ensure_dir(
        os.path.join(base, "assets", subdir))
    return out


def render_dir(job_id: str, render_id: str) -> str:
    return ensure_dir(os.path.join(job_dir(job_id), "renders", safe_job_id(render_id)))


def logs_dir() -> str:
    return ensure_dir(os.path.join(tmp_dir(), "logs"))


def safe_filename(name: str) -> str:
    """Filename-safe unique name that keeps the original extension."""
    original = os.path.basename(name or "")
    stem, ext = os.path.splitext(original)
    stem = _JOB_ID_RE.sub("_", stem)[:60] or "media"
    ext = ext[:16]
    return f"{stem}_{uuid.uuid4().hex[:8]}{ext}"


def resolve_media_path(job_id: Optional[str], filename: str) -> str:
    """_resolve path for an uploaded file for a given job."""
    fname = safe_filename(filename)
    if job_id:
        return os.path.join(job_upload_dir(job_id), fname)
    return os.path.join(ensure_dir(os.path.join(tmp_dir(), "chronocut_uploads")), fname)


def resolve_job_path(job_id: str, rel: str) -> str:
    """Resolve a path stored in the database relative to the current tmp root.

    Database records hold absolute destinations that must stay valid across
    container restarts and volume remounts; this re-keys them onto the live
    ``tmp_dir()`` root when it differs from the recorded one.
    """
    if not rel:
        return rel
    if os.path.exists(rel):
        return rel
    marker = "chronocut_"
    idx = rel.find(marker)
    if idx < 0:
        return rel
    return os.path.join(tmp_dir(), rel[idx:])
