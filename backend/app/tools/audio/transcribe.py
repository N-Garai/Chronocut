import logging
import os
from typing import Optional, Dict, Any, List

logger = logging.getLogger("chronocut.tools.audio")

__all__ = [
    "provider_audio_transcribe", "whisper_transcribe", "synthesize_speech",
    "get_duration",
]

# Module-level, lazily-loaded MMS-TTS model (loaded once per process).
_TTS_PROCESSOR = None
_TTS_MODEL = None


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


async def provider_audio_transcribe(file_path: str, language: str = "en", job_id: Optional[str] = None) -> Dict[str, Any]:
    """Provider-delegating transcription entrypoint.

    Chain: Meta muse-voice-transcribe (multipart ASR, <=10 min windows with
    overlap) -> local Whisper. Whichever path answers wins; the provider/model
    metadata is returned with the transcript. ASR audio-seconds cost is recorded
    in the ledger for the Meta path.
    """
    from app.config import settings

    provider_name = (settings.LLM_PROVIDER or "meta").strip().lower()
    if provider_name == "meta" and settings.provider_api_key:
        try:
            from app.tools.audio.meta_asr import transcribe_wav_chunked, ASRError
            res = await transcribe_wav_chunked(file_path, job_id=job_id, language=language)
            if res.get("segments") or res.get("full_text"):
                try:
                    from app.tools.llm.governor import asr_cost_cents, record_call
                    cost = asr_cost_cents(float(res.get("audio_seconds") or 0.0))
                    record_call(job_id, agent="archivist", tool="meta_asr",
                                model=settings.META_ASR_MODEL,
                                prompt_tokens=0, completion_tokens=0,
                                cost_cents=cost, cached=False, duration_ms=0)
                except Exception as gc_err:
                    logger.warning("asr cost ledger failed: %s", gc_err)
                out = {
                    "full_text": res.get("full_text", ""),
                    "segments": res.get("segments", []),
                    "language": language,
                    "duration_seconds": float(res.get("audio_seconds") or 0.0),
                    "provider": res.get("provider", "meta"),
                    "chunks": res.get("chunks", 0),
                }
                return out
            raise ASRError("meta asr returned empty transcript")
        except Exception as e:
            logger.warning("Meta ASR failed, falling back: %s", e)

    # Local Whisper (optional, no API cost).
    res = whisper_transcribe(file_path, language=language, model=settings.WHISPER_MODEL)
    if res.get("full_text"):
        res.setdefault("provider", "whisper")
        return res
    return {"full_text": "", "segments": [], "language": language,
            "duration_seconds": get_duration(file_path), "provider": "none",
            "error": "all transcription providers failed"}


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


def _load_tts():
    """Lazy-load the Meta MMS-TTS model once per process."""
    global _TTS_PROCESSOR, _TTS_MODEL
    if _TTS_MODEL is not None:
        return _TTS_PROCESSOR, _TTS_MODEL
    try:
        from transformers import VoxPopuliV2Processor, VoxPopuliV2ForConditionalGeneration
        from app.config import settings
        model_name = getattr(settings, "MMS_TTS_MODEL", "facebook/mms-tts-eng")
        processor = VoxPopuliV2Processor.from_pretrained(model_name)
        model = VoxPopuliV2ForConditionalGeneration.from_pretrained(model_name)
        _TTS_PROCESSOR, _TTS_MODEL = processor, model
        return processor, model
    except Exception as e:
        logger.warning(f"MMS-TTS model load failed: {e}")
        _TTS_MODEL = object()  # sentinel: mark attempted
        _TTS_PROCESSOR = None
        return None, None


async def synthesize_speech(text: str, language: str = "eng", out_path: Optional[str] = None) -> Optional[str]:
    """Text-to-speech using Meta MMS-TTS open weights (local, no API key).

    Synthesizes ``text`` into ``out_path`` (an MP3/WAV). Returns the path on
    success, ``None`` if synthesis is unavailable or fails. The model is loaded
    lazily and cached per process so repeated narration is cheap.
    """
    if not text or not text.strip():
        return None
    if out_path is None:
        import tempfile
        out_path = os.path.join(tempfile.gettempdir(), f"chronocut_tts_{abs(hash(text))}.wav")

    processor, model = _load_tts()
    if processor is None or model is object():
        logger.warning("MMS-TTS unavailable; no audio synthesized")
        return None
    try:
        import torch
        import soundfile as sf
        import numpy as np
        lang = getattr(model, "config", None)
        lang = getattr(lang, "lang", None) or language
        inputs = processor(text=text, return_tensors="pt", language=language)
        with torch.no_grad():
            output = model.generate(**inputs)
        audio = output[0].cpu().numpy().astype(np.float32)
        sampling_rate = getattr(model.config, "sampling_rate", 16000)
        sf.write(out_path, audio, sampling_rate)
        if os.path.exists(out_path) and os.path.getsize(out_path) > 0:
            return out_path
    except Exception as e:
        logger.warning(f"MMS-TTS synthesis failed: {e}")
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
