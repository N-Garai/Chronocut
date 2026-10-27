import logging

logger = logging.getLogger("chronocut.tools.footage.archive_org")

_ADVANCEDSEARCH = "https://archive.org/advancedsearch.php"
_METADATA = "https://archive.org/metadata"


def search_archive_org(query: str, limit: int = 3) -> list[dict]:
    params = {
        "q": f"{query} AND mediatype:(movies)",
        "fl[]": "identifier",
        "fl[]": "title",
        "rows": min(limit + 5, 50),
        "page": 1,
        "output": "json",
    }

    try:
        import requests
        resp = requests.get(_ADVANCEDSEARCH, params=params, timeout=20)
        resp.raise_for_status()
        data = resp.json()
        docs = data.get("response", {}).get("docs", [])
    except Exception as e:
        logger.error(f"search_archive_org advancedsearch failed: {e}")
        return []

    results = []
    for doc in docs:
        identifier = doc.get("identifier")
        if not identifier:
            continue
        try:
            import requests
            mresp = requests.get(f"{_METADATA}/{identifier}", timeout=20)
            mresp.raise_for_status()
            files = mresp.json().get("files", [])
            playable = None
            for f in files:
                name = f.get("name", "")
                if name.lower().endswith((".mp4", ".webm")):
                    playable = f"{_METADATA}/{identifier}/{name}"
                    break
            if not playable:
                continue
            results.append({
                "url": playable,
                "thumb": None,
                "source": "archive_org",
                "identifier": identifier,
            })
            if len(results) >= limit:
                break
        except Exception as e:
            logger.warning(f"search_archive_org metadata failed for {identifier}: {e}")
            continue
    return results
