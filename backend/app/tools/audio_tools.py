import os
import base64
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger("chronocut.tools.audio")


def transcribe_audio(file_path: str, language: str = "en") -> Dict[str, Any]:
    """Transcribe an audio file using the multimodal model. Returns time-coded segments."""
    try:
        import google.generativeai as genai
    except ImportError:
        return {"error": "google-generativeai not installed"}

    api_key = os.getenv("GOOGLE_API_KEY")
    if not api_key:
        return {"error": "GOOGLE_API_KEY not configured"}

    genai.configure(api_key=api_key)
    path = Path(file_path)
    if not path.exists():
        return {"error": f"File not found: {file_path}"}

    mime_types = {".mp3": "audio/mpeg", ".wav": "audio/wav", ".m4a": "audio/mp4", ".flac": "audio/flac"}
    mime_type = mime_types.get(path.suffix.lower(), "audio/wav")

    try:
        with open(file_path, "rb") as f:
            audio_data = f.read()

        model = genai.GenerativeModel(os.getenv("GEMINI_MODEL", "gemini-3.5-flash"))
        prompt = (
            f"Transcribe this audio in {language}. "
            "Format each line as: start_seconds - end_seconds: text. "
            "Preserve exact timestamps. Remove filler words."
        )

        response = model.generate_content(
            [
                {"mime_type": mime_type, "data": base64.b64encode(audio_data).decode()},
                prompt,
            ]
        )

        transcript_text = response.text or ""
        segments = _parse_transcript(transcript_text)
        return {
            "full_text": transcript_text,
            "segments": segments,
            "language": language,
            "duration_seconds": segments[-1]["end"] if segments else 0,
        }
    except Exception as e:
        logger.error(f"Transcription failed: {e}")
        return {"error": str(e)}


def _parse_transcript(text: str) -> List[Dict[str, Any]]:
    segments = []
    for line in text.strip().split("\n"):
        line = line.strip()
        if not line or " - " not in line or ":" not in line:
            continue
        try:
            time_part, content = line.split(":", 1)
            start_str, end_str = time_part.strip().split(" - ")
            segments.append({
                "start": float(start_str.strip()),
                "end": float(end_str.strip()),
                "text": content.strip(),
            })
        except ValueError:
            continue
    return segments
