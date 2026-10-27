import os
import logging
import subprocess
from typing import Optional

logger = logging.getLogger("chronocut.tools.audio_post")


def music_mixer(
    narration_path: str,
    music_path: str,
    out_path: str,
    music_gain: float = 0.25,
) -> bool:
    """Mix full narration with low-gain music, then normalize."""
    try:
        if not narration_path or not os.path.exists(narration_path):
            logger.error("music_mixer: narration missing")
            return False
        if not music_path or not os.path.exists(music_path):
            # No music: just normalize narration.
            from app.tools.audio_post.normalize import normalize
            return normalize(narration_path, out_path)

        filter_complex = (
            f"[1:a]volume={music_gain}[m];"
            "[0:a][m]amix=inputs=2:duration=longest:normalize=0[pre];"
            "[pre]loudnorm=I=-18:TP=-1.5:LRA=11[out]"
        )
        cmd = [
            "ffmpeg", "-y", "-i", narration_path, "-i", music_path,
            "-filter_complex", filter_complex,
            "-map", "[out]", "-c:a", "aac", "-b:a", "192k", out_path,
        ]
        res = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
        return res.returncode == 0 and os.path.exists(out_path)
    except Exception as e:
        logger.error(f"music_mixer failed: {e}")
        return False
