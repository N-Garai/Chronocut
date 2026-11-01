"""Aspect-corrected, subject-aware framing for profile exports.

A 16:9 project rendered to 9:16, 1:1 or 21:9 needs a real crop decision per
clip, not a blind center cut. Two layers:

* **Deterministic (always on):** pure aspect math produces the crop window that
  fills the target frame from the source aspect, centred by default.
* **Subject-aware (optional):** when a vision provider is configured, a capped
  number of sources get a subject box and the window shifts to keep that
  subject inside the frame. Failure simply returns the centred window.

Focus points are computed once when the EDL is built and stored in the job's
agent context, so rendering never spends model calls per profile.
"""
import logging
import os
import subprocess
from typing import Any, Dict, Iterable, List, Optional, Tuple

logger = logging.getLogger("chronocut.tools.media.reframe")

DEFAULT_ASPECT = 16.0 / 9.0
MAX_SUBJECT_PROBES = 8

__all__ = ["aspect_crop", "source_aspect", "compute_focus", "reframe_sources",
           "apply_reframe_to_edl", "aspect_of_profile"]


def aspect_of_profile(width: int, height: int) -> float:
    try:
        w, h = int(width), int(height)
        if w <= 0 or h <= 0:
            return DEFAULT_ASPECT
        return float(w) / float(h)
    except (TypeError, ValueError, ZeroDivisionError):
        return DEFAULT_ASPECT


def aspect_crop(source_aspect: float, target_aspect: float,
                focus_x: float = 0.5, focus_y: float = 0.5) -> Optional[Dict[str, float]]:
    """Crop window (fractions trimmed per edge) that fills ``target_aspect``.

    Returns ``None`` when the aspects already match closely (no crop needed).
    """
    try:
        s = float(source_aspect)
        t = float(target_aspect)
    except (TypeError, ValueError):
        return None
    if s <= 0 or t <= 0 or abs(s - t) < 0.01:
        return None

    if s > t:                      # source wider than target -> trim sides
        keep = t / s               # window width as a fraction of the source
        fx = min(max(float(focus_x), 0.0), 1.0)
        left = min(max(fx - keep / 2.0, 0.0), 1.0 - keep)
        return {"left": round(left, 4), "top": 0.0,
                "right": round(max(0.0, 1.0 - keep - left), 4), "bottom": 0.0}

    keep = s / t                   # source taller than target -> trim top/bottom
    fy = min(max(float(focus_y), 0.0), 1.0)
    top = min(max(fy - keep / 2.0, 0.0), 1.0 - keep)
    return {"left": 0.0, "top": round(top, 4),
            "right": 0.0, "bottom": round(max(0.0, 1.0 - keep - top), 4)}


def source_aspect(path: Optional[str]) -> Optional[float]:
    """Width/height of a still or clip via ffprobe; ``None`` when unknown."""
    if not path or not os.path.isfile(path):
        return None
    try:
        out = subprocess.run(
            ["ffprobe", "-v", "error", "-select_streams", "v:0",
             "-show_entries", "stream=width,height",
             "-of", "default=noprint_wrappers=1:nokey=1", path],
            capture_output=True, text=True, timeout=20,
        )
        vals = [v for v in (out.stdout or "").split() if v.strip().isdigit()]
        if len(vals) >= 2:
            w, h = int(vals[0]), int(vals[1])
            if w > 0 and h > 0:
                return w / h
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError, ValueError):
        return None
    return None


def _vision_configured() -> bool:
    try:
        from app.config import settings
        return bool(getattr(settings, "provider_api_key", None))
    except Exception:
        return False


def compute_focus(media_path: Optional[str], job_id: Optional[str] = None,
                  *, prompt: str = "person") -> Optional[Tuple[float, float]]:
    """Subject centre (normalized) for one source; ``None`` when unavailable."""
    if not media_path or not _vision_configured():
        return None
    try:
        from app.tools.vision.sam_reframe import subject_box
        box = subject_box(media_path, prompt, job_id=job_id)
        if not box:
            return None
        return ((box[0] + box[2]) / 2.0, (box[1] + box[3]) / 2.0)
    except Exception as e:
        logger.debug("subject focus unavailable for %s: %s", media_path, e)
        return None


def reframe_sources(sources: Iterable[Dict[str, Any]], job_id: Optional[str] = None,
                    *, cap: int = MAX_SUBJECT_PROBES) -> Dict[str, Dict[str, float]]:
    """Compute subject focus for up to ``cap`` visual sources.

    Called once per job when the EDL is built; results live in agent context so
    renders stay free of model calls.
    """
    from app.services.storage import resolve_job_path
    out: Dict[str, Dict[str, float]] = {}
    probed = 0
    for src in sources or []:
        if probed >= cap:
            break
        if not isinstance(src, dict):
            continue
        kind = str(src.get("type") or "")
        if kind not in ("image", "video"):
            continue
        path = resolve_job_path(str(job_id or ""), str(src.get("path") or ""))
        focus = compute_focus(path, job_id)
        probed += 1
        if focus:
            out[str(src.get("id"))] = {"x": round(focus[0], 4), "y": round(focus[1], 4)}
    return out


def apply_reframe_to_edl(edl: Dict[str, Any], width: int, height: int,
                         focus: Optional[Dict[str, Dict[str, float]]] = None) -> int:
    """Set ``transform.crop`` on clips that need it for this profile.

    Existing explicit crops win; clips whose source already matches the target
    aspect are left alone. Returns the number of clips reframed.
    """
    target = aspect_of_profile(width, height)
    sources = {str(s.get("id")): s for s in (edl.get("sources") or []) if isinstance(s, dict)}
    focus = focus or {}
    changed = 0
    for track in edl.get("tracks") or []:
        if str(track.get("id") or "") != "v1":
            continue
        for clip in track.get("clips") or []:
            tr = clip.get("transform") if isinstance(clip.get("transform"), dict) else {}
            if tr.get("crop"):
                continue                        # author/agent decided already
            src = sources.get(str(clip.get("source_id"))) or {}
            s_aspect = float(src.get("aspect") or 0.0) or source_aspect(
                str(src.get("path") or "")) or DEFAULT_ASPECT
            f = focus.get(str(clip.get("source_id"))) or {}
            window = aspect_crop(s_aspect, target, float(f.get("x", 0.5)), float(f.get("y", 0.5)))
            if not window:
                continue
            tr = dict(tr)
            tr["crop"] = window
            clip["transform"] = tr
            changed += 1
    return changed


def focus_from_context(job_id: Optional[str]) -> Dict[str, Dict[str, float]]:
    """Focus map recorded by the render/framer stage, if any."""
    try:
        from app.agents.agent_context import entries_for
        out: Dict[str, Dict[str, float]] = {}
        for row in entries_for(job_id, "render"):
            focus = ((row.get("data") or {}).get("focus") or {})
            for sid, xy in focus.items():
                if isinstance(xy, dict):
                    out[str(sid)] = {"x": float(xy.get("x", 0.5)), "y": float(xy.get("y", 0.5))}
        return out
    except Exception:
        return {}
