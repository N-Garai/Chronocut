"""Silence detection for the remove_silence macro.

Uses ffmpeg's silencedetect filter (no extra dependencies). Returns qualifying
ranges in project seconds with a minimum duration and a dB threshold so the
op engine can cut them with a global ripple.
"""
import json
import logging
import re
import subprocess
from typing import Any, Dict, List

logger = logging.getLogger("chronocut.tools.audio.silence")

__all__ = ["detect_silence", "analyze_job_audio", "job_audio_paths",
           "cached_job_audio", "audio_silence_context"]


def detect_silence(audio_path: str, *, noise_db: float = -35.0,
                   min_silence: float = 0.4, duration: float = 0.0) -> Dict[str, Any]:
    """Return {"silence_ranges": [(start, end), ...], "duration": seconds}.

    Falls back to an empty report when ffmpeg/ffprobe are unavailable so the
    operation degrades gracefully (remove_silence then raises a clean 422).
    """
    ranges: List[List[float]] = []
    real_duration = float(duration or 0.0)
    try:
        if real_duration <= 0:
            probe = subprocess.run(
                ["ffprobe", "-v", "quiet", "-print_format", "json", "-show_format", audio_path],
                capture_output=True, text=True, timeout=30)
            data = json.loads(probe.stdout or "{}")
            real_duration = float((data.get("format") or {}).get("duration") or 0.0)

        args = ["ffmpeg", "-hide_banner", "-nostats", "-i", audio_path,
                "-af", f"silencedetect=noise={noise_db}dB:d={min_silence}",
                "-f", "null", "-"]
        proc = subprocess.run(args, capture_output=True, text=True, timeout=300)
        text = proc.stderr or ""
        starts = [float(m.group(1)) for m in re.finditer(
            r"silence_start:\s*(-?\d+(?:\.\d+)?)", text)]
        ends = [float(m.group(1)) for m in re.finditer(
            r"silence_end:\s*(\d+(?:\.\d+)?)", text)]
        if len(ends) < len(starts):  # trailing silence at EOF; close at duration
            starts = starts[:len(ends)] if ends else []
        for s, e in zip(starts, ends):
            if e > s:
                ranges.append([max(0.0, s), e])
    except FileNotFoundError:
        logger.warning("silence detection skipped: ffmpeg not installed")
        return {"silence_ranges": [], "duration": real_duration}
    except Exception as e:
        logger.warning("silence detection failed for %s: %s", audio_path, e)
        return {"silence_ranges": [], "duration": real_duration}

    return {
        "silence_ranges": [{"start": round(s, 3), "end": round(e, 3)} for s, e in ranges],
        "duration": round(real_duration, 3),
    }


def analyze_job_audio(paths: List[str], *, noise_db: float = -35.0,
                      min_silence: float = 0.4) -> Dict[str, Any]:
    """Analyze the first available audio source for a job (host narration track)."""
    for p in paths or []:
        if p and __import__("os").path.exists(p):
            return detect_silence(p, noise_db=noise_db, min_silence=min_silence)
    return {"silence_ranges": [], "duration": 0.0}


# --------------------------------------------------------------------------
# job-level helpers (endpoint + remove_silence context)
# --------------------------------------------------------------------------
_CACHE: Dict[tuple, Dict[str, Any]] = {}
_CACHE_LIMIT = 64


def job_audio_paths(edl: Dict[str, Any]) -> List[str]:
    """Local audio source paths of an EDL (narration mp3s, uploaded music)."""
    out = []
    for s in (edl.get("sources") or []):
        if not isinstance(s, dict):
            continue
        if str(s.get("type") or "") == "audio" and s.get("path"):
            out.append(str(s["path"]))
    return out


def cached_job_audio(job_id: str, revision: int, paths: List[str], *,
                     noise_db: float = -35.0, min_silence: float = 0.4) -> Dict[str, Any]:
    """Revision-keyed silence report cache (tmp audio is immutable per revision).

    After any cut the stored EDL revision increments, so the next call with the
    new revision recomputes instead of serving stale ranges.
    """
    key = (str(job_id), int(revision), round(float(noise_db), 1), round(float(min_silence), 2))
    hit = _CACHE.get(key)
    if hit is not None:
        return hit
    report = analyze_job_audio(paths, noise_db=noise_db, min_silence=min_silence)
    if len(_CACHE) >= _CACHE_LIMIT:
        _CACHE.clear()
    _CACHE[key] = report
    return report


def audio_silence_context(edl: Dict[str, Any], *, revision: int = 0,
                          job_id: str = "", noise_db: float = -35.0,
                          min_silence: float = 0.4) -> Dict[str, Any]:
    """Build the ``remove_silence`` macro context for an EDL, degrading to an
    empty range list so the op raises a clean validation error when ffmpeg or
    the narration files are unavailable. ``revision`` keys the cache (it
    increments after every save, invalidating stale ranges)."""
    paths = job_audio_paths(edl)
    if not paths or not job_id:
        return {"silence_ranges": []}
    report = cached_job_audio(str(job_id), int(revision), paths,
                              noise_db=noise_db, min_silence=min_silence)
    return {"silence_ranges": report.get("silence_ranges") or []}

