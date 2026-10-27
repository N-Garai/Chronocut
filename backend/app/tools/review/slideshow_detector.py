import logging
import os
import subprocess
import tempfile
from typing import Dict, Any

logger = logging.getLogger("chronocut.tools.review")

__all__ = ["slideshow_detector"]


def slideshow_detector(video_path: str, n: int = 10) -> Dict[str, Any]:
    """Detect if the video is a static slideshow (consecutive frames near-identical)."""
    try:
        from app.tools.review.ffprobe import ffprobe_check
        meta = ffprobe_check(video_path)
        duration = meta.get("duration", 0)
        if duration <= 0:
            return {"identical_ratio": 0.0, "ok": True}
        tmp = tempfile.mkdtemp(prefix="chronocut_slide_")
        frames = []
        for i in range(n):
            ts = duration * i / n
            fp = os.path.join(tmp, f"s{i:02d}.jpg")
            subprocess.run(["ffmpeg", "-y", "-ss", str(ts), "-i", video_path,
                            "-vframes", "1", "-q:v", "4", fp],
                           capture_output=True, text=True, timeout=20)
            if os.path.exists(fp):
                frames.append(fp)
        if len(frames) < 2:
            return {"identical_ratio": 0.0, "ok": True}
        identical = 0
        for a, b in zip(frames, frames[1:]):
            try:
                from PIL import Image, ImageChops
                import numpy as np
                ia = np.asarray(Image.open(a).convert("L")).astype("int")
                ib = np.asarray(Image.open(b).convert("L")).astype("int")
                diff = np.abs(ia - ib).mean()
                if diff < 5:
                    identical += 1
            except Exception:
                pass
        ratio = identical / (len(frames) - 1)
        return {"identical_ratio": round(ratio, 2), "ok": ratio <= 0.8}
    except Exception as e:
        logger.error(f"slideshow_detector failed: {e}")
        return {"identical_ratio": 0.0, "ok": True}
