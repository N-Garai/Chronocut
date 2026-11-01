import logging
import os
import tempfile
from urllib.parse import quote

logger = logging.getLogger("chronocut.tools.footage.resolver")


def _asset_dir() -> str:
    d = os.path.join(tempfile.gettempdir(), "chronocut_assets")
    try:
        os.makedirs(d, exist_ok=True)
    except Exception as e:
        logger.error(f"resolve_visual: cannot create asset dir: {e}")
    return d


def _matte(query: str) -> dict:
    """Final fallback: a generated dark cinematic gradient matte with query text."""
    d = _asset_dir()
    from app.services.firestore_service import sha256_text
    sha = sha256_text(query)[:16]
    out_path = os.path.join(d, f"matte_{sha}.png")
    try:
        from PIL import Image, ImageDraw, ImageFont
        w, h = 1920, 1080
        base = Image.new("RGB", (w, h), (0, 0, 0))
        px = base.load()
        for y in range(h):
            t = y / h
            r = int(8 + t * 24)
            g = int(10 + t * 30)
            b = int(18 + t * 48)
            for x in range(w):
                px[x, y] = (r, g, b)
        draw = ImageDraw.Draw(base)
        try:
            font = ImageFont.load_default()
        except Exception:
            font = None
        text = (query or "ChronoCut")[:120]
        if font is not None:
            try:
                bbox = draw.textbbox((0, 0), text, font=font)
                tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
                draw.text(((w - tw) / 2, (h - th) / 2), text, fill=(220, 220, 230), font=font)
            except Exception:
                draw.text((40, 40), text, fill=(220, 220, 230), font=font)
        base.save(out_path)
    except Exception as e:
        logger.error(f"resolve_visual: matte generation failed: {e}")
        out_path = None
    return {
        "type": "color_matte",
        "url": None,
        "file": out_path,
        "source": "generated",
        "effect": "none",
    }


def _cache(query: str, url: str, source: str, modality: str, fpath: str) -> None:
    try:
        from app.tools.footage.clip_search import store_footage
        store_footage(query, url, source, modality, fpath)
    except Exception as e:
        logger.warning(f"resolve_visual: corpus cache failed: {e}")


def _alternate_queries(query: str) -> list[str]:
    """Re-search phrasings — drop descriptive tone words, then try the raw
    noun phrase, then a generic fallback so we 'search properly when necessary'."""
    q = (query or "").strip()
    if not q:
        return []
    words = [w for w in q.split() if len(w) > 2]
    alts: list[str] = []
    if len(words) > 2:
        alts.append(" ".join(words[:3]))
    if len(words) > 1:
        alts.append(" ".join(words[:2]))
    alts.append(words[0] if words else q)
    # de-dup preserving order, keep distinct from the original
    seen = {q.lower()}
    out = []
    for a in alts:
        if a.lower() not in seen:
            seen.add(a.lower())
            out.append(a)
    return out


def _download_first(hits, asset_dir, job_id, effect="none", modality="video",
                    source_label="source", avoid_urls=None) -> dict | None:
    """Try each ranked hit (hits[0], then hits[1..]) and return the first
    that downloads successfully. Returns None if all fail.

    ``avoid_urls`` lets the caller skip clips already used by other shots so a
    single matched clip never repeats across the storyboard. Tries non-avoided
    hits first, then falls back to the full list if every hit was avoided (so a
    shot is never left without footage).
    """
    from app.tools.footage.download_asset import download_asset
    avoid = set(avoid_urls or set())
    preferred = [h for h in (hits or []) if h.get("url") and h["url"] not in avoid] or (hits or [])
    for hit in preferred:
        url = hit.get("url")
        if not url:
            continue
        try:
            f = download_asset(url, asset_dir, job_id=job_id)
        except Exception as e:
            logger.warning(f"resolve_visual: download failed for {url}: {e}")
            continue
        if f and os.path.exists(f):
            _cache(query := hit.get("_query", ""), url, hit.get("source", source_label), modality, f)
            return {
                "type": hit.get("type", source_label),
                "url": url,
                "file": f,
                "source": hit.get("source", source_label),
                "effect": hit.get("effect", effect),
            }
    return None


def resolve_visual(query: str, duration: float = 5.0, job_id: str = None, profile: str = "youtube_landscape", avoid_urls=None) -> dict:
    asset_dir = _asset_dir()

    # Tier0: semantic footage corpus — embedding similarity search.
    try:
        from app.config import settings
        if settings.ENABLE_FOOTAGE_CORPUS:
            from app.tools.footage.clip_search import corpus_search
            from app.tools.footage.download_asset import download_asset
            results = corpus_search(query, top_k=3)
            if results:
                f = download_asset(results[0]["url"], asset_dir, job_id=job_id)
                if f and os.path.exists(f):
                    _cache(query, results[0]["url"], "footage_corpus", "video", f)
                    return {
                        "type": "corpus",
                        "url": results[0]["url"],
                        "file": f,
                        "source": "footage_corpus",
                        "effect": "ken_burns_slow_zoom",
                    }
    except Exception as e:
        logger.warning(f"resolve_visual Tier0 (corpus) failed: {e}")

    # Tier1: Pexels videos (requires PEXELS_API_KEY). Try the primary
    # query then progressively simpler alternate queries, iterating hits.
    try:
        from app.tools.footage.pexels_video import search_pexels_videos
        for q in _alternate_queries(query) or [query]:
            hits = search_pexels_videos(q, per_page=5)
            if hits:
                for h in hits:
                    h["_query"] = q
                    h["type"] = "pexels_broll"
                    h["effect"] = "none"
                resolved = _download_first(hits, asset_dir, job_id, effect="none", modality="video", source_label="pexels", avoid_urls=avoid_urls)
                if resolved:
                    return resolved
    except Exception as e:
        logger.warning(f"resolve_visual Tier1 (pexels) failed: {e}")

    # Tier2: Pixabay videos (requires PIXABAY_API_KEY).
    try:
        from app.tools.footage.pixabay_video import search_pixabay_videos
        for q in _alternate_queries(query) or [query]:
            hits = search_pixabay_videos(q, per_page=5)
            if hits:
                for h in hits:
                    h["_query"] = q
                    h["type"] = "pixabay"
                    h["effect"] = "none"
                resolved = _download_first(hits, asset_dir, job_id, effect="none", modality="video", source_label="pixabay", avoid_urls=avoid_urls)
                if resolved:
                    return resolved
    except Exception as e:
        logger.warning(f"resolve_visual Tier2 (pixabay) failed: {e}")

    # Tier3: Wikimedia videos (+ archive_org / nasa as extra motion sources).
    try:
        from app.tools.footage.download_asset import download_asset
        for q in _alternate_queries(query) or [query]:
            from app.tools.footage.wikimedia_video import search_wikimedia_videos
            hits = search_wikimedia_videos(q, limit=5)
            if not hits:
                from app.tools.footage.archive_org import search_archive_org
                hits = search_archive_org(q, limit=5)
            if not hits:
                from app.tools.footage.nasa import search_nasa
                hits = search_nasa(q, limit=5)
            if hits:
                for h in hits:
                    h["_query"] = q
                resolved = _download_first(hits, asset_dir, job_id, effect="none", modality="video",
                                           source_label=hits[0].get("source", "wikimedia"), avoid_urls=avoid_urls)
                if resolved:
                    return resolved
    except Exception as e:
        logger.warning(f"resolve_visual Tier3 (wikimedia/archive/nasa) failed: {e}")

    # Tier3b: stock IMAGES (Pexels photos + Wikimedia images), combined with the
    # video tiers above this guarantees a rich pool -- when no stock VIDEO matches a
    # shot we still get a relevant still (rendered with ken_burns motion) instead of
    # dropping to a matte. Images are preferred over AI generation (Tier4).
    try:
        from app.tools.footage.download_asset import download_asset
        img_hits: list = []
        try:
            from app.tools.pexels_tools import search_photos
            for p in (search_photos(query, per_page=5) or []):
                if p.get("url"):
                    img_hits.append({"url": p["url"], "type": "pexels_image",
                                     "effect": "ken_burns_slow_zoom", "source": "pexels"})
        except Exception as e:
            logger.warning(f"resolve_visual Pexels images failed: {e}")
        try:
            from app.tools.wikimedia_tools import search_images as _wik_images
            for im in (_wik_images(query, limit=5) or []):
                if im.get("url"):
                    img_hits.append({"url": im["url"], "type": "wikimedia_image",
                                     "effect": "ken_burns_slow_zoom", "source": "wikimedia"})
        except Exception as e:
            logger.warning(f"resolve_visual Wikimedia images failed: {e}")
        if img_hits:
            for h in img_hits:
                h["_query"] = query
            resolved = _download_first(img_hits, asset_dir, job_id, effect="ken_burns_slow_zoom",
                                       modality="image", source_label="image", avoid_urls=avoid_urls)
            if resolved:
                return resolved
    except Exception as e:
        logger.warning(f"resolve_visual Tier3b (images) failed: {e}")

    # Tier5: generated color matte.
    logger.info(f"resolve_visual: all tiers exhausted for '{query}'; using matte fallback")
    return _matte(query)
