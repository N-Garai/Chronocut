import logging

logger = logging.getLogger("chronocut.tools.footage.wikimedia_video")

WIKIMEDIA_API_BASE = "https://commons.wikimedia.org/w/api.php"

_VIDEO_EXTS = (".webm", ".ogv", ".mp4", ".mkv", ".mov", ".avi")


def search_wikimedia_videos(query: str, limit: int = 3) -> list[dict]:
    params = {
        "action": "query",
        "format": "json",
        "prop": "imageinfo",
        "iiprop": "url|mime",
        "generator": "search",
        "gsrsearch": f"filetype:video {query}",
        "gsrlimit": min(limit + 5, 50),
        "gsroffset": 0,
    }

    try:
        import requests
        resp = requests.get(WIKIMEDIA_API_BASE, params=params, timeout=20)
        resp.raise_for_status()
        data = resp.json()
        pages = data.get("query", {}).get("pages", {})

        results = []
        for page in pages.values():
            info_list = page.get("imageinfo")
            if not info_list:
                continue
            info = info_list[0]
            url = info.get("url", "")
            mime = info.get("mime", "")
            if not url:
                continue
            if mime and "video" not in mime and not url.lower().endswith(_VIDEO_EXTS):
                continue
            results.append({
                "url": url,
                "thumb": url,
                "source": "wikimedia",
            })
            if len(results) >= limit:
                break
        return results
    except Exception as e:
        logger.error(f"search_wikimedia_videos failed: {e}")
        return []
