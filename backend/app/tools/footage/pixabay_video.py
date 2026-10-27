import logging

logger = logging.getLogger("chronocut.tools.footage.pixabay_video")


def search_pixabay_videos(query: str, per_page: int = 3) -> list[dict]:
    from app.config import settings

    api_key = settings.PIXABAY_API_KEY
    if not api_key:
        logger.info("search_pixabay_videos: no PIXABAY_API_KEY configured; returning []")
        return []

    params = {
        "key": api_key,
        "q": query,
        "per_page": min(per_page, 200),
        "page": 1,
        "video_type": "all",
    }

    try:
        import requests
        resp = requests.get("https://pixabay.com/api/videos/", params=params, timeout=15)
        resp.raise_for_status()
        data = resp.json()
        results = []
        for hit in data.get("hits", []):
            vfiles = hit.get("videos") or {}
            # Prefer the largest available rendition.
            pick = vfiles.get("large") or vfiles.get("medium") or vfiles.get("small") or vfiles.get("tiny")
            if not pick or not pick.get("url"):
                continue
            url = pick["url"]
            results.append({
                "url": url,
                "thumb": url,
                "source": "pixabay",
            })
        return results
    except Exception as e:
        logger.error(f"search_pixabay_videos failed: {e}")
        return []
