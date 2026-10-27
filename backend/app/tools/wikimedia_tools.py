import os
import logging
from typing import Dict, Any, List, Optional

import requests

logger = logging.getLogger("chronocut.tools.wikimedia")

WIKIMEDIA_API_BASE = "https://commons.wikimedia.org/w/api.php"


def search_images(query: str, limit: int = 10) -> List[Dict[str, Any]]:
    params = {
        "action": "query",
        "format": "json",
        "uselang": "en",
        "titles": query,
        "prop": "imageinfo",
        "iiprop": "url|extmetadata",
        "iiurlwidth": "1280",
        "generator": "search",
        "gsrsearch": f"filetype:bitmap {query}",
        "gsrlimit": min(limit, 50),
        "gsroffset": 0,
    }

    try:
        resp = requests.get(WIKIMEDIA_API_BASE, params=params, timeout=20)
        resp.raise_for_status()
        data = resp.json()
        pages = data.get("query", {}).get("pages", {})

        results = []
        for page_id, page in pages.items():
            if "imageinfo" not in page:
                continue
            info = page["imageinfo"][0]
            results.append({
                "id": page.get("pageid", page_id),
                "url": info.get("thumburl", info.get("url", "")),
                "full_url": info.get("url", ""),
                "source": "wikimedia",
                "license": _extract_license(info),
            })
        return results
    except Exception as e:
        logger.error(f"Wikimedia search failed: {e}")
        return []


def _extract_license(info: Dict[str, Any]) -> str:
    ext = info.get("extmetadata", {})
    license_el = ext.get("License", {})
    if license_el:
        return license_el.get("value", "unknown")
    return "unknown"


def get_image_url(file_title: str, width: int = 1280) -> Optional[str]:
    params = {
        "action": "query",
        "format": "json",
        "titles": file_title,
        "prop": "imageinfo",
        "iiprop": "url",
        "iiurlwidth": str(width),
    }

    try:
        resp = requests.get(WIKIMEDIA_API_BASE, params=params, timeout=15)
        resp.raise_for_status()
        data = resp.json()
        pages = data.get("query", {}).get("pages", {})
        for page in pages.values():
            if "imageinfo" in page:
                return page["imageinfo"][0].get("thumburl") or page["imageinfo"][0].get("url")
    except Exception as e:
        logger.error(f"Wikimedia image URL fetch failed: {e}")
    return None
