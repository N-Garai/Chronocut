"""Meta speech-to-text: multipart ASR with chunking for long audio.

The endpoint accepts mono 16-bit PCM WAV (16/24 kHz) up to ~10 minutes and
32 MB per request. Longer uploads are chunked into windows with a small
overlap; overlapping turns are deduplicated by comparing tail/head text.
"""
import asyncio
import json
import logging
import os
import subprocess
import tempfile
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger("chronocut.tools.audio.meta_asr")

SR = 24000  # 24 kHz mono 16-bit PCM per provider docs


def _probe_seconds(path: str) -> float:
    try:
        res = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration",
             "-of", "default=noprint_wrappers=1:nokey=1", path],
            capture_output=True, text=True, timeout=60,
        )
        return float(res.stdout.strip() or 0)
    except Exception:
        return 0.0


def extract_wav_24k(src_path: str, out_path: str) -> bool:
    """Normalize any audio/video input to the WAV shape the endpoint expects."""
    try:
        res = subprocess.run(
            ["ffmpeg", "-y", "-i", src_path, "-ac", "1", "-ar", str(SR),
             "-c:a", "pcm_s16le", "-loglevel", "error", out_path],
            capture_output=True, text=True, timeout=600,
        )
        return res.returncode == 0 and os.path.exists(out_path) and os.path.getsize(out_path) > 0
    except Exception as e:
        logger.warning(f"wav extraction failed: {e}")
        return False


def plan_chunks(seconds: float, max_seconds: int, overlap: float = 0.5) -> List[Tuple[float, float]]:
    """Split into <= max_seconds windows with `overlap` seconds of head overlap."""
    if seconds <= max_seconds:
        return [(0.0, max(seconds, 0.001))]
    chunks: List[Tuple[float, float]] = []
    start = 0.0
    while start < seconds - 0.01:
        end = min(start + max_seconds, seconds)
        chunks.append((start, end))
        if end >= seconds - 0.01:
            break
        start = end - overlap
    return chunks


def cut_wav_window(wav_path: str, start: float, end: float, out_path: str) -> bool:
    try:
        res = subprocess.run(
            ["ffmpeg", "-y", "-ss", f"{start:.3f}", "-to", f"{end:.3f}", "-i", wav_path,
             "-loglevel", "error", out_path],
            capture_output=True, text=True, timeout=600,
        )
        if res.returncode == 0 and os.path.exists(out_path) and os.path.getsize(out_path) > 0:
            return True
        # Zero-byte windows are treated as missing and retried by callers.
        if os.path.exists(out_path) and os.path.getsize(out_path) == 0:
            os.remove(out_path)
        return False
    except Exception as e:
        logger.warning(f"wav window cut failed: {e}")
        return False


class ASRError(RuntimeError):
    pass


def _parse_turns(data: Dict[str, Any], chunk_offset: float) -> List[Dict[str, Any]]:
    segments: List[Dict[str, Any]] = []
    for turn in data.get("turns") or []:
        start = float(turn.get("startMs") or 0) / 1000.0 + chunk_offset
        end = float(turn.get("endMs") or 0) / 1000.0 + chunk_offset
        text = (turn.get("transcript") or "").strip()
        if not text:
            continue
        seg: Dict[str, Any] = {"start": round(start, 3), "end": round(end, 3), "text": text}
        speaker = turn.get("speaker")
        if speaker not in (None, ""):
            seg["speaker"] = str(speaker)
        segments.append(seg)
    return segments


def _requests_post(session_id: str, wav_path: str, language: str, model: str) -> Dict[str, Any]:
    """Synchronous request to the transcribe endpoint (run via to_thread)."""
    import requests

    from app.config import settings
    api_key = settings.provider_api_key
    if not api_key:
        raise ASRError("provider API key is not configured")
    request_payload = json.dumps({
        "model": model,
        "language": language or "en",
        "audioEncoding": "WAV",
    })
    with open(wav_path, "rb") as f:
        resp = requests.post(
            f"{settings.META_BASE_URL.rstrip('/')}/asr/transcribe",
            params={"sessionId": session_id},
            headers={"Authorization": f"Bearer {api_key}", "Accept": "application/json"},
            files={
                "request": (None, request_payload, "application/json"),
                "audio": (os.path.basename(wav_path), f, "audio/wav"),
            },
            timeout=180,
        )
    if resp.status_code == 400:
        raise ASRError(f"asr rejected request (400): {resp.text[:200]}")
    if resp.status_code == 413:
        raise ASRError("asr request body too large (32 MB cap)")
    if resp.status_code == 429:
        raise ASRError("asr rate limited (429)")
    if resp.status_code >= 500:
        raise ASRError(f"asr unavailable ({resp.status_code})")
    if resp.status_code != 200:
        raise ASRError(f"asr failed ({resp.status_code}): {resp.text[:200]}")
    return resp.json()


async def _transcribe_chunk(wav_path: str, start: float, end: float, tmp_dir: str,
                            session_id: str, language: str, model: str,
                            chunk_index: int) -> Tuple[float, List[Dict[str, Any]]]:
    out = os.path.join(tmp_dir, f"chunk_{chunk_index}.wav")
    if start == 0.0 and end >= _probe_seconds(wav_path):
        window = wav_path
    else:
        if not cut_wav_window(wav_path, start, end, out):
            raise ASRError(f"chunk {chunk_index}: window cut failed")
        window = out
    last_err: Optional[Exception] = None
    for attempt in range(3):
        try:
            data = await asyncio.to_thread(_requests_post, session_id, window, language, model)
            return start, _parse_turns(data or {}, chunk_offset=start)
        except ASRError as e:
            last_err = e
            logger.warning(f"asr chunk {chunk_index} attempt {attempt} failed: {e}")
            await asyncio.sleep(min(2 ** attempt * 3, 45))
    raise last_err or ASRError(f"chunk {chunk_index} failed")


def _dedupe_overlap(segments: List[Dict[str, Any]], overlap: float) -> List[Dict[str, Any]]:
    """Drop duplicated spans from consecutive overlapping windows."""
    if overlap <= 0 or len(segments) < 2:
        return segments
    keep_now: List[Dict[str, Any]] = []
    for seg in segments:
        if keep_now:
            prev = keep_now[-1]
            prev_text = str(prev.get("text", "")).strip()
            seg_text = str(seg.get("text", "")).strip()
            if seg_text and seg_text.lower() == prev_text.lower():
                if (seg.get("end", 0) - seg.get("start", 0)) >= (prev.get("end", 0) - prev.get("start", 0)):
                    keep_now[-1] = seg
                continue
        keep_now.append(seg)
    return keep_now


async def transcribe_wav_chunked(audio_path: str, *, job_id: Optional[str] = None,
                                 language: str = "en") -> Dict[str, Any]:
    """Public entrypoint: normalized WAV -> chunked ASR -> merged transcript."""
    from app.config import settings

    if not os.path.exists(audio_path):
        raise ASRError(f"audio file missing: {audio_path}")

    meta: Dict[str, Any] = {"provider": "meta", "model": settings.META_ASR_MODEL, "chunks": 0}
    if not settings.provider_api_key:
        raise ASRError("provider API key is not configured")

    with tempfile.TemporaryDirectory(prefix="chronocut_asr_") as tmp:
        wav_path = os.path.join(tmp, "audio_24k.wav")
        if os.path.splitext(audio_path)[1].lower() == ".wav":
            wav_path = audio_path
        else:
            if not extract_wav_24k(audio_path, wav_path):
                raise ASRError("audio normalization failed")
        seconds = _probe_seconds(wav_path)
        meta["audio_seconds"] = round(seconds, 2)
        if seconds <= 0:
            raise ASRError("no audio duration detected")

        max_s = int(settings.META_ASR_MAX_SECONDS)
        chunks = plan_chunks(seconds, max_s, overlap=0.5)
        session_id = job_id or "chronocut"
        merged: List[Dict[str, Any]] = []
        failed = []
        for i, (start, end) in enumerate(chunks):
            try:
                _, segs = await _transcribe_chunk(
                    wav_path, start, end, tmp, session_id, language,
                    settings.META_ASR_MODEL, i,
                )
                merged.extend(segs)
                meta["chunks"] = i + 1
            except ASRError as e:
                logger.error(f"asr chunk {i} exhausted retries: {e}")
                failed.append(i)
        merged.sort(key=lambda s: s.get("start", 0))
        merged = _dedupe_overlap(merged, overlap=0.5)
        transcript = " ".join(s["text"].strip() for s in merged).strip()
        # Provider pricing ($/audio-hour -> cents) is recorded by the caller;
        # here we only surface the audited metadata.
        meta["failed_chunks"] = failed
        meta["segments"] = merged
        meta["full_text"] = transcript
        return meta
