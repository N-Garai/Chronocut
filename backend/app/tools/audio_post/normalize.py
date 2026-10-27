import os
import logging
import subprocess
from typing import Optional

logger = logging.getLogger("chronocut.tools.audio_post")


def normalize(input_path: str, out_path: str, target_lufs: float = -18.0) -> bool:
    try:
        if not input_path or not os.path.exists(input_path):
            logger.error(f"normalize: missing input {input_path}")
            return False
        cmd = [
            "ffmpeg", "-y", "-i", input_path,
            "-af", f"loudnorm=I={target_lufs}:TP=-1.5:LRA=11",
            "-c:a", "aac", "-b:a", "192k", out_path,
        ]
        res = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
        return res.returncode == 0 and os.path.exists(out_path)
    except Exception as e:
        logger.error(f"normalize failed: {e}")
        return False
