import os
import logging
from typing import Dict, Any, List, Optional

import requests

logger = logging.getLogger("chronocut.tools.pexels")

PEXELS_API_BASE = "https://api.pexels.com/v1"
PEXELS_VIDEO_BASE = "https://api.pexels.com/videos"

_request_count = 0
_MAX_REQUESTS = 180  # Stay under 200/hour


def _get_headers() -> Dict[str, str]:
    api_key = os.getenv("PEXELS_API_KEY")
    if not api_key:
        raise RuntimeError("PEXELS_API_KEY not configured")
    return {"Authorization": api_key}


def search_photos(query: str, orientation: str = "horizontal", per_page: int = 5) -> List[Dict[str, Any]]:
    global _request_count
    if _request_count >= _MAX_REQUESTS:
        logger.warning("Pexels rate limit threshold reached")
        return []

    headers = _get_headers()
    params = {
        "query": query,
        "orientation": orientation,
        "per_page": min(per_page, 80),
        "page": 1,
    }

    try:
        resp = requests.get(f"{PEXELS_API_BASE}/search", headers=headers, params=params, timeout=15)
        _request_count += 1
        resp.raise_for_status()
        data = resp.json()
        return [
            {
                "id": photo["id"],
                "url": photo["src"]["original"],
                "thumb": photo["src"]["medium"],
                "photographer": photo["photographer"],
                "source": "pexels",
            }
            for photo in data.get("photos", [])
        ]
    except Exception as e:
        logger.error(f"Pexels photo search failed: {e}")
        return []


def search_videos(query: str, orientation: str = "horizontal", per_page: int = 5) -> List[Dict[str, Any]]:
    global _request_count
    if _request_count >= _MAX_REQUESTS:
        logger.warning("Pexels rate limit threshold reached")
        return []

    headers = _get_headers()
    params = {
        "query": query,
        "orientation": orientation,
        "per_page": min(per_page, 80),
        "page": 1,
    }

    try:
        resp = requests.get(f"{PEXELS_VIDEO_BASE}/search", headers=headers, params=params, timeout=15)
        _request_count += 1
        resp.raise_for_status()
        data = resp.json()
        return [
            {
                "id": video["id"],
                "url": video["video_files"][0]["link"] if video.get("video_files") else "",
                "thumb": video["image"],
                "duration": video.get("duration", 0),
                "source": "pexels",
            }
            for video in data.get("videos", [])
        ]
    except Exception as e:
        logger.error(f"Pexels video search failed: {e}")
        return []


def reset_request_count():
    global _request_count
    _request_count = 0
