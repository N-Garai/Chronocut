import logging
import subprocess
import json
from typing import Dict, Any, Optional

logger = logging.getLogger("chronocut.tools.review")

__all__ = ["ffprobe_check"]


def ffprobe_check(video_path: str) -> Dict[str, Any]:
    try:
        out = subprocess.run(
            ["ffprobe", "-v", "quiet", "-print_format", "json",
             "-show_format", "-show_streams", video_path],
            capture_output=True, text=True, timeout=30,
        )
        data = json.loads(out.stdout) or {}
        streams = data.get("streams", []) or []
        video_stream = next((s for s in streams if s.get("codec_type") == "video"), None)
        audio_stream = next((s for s in streams if s.get("codec_type") == "audio"), None)
        fmt = data.get("format", {}) or {}
        duration = float(fmt.get("duration", 0) or 0)
        codec = video_stream.get("codec_name") if video_stream else None
        return {
            "duration": duration,
            "codec": codec,
            "width": video_stream.get("width"),
            "height": video_stream.get("height"),
            "has_audio": audio_stream is not None,
            "ok": (duration >= 2.0) and (codec in ("h264", "hevc", "vp9", None)),
        }
    except Exception as e:
        logger.error(f"ffprobe_check failed: {e}")
        return {"duration": 0, "codec": None, "has_audio": False, "ok": False, "error": str(e)}
