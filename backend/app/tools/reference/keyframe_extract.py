import logging
import os
import subprocess

logger = logging.getLogger("chronocut.tools.reference")


def _probe_duration_seconds(path: str) -> float:
    try:
        out = subprocess.run(
            [
                "ffprobe", "-v", "error",
                "-show_entries", "format=duration",
                "-of", "default=noprint_wrappers=1:nokey=1",
                path,
            ],
            capture_output=True, text=True, timeout=60,
        )
        return float(out.stdout.strip() or 0.0)
    except Exception:
        return 0.0


def extract_keyframes(video_path: str, n: int = 8) -> list[str]:
    """Extract n evenly-spaced keyframe JPEGs.

    Returns a list of local jpg paths (may be empty on failure).
    """
    out: list[str] = []
    try:
        duration = _probe_duration_seconds(video_path)
        if not duration or duration <= 0:
            logger.warning("could not determine duration for keyframe extraction")
            return out

        dest_dir = os.path.dirname(os.path.abspath(video_path))
        step = duration / (n + 1)
        for i in range(1, n + 1):
            ts = step * i
            out_path = os.path.join(dest_dir, f"keyframe_{i:02d}.jpg")
            subprocess.run(
                [
                    "ffmpeg", "-y", "-ss", f"{ts:.3f}", "-i", video_path,
                    "-frames:v", "1", "-q:v", "3", out_path,
                ],
                capture_output=True, text=True, timeout=120,
            )
            if os.path.exists(out_path):
                out.append(out_path)
            else:
                logger.warning(f"keyframe extraction failed at {ts:.2f}s")
    except Exception as e:
        logger.warning(f"extract_keyframes failed: {e}")
    return out
