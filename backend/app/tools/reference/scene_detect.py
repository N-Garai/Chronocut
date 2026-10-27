import logging
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


def detect_scenes(video_path: str, threshold: float = 27.0) -> list[float]:
    """Return scene boundary timestamps (seconds).

    Uses PySceneDetect when available; on any failure, falls back to a
    fixed 5-second interval split up to the video duration. Never raises.
    """
    duration = _probe_duration_seconds(video_path)

    try:
        from scenedetect import detect, ContentDetector  # lazy import
        from scenedetect.video_splitter import split_video_ffmpeg  # noqa: F401 (kept for parity)

        scenes = detect(video_path, ContentDetector(threshold=threshold))
        boundaries = [float(s[0].get_seconds()) for s in scenes if s and len(s) >= 1]
        # first boundary is the start (0.0); keep meaningful cuts.
        boundaries = [b for b in boundaries if b > 0.0]
        if boundaries:
            return boundaries
    except ImportError:
        logger.info("pyscenedetect not installed; using interval fallback")
    except Exception as e:
        logger.warning(f"scene detection failed: {e}; using interval fallback")

    # --- Interval fallback -------------------------------------------------
    if duration and duration > 0:
        return [t for t in range(5, int(duration), 5)]
    return []
