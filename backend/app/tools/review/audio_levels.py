import logging
import subprocess
import json
from typing import Dict, Any

logger = logging.getLogger("chronocut.tools.review")

__all__ = ["audio_levels"]


def audio_levels(video_path: str) -> Dict[str, Any]:
    try:
        out = subprocess.run(
            ["ffmpeg", "-i", video_path, "-af", "astats=metadata=1:reset=0",
             "-f", "null", "-"],
            capture_output=True, text=True, timeout=30,
        )
        log = out.stderr
        peak = None
        rms = None
        for line in log.splitlines():
            if "Peak level dB:" in line:
                try:
                    peak = float(line.split(":")[1].strip())
                except Exception:
                    pass
            if "RMS level dB:" in line:
                try:
                    rms = float(line.split(":")[1].strip())
                except Exception:
                    pass
        if peak is None and rms is None:
            # Likely no audio track
            return {"has_audio": False, "peak_db": None, "rms_db": None, "ok": True}
        ok = (peak is None) or (-60.0 <= peak <= -0.5)
        return {"has_audio": True, "peak_db": peak, "rms_db": rms, "ok": ok}
    except Exception as e:
        logger.error(f"audio_levels failed: {e}")
        return {"has_audio": False, "ok": True}
