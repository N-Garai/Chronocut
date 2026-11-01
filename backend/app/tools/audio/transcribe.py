import logging
import os
from typing import Optional, Dict, Any, List

logger = logging.getLogger("chronocut.tools.audio")

__all__ = [
    "provider_audio_transcribe", "whisper_transcribe", "synthesize_speech",
    "get_duration",
]

# Module-level, lazily-loaded Meta MMS-TTS model (loaded once per process).
_TTS_TOKENIZER = None
_TTS_MODEL = None
_TTS_FAILED = False


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
    """Lazy-load the Meta MMS-TTS open weights once per process.

    Per the official model card for ``facebook/mms-tts-*``: ``VitsModel`` +
    ``AutoTokenizer``, and calling the model on tokenized input returns a
    ``SpeechOutput`` whose ``waveform`` is a float tensor at
    ``model.config.sampling_rate``. Loaded once per process; a failed load is
    marked with a module flag so narration degrades to captions instead of
    retrying a heavy import on every call.
    """
    global _TTS_TOKENIZER, _TTS_MODEL, _TTS_FAILED
    from app.config import settings

    if _TTS_MODEL is not None:
        return _TTS_TOKENIZER, _TTS_MODEL
    if (settings.TTS_PROVIDER or "mms").strip().lower() != "mms":
        _TTS_FAILED = True
        return None, None
    try:
        from transformers import VitsModel, AutoTokenizer
        model_name = settings.MMS_TTS_MODEL or "facebook/mms-tts-eng"
        tokenizer = AutoTokenizer.from_pretrained(model_name)
        model = VitsModel.from_pretrained(model_name)
        _TTS_TOKENIZER, _TTS_MODEL = tokenizer, model
        logger.info(f"MMS-TTS ready: {model_name}")
        return _TTS_TOKENIZER, _TTS_MODEL
    except Exception as e:
        logger.warning(f"MMS-TTS model load failed ({e}); narration degrades to captions")
        _TTS_FAILED = True
        return None, None


async def synthesize_speech(text: str, language: Optional[str] = None, out_path: Optional[str] = None) -> Optional[str]:
    """Narration text-to-speech with Meta MMS-TTS open weights (local, keyless).

    Synthesizes ``text`` into ``out_path`` (WAV) and returns that path on
    success, ``None`` when synthesis is unavailable or fails (callers degrade
    to captions-only). ``language`` accepts an ISO 639-3 code; mirroring
    ``MMS_TTS_LANG`` when omitted.
    """
    if not text or not text.strip():
        return None
    from app.config import settings

    if _TTS_FAILED:
        return None
    lang = (language or settings.MMS_TTS_LANG or "eng").strip() or "eng"
    if out_path is None:
        import tempfile
        base = settings.CHRONOCUT_TMP_DIR or tempfile.gettempdir()
        os.makedirs(base, exist_ok=True)
        out_path = os.path.join(base, f"chronocut_tts_{abs(hash(text))}.wav")

    tokenizer, model = _load_tts()
    if tokenizer is None or model is None:
        return None
    try:
        import torch
        import soundfile as sf
        # MMS-TTS tokenizers take plain text only (no ``language`` kwarg); the
        # per-language checkpoint selection is done through the model id.
        inputs = tokenizer(text, return_tensors="pt")
        with torch.no_grad():
            outputs = model(**inputs).waveform
        audio = outputs.squeeze(0).float().cpu().numpy()
        sampling_rate = getattr(model.config, "sampling_rate", 16000)
        sf.write(out_path, audio, sampling_rate)
        if os.path.exists(out_path) and os.path.getsize(out_path) > 0:
            logger.info(
                f"MMS-TTS narration written: {len(text)} chars, "
                f"{sampling_rate} Hz, model={settings.MMS_TTS_MODEL} (lang={lang})"
            )
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
