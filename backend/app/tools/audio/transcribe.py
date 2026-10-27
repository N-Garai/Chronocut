import logging
import os
from typing import Optional, Dict, Any, List

logger = logging.getLogger("chronocut.tools.audio")

__all__ = ["gemini_audio_transcribe", "whisper_transcribe", "synthesize_speech", "get_duration"]

# R5: session-level flag to skip edge-tts after a 403 block. Uses a file sentinel
# so the flag survives across multiprocessing child processes (each job runs in
# a fresh spawned process, so module-level vars don't persist).
_EDGE_TTS_BLOCKED_FLAG = "/tmp/chronocut_edge_tts_blocked"


def _is_edge_tts_blocked() -> bool:
    try:
        return os.path.exists(_EDGE_TTS_BLOCKED_FLAG)
    except Exception:
        return False


def _mark_edge_tts_blocked() -> None:
    try:
        with open(_EDGE_TTS_BLOCKED_FLAG, "w") as f:
            f.write("blocked")
    except Exception:
        pass


def get_duration(file_path: str) -> float:
    try:
        import subprocess, json
        out = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration",
             "-of", "default=noprint_wrappers=1:nokey=1", file_path],
            capture_output=True, text=True, timeout=30,
        )
        return float(out.stdout.strip() or 0)
    except Exception:
        return 0.0


async def gemini_audio_transcribe(file_path: str, language: str = "en", job_id: Optional[str] = None) -> Dict[str, Any]:
    """Transcribe audio via Gemini native audio (free-tier Flash)."""
    from app.tools.llm.call import scored_gemini_call
    try:
        with open(file_path, "rb") as f:
            data = f.read()
    except Exception as e:
        return {"full_text": "", "segments": [], "language": language, "duration_seconds": 0, "error": str(e)}

    mime = {
        ".mp3": "audio/mpeg", ".wav": "audio/wav", ".m4a": "audio/mp4",
        ".aac": "audio/aac", ".ogg": "audio/ogg", ".flac": "audio/flac",
        ".opus": "audio/opus",
    }.get(os.path.splitext(file_path)[1].lower(), "audio/wav")

    prompt = (
        f"Transcribe this audio in language '{language}'. "
        "Return each line as: start_seconds - end_seconds: spoken text. "
        "Use real timestamps. Keep words exactly as spoken (do not invent)."
    )
    try:
        raw = await scored_gemini_call(
            prompt, system="You are a precise multilingual transcription engine.",
            job_id=job_id, agent="archivist", tool="gemini_audio_transcribe",
            temperature=0.2, max_output_tokens=4096,
            media=[{"data": data, "mime_type": mime}], json_mode=False,
        )
        segments = _parse_transcript(raw)
        duration = segments[-1]["end"] if segments else get_duration(file_path)
        return {"full_text": raw, "segments": segments, "language": language, "duration_seconds": duration}
    except Exception as e:
        logger.error(f"Gemini transcription failed: {e}")
        return {"full_text": "", "segments": [], "language": language, "duration_seconds": get_duration(file_path), "error": str(e)}


def whisper_transcribe(file_path: str, language: str = "en", model: str = "base") -> Dict[str, Any]:
    """Local Whisper transcription (optional, no API cost)."""
    try:
        import whisper
    except ImportError:
        logger.warning("whisper not installed; skipping local transcription")
        return {"full_text": "", "segments": [], "language": language, "duration_seconds": 0}
    try:
        m = whisper.load_model(model)
        res = m.transcribe(file_path, language=language)
        segments = [{"start": s["start"], "end": s["end"], "text": s["text"].strip()}
                    for s in res.get("segments", [])]
        return {"full_text": res.get("text", ""), "segments": segments,
                "language": res.get("language", language),
                "duration_seconds": segments[-1]["end"] if segments else get_duration(file_path)}
    except Exception as e:
        logger.error(f"Whisper failed: {e}")
        return {"full_text": "", "segments": [], "language": language, "duration_seconds": 0, "error": str(e)}


async def synthesize_speech(text: str, language: str = "en", out_path: Optional[str] = None) -> Optional[str]:
    """Free TTS. edge-tts (neural, no key) is primary; gTTS is the fallback.

    A6: this is an async function so it is ``await``ed from the orchestrator —
    the previous Gemini-TTS fallback used ``asyncio.run`` inside the async path,
    which raised RuntimeError. That fallback is removed (Gemini returns no audio
    here); gTTS/edge-tts are the real free paths.
    """
    if not text or not text.strip():
        return None
    if out_path is None:
        import tempfile
        out_path = os.path.join(tempfile.gettempdir(), f"chronocut_tts_{abs(hash(text))}.mp3")

    # R5: if edge-tts was blocked by a previous 403 (in this or any prior job),
    # skip it entirely and use gTTS directly.
    if _is_edge_tts_blocked():
        return await _gtts_fallback(text, language, out_path)

    # J2: edge-tts primary — free, no API key, neural voices, supports rate/pitch.
    # N4: capture word-boundary timestamps so the HyperFrames overlay renderer can
    # burn word-synced (karaoke) captions. Written as a sidecar "<out>.words.json".
    try:
        import edge_tts  # type: ignore
        import io as _io
        voice = "en-US-GuyNeural" if (language or "en") == "en" else None
        comm = edge_tts.Communicate(text, voice) if voice else edge_tts.Communicate(text)
        words: List[Dict[str, Any]] = []
        audio_buffer = _io.BytesIO()
        tts_error = None
        try:
            async for ev in comm.stream():
                if getattr(ev, "type", None) == "WordBoundary" and getattr(ev, "text", None):
                    offset_s = float(getattr(ev, "offset", 0) or 0) / 10_000_000.0
                    dur_s = float(getattr(ev, "duration", 0) or 0) / 10_000_000.0
                    words.append({"word": ev.text, "start": round(offset_s, 3),
                                  "end": round(offset_s + dur_s, 3)})
                elif hasattr(ev, "data") and ev.data:
                    audio_buffer.write(ev.data)
        except Exception as e:
            tts_error = e
            # If streaming fails (older edge-tts, network hiccup, or 403 block),
            # fall back to the synchronous save path which uses a fresh stream internally.
            try:
                # Re-create Communicate so stream() can be called again.
                comm2 = edge_tts.Communicate(text, voice) if voice else edge_tts.Communicate(text)
                await comm2.save(out_path)
                if os.path.exists(out_path) and os.path.getsize(out_path) > 0:
                    return out_path
            except Exception as e2:
                logger.warning(f"edge-tts save fallback failed: {e2}")
                # If the error is a 403, skip edge-tts entirely and go to gTTS.
                if "403" in str(e2) or "Invalid response" in str(e2):
                    logger.warning("edge-tts blocked (403); falling back to gTTS")
                    _mark_edge_tts_blocked()
                    return await _gtts_fallback(text, language, out_path)
                return None
        else:
            try:
                with open(out_path, "wb") as f:
                    f.write(audio_buffer.getvalue())
            except Exception as e2:
                logger.warning(f"edge-tts write failed: {e2}")
                return None
        if os.path.exists(out_path) and os.path.getsize(out_path) > 0:
            if words:
                try:
                    import json
                    with open(out_path + ".words.json", "w", encoding="utf-8") as wf:
                        json.dump({"text": text, "words": words}, wf)
                except Exception:
                    pass
            return out_path
    except Exception as e:
        logger.warning(f"edge-tts failed: {e}")

    # Fallback: gTTS.
    return await _gtts_fallback(text, language, out_path)


async def _gtts_fallback(text: str, language: str, out_path: str) -> Optional[str]:
    """gTTS fallback for TTS when edge-tts is unavailable."""
    try:
        from gtts import gTTS
        gTTS(text=text, lang=language or "en", slow=False).save(out_path)
        if os.path.exists(out_path) and os.path.getsize(out_path) > 0:
            return out_path
    except Exception as e:
        logger.warning(f"gTTS failed: {e}")
    return None


def _parse_transcript(text: str) -> List[Dict[str, Any]]:
    segments = []
    for line in text.strip().split("\n"):
        line = line.strip()
        if not line or " - " not in line or ":" not in line:
            continue
        try:
            time_part, content = line.split(":", 1)
            start_str, end_str = time_part.strip().split(" - ")
            segments.append({"start": float(start_str.strip()), "end": float(end_str.strip()),
                             "text": content.strip()})
        except ValueError:
            continue
    return segments
