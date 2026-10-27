import logging
import os
import tempfile

logger = logging.getLogger("chronocut.tools.footage.download_asset")

_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)


def download_asset(url: str, dest_dir: str, sha: str = None, job_id: str = None) -> str | None:
    from app.config import settings
    from app.services.firestore_service import JobStateService, sha256_text

    if not url:
        return None

    try:
        os.makedirs(dest_dir, exist_ok=True)
    except Exception as e:
        logger.error(f"download_asset: cannot create dest dir {dest_dir}: {e}")
        return None

    asset_sha = sha or sha256_text(url)

    # Dedup via asset cache.
    try:
        cached = JobStateService.asset_cache_get(asset_sha)
        if cached and cached.get("local_path") and os.path.exists(cached["local_path"]):
            logger.info(f"download_asset: cache hit for {url}")
            return cached["local_path"]
    except Exception as e:
        logger.warning(f"download_asset: cache lookup failed: {e}")

    import requests

    ext = os.path.splitext(url.split("?")[0].split("#")[0])[1] or ".bin"
    dest_path = os.path.join(dest_dir, f"{asset_sha}{ext}")

    try:
        headers = {"User-Agent": _USER_AGENT}
        with requests.get(url, headers=headers, timeout=30, stream=True) as resp:
            resp.raise_for_status()
            with open(dest_path, "wb") as f:
                for chunk in resp.iter_content(chunk_size=8192):
                    if chunk:
                        f.write(chunk)
        if not os.path.exists(dest_path) or os.path.getsize(dest_path) == 0:
            logger.error(f"download_asset: empty download for {url}")
            return None
        try:
            JobStateService.asset_cache_put(asset_sha, {"local_path": dest_path, "url": url})
        except Exception as e:
            logger.warning(f"download_asset: cache put failed: {e}")
        return dest_path
    except Exception as e:
        logger.error(f"download_asset: failed to download {url}: {e}")
        try:
            if os.path.exists(dest_path):
                os.remove(dest_path)
        except Exception:
            pass
        return None
