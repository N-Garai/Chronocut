import logging
import os

logger = logging.getLogger("chronocut.tools.reference")


def fetch(url: str, dest_dir: str) -> str | None:
    """Download a reference video to dest_dir and return the local path.

    Returns None on any failure (missing dependency or network error).
    """
    try:
        import yt_dlp  # lazy import
    except ImportError:
        logger.warning("yt-dlp not installed; reference fetch unavailable")
        return None

    try:
        os.makedirs(dest_dir, exist_ok=True)
        out_template = os.path.join(dest_dir, "%(id)s.%(ext)s")
        ydl_opts = {
            "outtmpl": out_template,
            "format": "bestvideo[ext=mp4]+bestaudio[ext=m4a]/bestvideo[ext=webm]+bestaudio[ext=webm]/best[ext=mp4]/best[ext=webm]/best",
            "merge_output_format": "mp4",
            "quiet": True,
            "no_warnings": True,
        }
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)
            if info is None:
                return None
            downloaded = ydl.prepare_filename(info)
            # yt-dlp may have merged into a different container.
            if os.path.exists(downloaded):
                return downloaded
            # Fall back: search for a file with the same id stem.
            base = os.path.splitext(downloaded)[0]
            for cand in (base + ".mp4", base + ".webm", base + ".mkv"):
                if os.path.exists(cand):
                    return cand
            return None
    except Exception as e:
        logger.warning(f"fetch failed for {url}: {e}")
        return None
