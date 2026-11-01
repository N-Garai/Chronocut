"""Asset listing and cached thumbnails for the timeline asset bin.

The asset bin needs metadata for every source the EDL references: what it is,
whether the file is actually on this container, and a small preview. Thumbnails
are generated once with FFmpeg and cached under the job's asset tree so repeat
loads are free. Everything degrades: a missing file, a missing FFmpeg binary, or
a failed encode yields ``thumb_url: None`` instead of an error.
"""
import logging
import os
import subprocess
from typing import Any, Dict, List, Optional

from app.services.storage import asset_dir, resolve_job_path

logger = logging.getLogger("chronocut.tools.media.thumbnails")

THUMB_WIDTH = 320
_THUMB_TIMEOUT_S = 25
_MEDIA_EXT = {
    "image": {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".gif", ".tif", ".tiff"},
    "video": {".mp4", ".mov", ".webm", ".mkv", ".m4v"},
    "narration": {".wav", ".mp3", ".m4a", ".flac", ".ogg"},
    "music": {".wav", ".mp3", ".m4a", ".flac", ".ogg"},
}


def _kind_of(source: Dict[str, Any]) -> str:
    t = str(source.get("type") or "image").lower()
    return t if t in _MEDIA_EXT else "image"


def thumb_path(job_id: str, asset_id: str) -> str:
    return os.path.join(asset_dir(str(job_id), "thumbs"), f"{os.path.basename(str(asset_id))}.png")


def _run_ffmpeg(args: List[str]) -> bool:
    try:
        res = subprocess.run(args, capture_output=True, timeout=_THUMB_TIMEOUT_S)
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError) as e:
        logger.warning("thumbnail ffmpeg unavailable: %s", e)
        return False
    if res.returncode != 0:
        logger.warning("thumbnail ffmpeg rc=%s: %s", res.returncode,
                       (res.stderr or b"")[-200:].decode("utf-8", "ignore"))
        return False
    return True


def ensure_thumbnail(job_id: str, asset_id: str, path: Optional[str],
                     kind: str = "image") -> Optional[str]:
    """Return a cached 320px-wide PNG for this asset, generating it if needed."""
    if kind not in ("image", "video"):
        return None
    out = thumb_path(job_id, asset_id)
    if os.path.isfile(out) and os.path.getsize(out) > 0:
        return out
    if not path or not os.path.isfile(path):
        return None
    stem = os.path.splitext(out)[0]
    part = f"{stem}.part.png"
    args = ["ffmpeg", "-y", "-loglevel", "error", "-i", path]
    if kind == "video":
        args += ["-ss", "0.2"]
    args += ["-frames:v", "1", "-vf", f"scale={THUMB_WIDTH}:-2", part]
    if not _run_ffmpeg(args):
        for leftover in (part,):
            if os.path.exists(leftover):
                try:
                    os.remove(leftover)
                except OSError:
                    pass
        return None
    try:
        os.replace(part, out)
    except OSError:
        return None
    return out


def waveform_path(job_id: str, asset_id: str) -> str:
    return os.path.join(asset_dir(str(job_id), "waveforms"),
                        f"{os.path.basename(str(asset_id))}.png")


def ensure_waveform(job_id: str, asset_id: str, path: Optional[str],
                    *, width: int = 1200, height: int = 120) -> Optional[str]:
    """Cached waveform PNG for one audio asset (FFmpeg showwavespic).

    Degrades to ``None`` when the file is missing or FFmpeg cannot run, so the
    timeline simply shows no waveform instead of failing.
    """
    out = waveform_path(job_id, asset_id)
    if os.path.isfile(out) and os.path.getsize(out) > 0:
        return out
    if not path or not os.path.isfile(path):
        return None
    part = os.path.splitext(out)[0] + ".part.png"
    args = [
        "ffmpeg", "-y", "-loglevel", "error", "-i", path,
        "-filter_complex",
        f"showwavespic=s={int(width)}x{int(height)}:colors=#7dd3fc",
        "-frames:v", "1", part,
    ]
    if not _run_ffmpeg(args):
        if os.path.exists(part):
            try:
                os.remove(part)
            except OSError:
                pass
        return None
    try:
        os.replace(part, out)
    except OSError:
        return None
    return out


def describe_source(job_id: str, source: Dict[str, Any]) -> Dict[str, Any]:
    """One asset row: identity, kind, on-disk metadata, and preview URL."""
    sid = str(source.get("id") or "")
    kind = _kind_of(source)
    raw = str(source.get("path") or "")
    path = resolve_job_path(str(job_id), raw) if raw else ""
    exists = bool(path) and os.path.isfile(path)
    row: Dict[str, Any] = {
        "asset_id": sid,
        "id": sid,
        "kind": kind,
        "type": kind,
        "name": os.path.basename(path) if path else sid,
        "generated": bool(source.get("generated")),
        "degraded": source.get("degraded"),
        "prompt": source.get("prompt"),
        "available": exists,
        "bytes": os.path.getsize(path) if exists else 0,
        "thumb_url": None,
    }
    if exists and kind in ("image", "video"):
        thumb = ensure_thumbnail(str(job_id), sid or "asset", path, kind)
        if thumb:
            row["thumb_url"] = f"/api/v1/jobs/{job_id}/assets/{sid}/thumb"
    return row


def list_assets(job_id: str, edl: Optional[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """All EDL sources as asset rows, ordered as the EDL lists them."""
    sources = (edl or {}).get("sources") or []
    rows: List[Dict[str, Any]] = []
    for source in sources:
        if isinstance(source, dict):
            rows.append(describe_source(str(job_id), source))
    return rows


__all__ = ["ensure_thumbnail", "ensure_waveform", "describe_source", "list_assets",
           "thumb_path", "waveform_path"]
