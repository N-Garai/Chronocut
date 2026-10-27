import os
import logging
import subprocess
from typing import Optional

logger = logging.getLogger("chronocut.tools.audio_post")


def duck(music_path: str, voice_path: str, out_path: str) -> bool:
    """Duck music under voice. Uses sidechaincompress when both present;
    falls back to lowering music volume and mixing."""
    try:
        if not music_path or not os.path.exists(music_path):
            logger.error("duck: music missing")
            return False
        if not voice_path or not os.path.exists(voice_path):
            # Nothing to duck against: just normalize music quietly.
            from app.tools.audio_post.normalize import normalize
            return normalize(music_path, out_path)

        filter_complex = (
            "[1:a]asplit=2[sc][v];"
            "[0:a][sc]sidechaincompress=threshold=0.05:ratio=8:attack=20:release=200[comp];"
            "[comp][v]amix=inputs=2:duration=longest:normalize=0[out]"
        )
        cmd = [
            "ffmpeg", "-y", "-i", music_path, "-i", voice_path,
            "-filter_complex", filter_complex,
            "-map", "[out]", "-c:a", "aac", "-b:a", "192k", out_path,
        ]
        res = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
        if res.returncode == 0 and os.path.exists(out_path):
            return True

        # Fallback: lower music and mix with voice.
        logger.warning("duck: sidechain failed, using volume fallback")
        fb = (
            "[0:a]volume=0.25[mm];"
            "[mm][1:a]amix=inputs=2:duration=longest:normalize=0[out]"
        )
        cmd2 = [
            "ffmpeg", "-y", "-i", music_path, "-i", voice_path,
            "-filter_complex", fb,
            "-map", "[out]", "-c:a", "aac", "-b:a", "192k", out_path,
        ]
        res2 = subprocess.run(cmd2, capture_output=True, text=True, timeout=300)
        return res2.returncode == 0 and os.path.exists(out_path)
    except Exception as e:
        logger.error(f"duck failed: {e}")
        return False
