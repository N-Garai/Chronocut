import logging

logger = logging.getLogger("chronocut.tools.footage.nasa")

NASA_IMAGES_API = "https://images-api.nasa.gov/search"


def search_nasa(query: str, limit: int = 3) -> list[dict]:
    params = {"q": query, "media_type": "video,image"}

    try:
        import requests
        resp = requests.get(NASA_IMAGES_API, params=params, timeout=20)
        resp.raise_for_status()
        data = resp.json()
        items = data.get("collection", {}).get("items", [])
    except Exception as e:
        logger.error(f"search_nasa failed: {e}")
        return []

    results = []
    manifest_failures = 0
    for item in items:
        if len(results) >= limit:
            break
        meta = item.get("data", [{}])[0] if item.get("data") else {}
        links = item.get("links", [])
        if not links:
            continue
        manifest_url = links[0].get("href")
        if not manifest_url:
            continue
        # Fail fast: when the manifest endpoint is failing wholesale (empty
        # bodies, blocked network) each retry costs the pipeline up to 20s per
        # item. Two consecutive failures means the source is down for this
        # query — bail out and let the resolver cascade try other sources.
        if manifest_failures >= 2:
            logger.warning("search_nasa manifest endpoint failing repeatedly; skipping remaining items")
            break
        # Default thumbnail = the manifest link itself.
        thumb = meta.get("thumbnail") or manifest_url
        try:
            import requests
            mresp = requests.get(manifest_url, timeout=10)
            mresp.raise_for_status()
            # The link is a JSON manifest of asset URLs.
            assets = mresp.json()
            if not isinstance(assets, list):
                assets = [assets]
            chosen = None
            for a in assets:
                if a.lower().endswith(".mp4"):
                    chosen = a
                    break
            if not chosen:
                for a in assets:
                    if a.lower().endswith((".jpg", ".png", ".jpeg")):
                        chosen = a
                        break
            if not chosen and assets:
                chosen = assets[0]
            if not chosen:
                continue
            results.append({
                "url": chosen,
                "thumb": thumb,
                "source": "nasa",
            })
        except Exception as e:
            manifest_failures += 1
            logger.warning(f"search_nasa asset manifest failed: {e}")
            continue
    return results
