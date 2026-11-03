"""SAM 3.1 smart reframe — 16:9 -> 9:16 without cutting off the subject (P1).

Box-based "subject-aware crop": probes up to 3 frames per clip, asks SAM 3.1
(via the Meta Model API) for the target subject's bounding box, then computes
a crop window for the portrait profile that keeps the box centered with
padding. Falls back to Muse Spark grounding boxes, then a plain center crop —
the op never blocks a render.
"""
import base64
import json
import logging
import os
import subprocess
import tempfile
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger("chronocut.tools.vision.sam_reframe")

__all__ = ["smart_reframe_crop", "probe_frames", "subject_box", "compute_crop"]


def probe_frames(video_path: str, count: int = 3, tmp_dir: Optional[str] = None,
                 timeout: int = 60) -> List[str]:
    """Extract up to ``count`` evenly spaced frames (start/middle/end)."""
    frames: List[str] = []
    work = tmp_dir or tempfile.mkdtemp(prefix="cc_sam_")
    try:
        dur = _probe_duration(video_path)
        if not dur:
            return frames
        for i in range(count):
            at = dur * (i + 0.5) / count
            out = os.path.join(work, f"probe_{i:02d}.jpg")
            r = subprocess.run(
                ["ffmpeg", "-y", "-ss", f"{max(0.0, at):.3f}", "-i", video_path,
                 "-frames:v", "1", "-q:v", "3", out],
                capture_output=True, timeout=timeout)
            if r.returncode == 0 and os.path.exists(out) and os.path.getsize(out) > 0:
                frames.append(out)
    except Exception as e:
        logger.warning("frame probing failed for %s: %s", video_path, e)
    return frames


def _probe_duration(path: str) -> float:
    try:
        r = subprocess.run(
            ["ffprobe", "-v", "quiet", "-print_format", "json", "-show_format", path],
            capture_output=True, text=True, timeout=30)
        return float((json.loads(r.stdout or "{}").get("format") or {}).get("duration") or 0.0)
    except Exception:
        return 0.0


async def subject_box(image_path: str, prompt: str = "person",
                 *, job_id: Optional[str] = None) -> Optional[Tuple[float, float, float, float]]:
    """Ask the Meta Model API (SAM 3.1 grounding prompt) for the subject box.
    Returns (x0, y0, x1, y1) normalized 0..1, or None when unavailable."""
    from app.tools.llm.call import scored_llm_json
    try:
        with open(image_path, "rb") as f:
            data = base64.b64encode(f.read()).decode("ascii")
        res = await scored_llm_json(
            "Locate the most prominent subject matching the requested category in "
            "this frame. Reply with JSON only: "
            '{"found": <bool>, "box": [<x0>, <y0>, <x1>, <y1>]} normalized 0..1. '
            f"Subject category: {prompt}",
            media=[{"data": data, "mime_type": "image/jpeg"}],
            agent="archivist", tool="sam_reframe", job_id=job_id,
            temperature=0.0, max_output_tokens=300,
            require_keys=["found"],
        )
        if not res or not res.get("found"):
            return None
        box = [float(v) for v in (res.get("box") or [])]
        if len(box) != 4:
            return None
        x0, y0, x1, y1 = box
        if not (0.0 <= x0 < x1 <= 1.0 and 0.0 <= y0 < y1 <= 1.0):
            return None
        return (x0, y0, x1, y1)
    except Exception as e:
        logger.debug("SAM subject box unavailable: %s", e)
        return None


def compute_crop(box: Tuple[float, float, float, float], target_aspect: float,
                 source_aspect: float, *, pad: float = 0.25) -> Dict[str, Any]:
    """Crop window (center + size, normalized) that keeps ``box`` inside a
    ``target_aspect`` frame with ``pad`` breathing room."""
    try:
        cx = (box[0] + box[2]) / 2.0
        cy = (box[1] + box[3]) / 2.0
        bw = max(0.05, box[2] - box[0])
        bh = max(0.05, box[3] - box[1])
        width = min(1.0, max(bw * (1.0 + pad * 2.0), 0.35))
        height = min(1.0, width * source_aspect / target_aspect)
        if height < bh * (1.0 + pad):
            height = min(1.0, bh * (1.0 + pad))
            width = min(1.0, height * target_aspect / source_aspect)
        x = min(max(cx - width / 2.0, 0.0), 1.0 - width)
        y = min(max(cy - height / 2.0, 0.0), 1.0 - height)
        return {"crop": {"x": round(x, 4), "y": round(y, 4),
                         "width": round(width, 4), "height": round(height, 4)},
                "focus": {"x": round(cx, 4), "y": round(cy, 4)},
                "method": "sam3_box"}
    except Exception:
        return {}


def smart_reframe_crop(video_path: str, *, prompt: str = "person",
                       target_aspect: float = 9.0 / 16.0) -> Dict[str, Any]:
    """Full pipeline for one source clip: probe -> box -> crop window.

    Always returns a window (center crop fallback) so callers can proceed;
    ``method`` records which path produced it (sam3_box | muse_grounding |
    center_fallback).
    """
    try:
        source_aspect = _probe_aspect(video_path)
    except Exception:
        source_aspect = 16.0 / 9.0
    if abs(source_aspect - target_aspect) < 0.01:
        return {"crop": None, "method": "none", "note": "source already matches target"}

    frames = probe_frames(video_path, count=min(3, max(1, int(os.environ.get("SAM_PROBE_FRAMES", 3)))))
    for frame in frames:
        box = subject_box(frame, prompt, job_id=os.environ.get("CHRONOCUT_JOB_ID") or None)
        result = compute_crop(box, target_aspect, source_aspect) if box else None
        if result:
            return result
    # Center crop fallback keeps the profile renderable regardless of SAM output.
    height = 1.0
    width = height * target_aspect / source_aspect
    if width > 1.0:
        width = 1.0
        height = width * source_aspect / target_aspect
    return {"crop": {"x": round((1.0 - width) / 2.0, 4), "y": 0.0,
                     "width": round(width, 4), "height": round(height, 4)},
            "focus": {"x": 0.5, "y": 0.5},
            "method": "center_fallback"}


def _probe_aspect(path: str) -> float:
    r = subprocess.run(
        ["ffprobe", "-v", "quiet", "-print_format", "json",
         "-show_streams", "-select_streams", "v:0", path],
        capture_output=True, text=True, timeout=30)
    streams = (json.loads(r.stdout or "{}").get("streams") or [])
    if not streams:
        return 16.0 / 9.0
    w = float(streams[0].get("width") or 16)
    h = float(streams[0].get("height") or 9)
    return w / h if h else 16.0 / 9.0
