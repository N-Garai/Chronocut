import logging
import os
import time
import threading

try:
    from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type, RetryError
except ImportError:  # tenacity is already a dependency, but guard anyway
    retry = None

logger = logging.getLogger("chronocut.tools.footage.pexels_video")

PEXELS_VIDEO_BASE = "https://api.pexels.com/videos"

# C5: auto-resetting per-hour quota guard (replaces an unused static counter).
_lock = threading.Lock()
_request_times: list[float] = []


def _admit_request(max_per_hour: int) -> bool:
    now = time.time()
    with _lock:
        global _request_times
        _request_times = [t for t in _request_times if now - t < 3600]
        if len(_request_times) >= max_per_hour:
            return False
        _request_times.append(now)
    return True


def _quality_rank(video: dict) -> float:
    """C2: prefer higher resolution / 'hd'/'uhd' quality and longer clips."""
    best = 0
    dur = float(video.get("duration", 0) or 0)
    for f in (video.get("video_files") or []):
        w = int(f.get("width") or 0)
        # weight resolution heavily, with a small bonus for longer usable clips
        score = w + (10 if f.get("quality") in ("hd", "uhd") else 0)
        best = max(best, score)
    return best + min(dur, 30) * 0.5


def _fetch(query: str, per_page: int, api_key: str) -> list:
    import requests
    headers = {"Authorization": api_key}
    params = {"query": query, "per_page": min(per_page, 80), "page": 1}
    resp = requests.get(f"{PEXELS_VIDEO_BASE}/search", headers=headers, params=params, timeout=15)
    if resp.status_code in (401, 403):
        raise PermissionError(f"Pexels auth failed ({resp.status_code})")
    if resp.status_code == 429:
        retry_after = resp.headers.get("Retry-After")
        msg = f"Pexels 429 rate limited"
        if retry_after:
            msg += f"; Retry-After={retry_after}"
        raise RuntimeError(msg)
    resp.raise_for_status()
    return resp.json().get("videos", [])


def search_pexels_videos(query: str, per_page: int = 3) -> list[dict]:
    from app.config import settings

    api_key = settings.PEXELS_API_KEY
    if not api_key:
        logger.info("search_pexels_videos: no PEXELS_API_KEY configured; returning []")
        return []

    max_per_hour = settings.PEXELS_MAX_REQUESTS_PER_HOUR
    if not _admit_request(max_per_hour):
        logger.warning("search_pexels_videos: per-hour quota guard tripped; skipping")
        return []

    # C5: tenacity exponential backoff on transient/quota errors (honors Retry-After
    # via the caller's sleep is implicit; we retry a bounded number of times).
    call = _fetch
    if retry is not None:
        def _backoff(exc):
            return isinstance(exc, Exception) and (
                "429" in str(exc) or "rate" in str(exc).lower() or "timeout" in str(exc).lower()
            )
        call = retry(
            stop=stop_after_attempt(3),
            wait=wait_exponential(multiplier=2, min=2, max=30),
            retry=retry_if_exception_type(Exception),
            reraise=True,
        )(_fetch)

    try:
        videos = call(query, per_page, api_key)
    except Exception as e:  # noqa: BLE001
        logger.error(f"search_pexels_videos failed: {e}")
        return []

    results = []
    for video in videos:
        files = video.get("video_files") or []
        if not files:
            continue
        # C2: rank video_files by quality and pick the best link.
        best_file = max(files, key=lambda f: int(f.get("width") or 0)
                        + (10 if f.get("quality") in ("hd", "uhd") else 0))
        link = best_file.get("link")
        if not link:
            continue
        results.append({
            "url": link,
            "thumb": video.get("image", ""),
            "source": "pexels",
            "duration": float(video.get("duration", 0) or 0),
            "width": int(best_file.get("width") or 0),
            "quality": best_file.get("quality", ""),
            "rank": _quality_rank(video),
        })
    # Sort so the highest-quality clip is first.
    results.sort(key=lambda r: r.get("rank", 0), reverse=True)
    return results
