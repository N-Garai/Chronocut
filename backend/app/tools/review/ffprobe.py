import logging
import os
import re
import subprocess
import json
from typing import Dict, Any, Optional

logger = logging.getLogger("chronocut.tools.review")

__all__ = ["ffprobe_check"]


def _ffmpeg_probe_fallback(video_path: str) -> Optional[Dict[str, Any]]:
    """Derive duration/codec from `ffmpeg -i` when the ffprobe binary is not on
    PATH (e.g. minimal local installs that only ship the ffmpeg binary)."""
    try:
        out = subprocess.run(
            ["ffmpeg", "-hide_banner", "-i", video_path, "-f", "null", "-"],
            capture_output=True, text=True, timeout=60,
        )
        err = out.stderr or ""
        m = re.search(r"Duration:\s*(\d+):(\d+):(\d+\.?\d*)", err)
        if not m:
            return None
        duration = int(m.group(1)) * 3600 + int(m.group(2)) * 60 + float(m.group(3))
        codec = None
        width = height = None
        sm = re.search(r"Stream #\d+:\d+.*?: Video:\s*(\w+)", err)
        if sm:
            codec = sm.group(1)
            dm = re.search(r",\s*(\d{2,5})x(\d{2,5})[, ]", err[sm.start():sm.start() + 300])
            if dm:
                width, height = int(dm.group(1)), int(dm.group(2))
        has_audio = bool(re.search(r"Stream #\d+:\d+.*?: Audio:", err))
        return {
            "duration": duration,
            "codec": codec,
            "width": width,
            "height": height,
            "has_audio": has_audio,
            "ok": (duration >= 2.0) and (codec in ("h264", "hevc", "vp9", None)),
        }
    except Exception as e:
        logger.warning(f"ffmpeg probe fallback failed: {e}")
        return None


def ffprobe_check(video_path: str) -> Dict[str, Any]:
    if not os.path.exists(video_path):
        return {"duration": 0, "codec": None, "has_audio": False, "ok": False,
                "error": f"file not found: {video_path}"}
    try:
        out = subprocess.run(
            ["ffprobe", "-v", "quiet", "-print_format", "json",
             "-show_format", "-show_streams", video_path],
            capture_output=True, text=True, timeout=30,
        )
        data = json.loads(out.stdout) if out.returncode == 0 and out.stdout.strip() else {}
        if not data:
            raise FileNotFoundError("ffprobe unavailable or returned no data")
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
    except FileNotFoundError as e:
        fallback = _ffmpeg_probe_fallback(video_path)
        if fallback:
            return fallback
        logger.error(f"ffprobe_check failed: {e}")
        return {"duration": 0, "codec": None, "has_audio": False, "ok": False, "error": str(e)}
    except Exception as e:
        logger.error(f"ffprobe_check failed: {e}")
        return {"duration": 0, "codec": None, "has_audio": False, "ok": False, "error": str(e)}
