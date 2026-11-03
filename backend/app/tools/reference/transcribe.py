import logging
import os
import subprocess
import tempfile

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


def _extract_audio(video_path: str, audio_path: str) -> bool:
    try:
        subprocess.run(
            [
                "ffmpeg", "-y", "-i", video_path,
                "-vn", "-ac", "1", "-ar", "16000",
                "-acodec", "pcm_s16le", audio_path,
            ],
            capture_output=True, text=True, timeout=600,
        )
        return os.path.exists(audio_path)
    except Exception as e:
        logger.warning(f"audio extraction failed: {e}")
        return False


def transcribe(audio_path: str, language: str = "en") -> dict:
    """Transcribe audio to text + segments via Meta ASR.

    Returns a dict with keys: full_text, segments, language, duration_seconds.
    Degrades to an empty transcript when the Meta ASR path is unavailable.
    """
    result: dict = {"full_text": "", "segments": [], "language": language, "duration_seconds": 0.0}

    try:
        result["duration_seconds"] = _probe_duration_seconds(audio_path)
    except Exception:
        pass

    try:
        import asyncio as _aio

        from app.tools.audio.transcribe import provider_audio_transcribe  # lazy import

        g = _aio.run(provider_audio_transcribe(audio_path, language=language))
        if g and isinstance(g, dict):
            result["full_text"] = g.get("full_text", "") or ""
            result["segments"] = g.get("segments", []) or []
            result["language"] = g.get("language", language)
            if not result["duration_seconds"]:
                result["duration_seconds"] = float(g.get("duration_seconds", 0.0) or 0.0)
            return result
    except ImportError:
        logger.info("provider_audio_transcribe not available")
    except Exception as e:
        logger.warning(f"provider transcription failed: {e}")

    return result
