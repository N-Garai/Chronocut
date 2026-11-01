"""Beat/onset analysis: the one required analyzer addition for beat-synced editing.

Wraps ``librosa.beat.beat_track`` / ``librosa.onset.onset_detect`` into one
deterministic JSON tool:

    { "beats_ms": [...], "onset_ms": [...], "tempo_bpm": float|null,
      "sync": "beat"|"none", "degraded": bool, "reason": str }

librosa is an *optional* dependency (its numba wheel is heavy on the 512 MB
API container, so it ships in requirements only commented out). The tool is
wired but never load-bearing: when librosa is missing or the analysis fails,
``sync`` resolves to ``"none"`` with a degraded telemetry row instead of
raising — a ``sync: "beat"`` plan remains valid, it just snaps to nothing.
The same JSON shape is returned either way so callers never branch on
absence.

CPU-only, no model downloads; safe on the API container and the Actions
render worker alike. Hand-written numpy onset energy detection is the
documented fallback if librosa proves heavy; it lives in ``_onset_energy()``
and is used when librosa is absent but numpy is importable.
"""
import logging
from typing import Any, Dict, List, Optional

logger = logging.getLogger("chronocut.tools.audio_analysis")

MAX_ANALYSIS_MINUTES = 10.0      # same cap as browser-side preview batches
MAX_POINTS = 2000                # keep the context bundle small


def _beat_json(beats_ms: List[int], onsets_ms: List[int], tempo: Optional[float],
               degraded: bool = False, reason: str = "") -> Dict[str, Any]:
    return {
        "beats_ms": beats_ms,
        "onset_ms": onsets_ms,
        "tempo_bpm": tempo,
        "sync": "beat" if (not degraded and beats_ms) else "none",
        "degraded": degraded,
        "reason": reason,
    }


def analyze_beats(audio_path: str, *, max_minutes: float = MAX_ANALYSIS_MINUTES,
                  job_id: Optional[str] = None) -> Dict[str, Any]:
    """One batched, read-only analysis of one audio file.

    Returns the fixed JSON shape above; never raises for analysis problems
    (only for programming errors). ``tempo_bpm`` is bounded to a sane range
    (40–300) so a degenerate detection cannot poison beat alignment.
    """
    audio_seconds = max(0.0, min(float(max_minutes), MAX_ANALYSIS_MINUTES)) * 60.0
    if not audio_path:
        return _beat_json([], [], None, True, "no audio file supplied")

    beats_ms: List[int] = []
    onsets_ms: List[int] = []
    tempo: Optional[float] = None
    tempo_val: Optional[float] = None
    reason = ""

    try:
        import os
        import librosa
        y, sr = librosa.load(audio_path, sr=22050, mono=True, duration=audio_seconds)
        if y.size == 0:
            return _beat_json([], [], None, True, "audio decoded to silence")
        tempo, beats = librosa.beat.beat_track(y=y, sr=sr, units="time")
        beats_s = [float(t) for t in (beats if beats is not None else [])]
        onsets_t = librosa.onset.onset_detect(y=y, sr=sr, units="time", backtrack=False)
        onsets_s = [float(t) for t in (onsets_t if onsets_t is not None else [])]
        try:
            tempo_val = float(tempo)
        except (TypeError, ValueError):
            tempo_val = None
        if tempo_val is not None and not (40.0 <= tempo_val <= 300.0):
            tempo_val = None
    except ImportError:
        # librosa (or its numba wheel) unavailable: deterministic numpy fallback.
        onsets_s, reason = _onset_energy(audio_path, audio_seconds)
        beats_s = []
        tempo = None
        if reason:
            return _beat_json([], [], None, True, reason)
    except FileNotFoundError:
        return _beat_json([], [], None, True, f"audio file not found: {os.path.basename(audio_path)}")
    except Exception as e:
        return _beat_json([], [], None, True, f"beat analysis failed: {type(e).__name__}")
    else:
        reason = ""

    beats_ms = sorted({int(round(b * 1000.0)) for b in beats_s if b >= 0})[:MAX_POINTS]
    onsets_ms = sorted({int(round(o * 1000.0)) for o in onsets_s if o >= 0})[:MAX_POINTS]

    return _beat_json(beats_ms, onsets_ms, tempo_val,
                      degraded=bool(reason), reason=reason)


def _onset_energy(audio_path: str, seconds: float) -> tuple:
    """numpy-only onset detection via short-window energy deltas.

    Returns (onset_seconds, degraded_reason). An empty list with a reason
    means the fallback could not run either — callers then report sync:"none".
    """
    try:
        import wave

        import numpy as np
    except ImportError:
        return [], "librosa and numpy unavailable; beat analysis disabled"
    try:
        with wave.open(str(audio_path), "rb") as w:
            sr = w.getframerate()
            frames = min(int(sr * seconds), w.getnframes())
            data = np.frombuffer(w.readframes(frames), dtype=np.int16).astype(np.float32) / 32768.0
        if data.size == 0:
            return [], "audio decoded to silence"
        hop = max(1, int(sr * 0.02))          # 20 ms windows
        win = data[: (data.size // hop) * hop].reshape(-1, hop)
        energy = np.sqrt((win ** 2).mean(axis=1))
        if energy.size < 3:
            return [], "audio too short for onset detection"
        delta = np.maximum(0.0, energy[1:] - energy[:-1])
        threshold = delta.mean() + 2.5 * delta.std()
        idx = np.where(delta > threshold)[0] + 1
        keep: List[float] = []
        last = -1.0
        for i in idx:
            t = i * 0.02
            if t - last >= 0.2:               # dedupe to 200 ms minimum spacing
                keep.append(float(t))
                last = t
        return keep, ""
    except Exception as e:
        return [], f"energy fallback failed: {type(e).__name__}"


def beat_context(audio_path: str, *, job_id: Optional[str] = None,
                 parent_agent: str = "editor") -> Dict[str, Any]:
    """analyze_beats + the degraded telemetry row the plan expects.

    Callers hand this straight into the context bundle: it never raises and
    the JSON shape is identical whether or not librosa ran.
    """
    from app.agents import telemetry as _tel

    result = analyze_beats(audio_path, job_id=job_id)
    if result.get("degraded") and job_id:
        _tel.record_activity(
            job_id, agent="audio_analysis", action="beat_analysis",
            status=_tel.STATUS_FAILED, parent_agent=parent_agent,
            detail=f"beat analysis degraded: {result.get('reason') or 'unavailable'}")
    return result
