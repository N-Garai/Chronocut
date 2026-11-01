"""Beat/onset analysis: one JSON shape, graceful degradation, deterministic
fallbacks — librosa present, absent, slow, or the file broken.
"""
import sys
import wave
from types import SimpleNamespace

import numpy as np
import pytest

from app.tools import audio_analysis as aa
from app.tools.audio_analysis import analyze_beats, beat_context


def _write_wav(path, sr=8000, seconds=2.0, spike_at=1.0):
    """A tiny deterministic WAV: quiet hum with one loud energy spike."""
    n = int(sr * seconds)
    t = np.arange(n) / sr
    data = 0.02 * np.sin(2 * np.pi * 220 * t)
    spike = int(spike_at * sr)
    data[spike:spike + 80] += 0.9
    pcm = (np.clip(data, -1, 1) * 32767).astype("<i2")
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sr)
        w.writeframes(pcm.tobytes())
    return path


def test_missing_file_degrades_with_the_fixed_shape():
    res = analyze_beats("/nowhere/at_all.wav")
    assert set(res) == {"beats_ms", "onset_ms", "tempo_bpm", "sync", "degraded", "reason"}
    assert res["beats_ms"] == [] and res["onset_ms"] == []
    assert res["tempo_bpm"] is None
    assert res["sync"] == "none"
    assert res["degraded"] is True
    assert "not found" in res["reason"]


def test_empty_path_degrades():
    res = analyze_beats("")
    assert res["degraded"] is True and res["sync"] == "none"


class _FakeLibrosa:
    """Configurable librosa stand-in injected via sys.modules."""
    def __init__(self, tempo=120.0, beats=(0.0, 0.5, 1.0), onsets=(0.1, 0.4)):
        self._tempo, self._beats, self._onsets = tempo, beats, onsets
        self.beat = SimpleNamespace(beat_track=self._beat)
        self.onset = SimpleNamespace(onset_detect=self._onset)
        self.load = self._load

    def _load(self, *_a, **_kw):
        return np.zeros(2205, dtype=np.float32), 22050

    def _beat(self, *_a, **_kw):
        return self._tempo, np.asarray(self._beats, dtype=float)

    def _onset(self, *_a, **_kw):
        return np.asarray(self._onsets, dtype=float)


def _install_librosa(monkeypatch, fake):
    monkeypatch.setitem(sys.modules, "librosa", fake)


def test_librosa_path_returns_beats_and_onsets(monkeypatch):
    _install_librosa(monkeypatch, _FakeLibrosa(beats=(0.0, 0.25, 0.5),
                                               onsets=(0.05, 0.61)))
    res = analyze_beats("/fake/anywhere.wav")
    assert res["sync"] == "beat"
    assert res["degraded"] is False
    assert res["tempo_bpm"] == 120.0
    assert res["beats_ms"] == [0, 250, 500]
    assert res["onset_ms"] == [50, 610]


def test_tempo_is_bounded_to_a_sane_range(monkeypatch):
    _install_librosa(monkeypatch, _FakeLibrosa(tempo=900.0))
    res = analyze_beats("/fake/x.wav")
    assert res["tempo_bpm"] is None            # out-of-band tempo is nulled
    assert res["sync"] == "beat"               # beats still drive the sync
    _install_librosa(monkeypatch, _FakeLibrosa(tempo="not-a-number"))
    res2 = analyze_beats("/fake/x.wav")
    assert res2["tempo_bpm"] is None


def test_degenerate_detection_degrades_not_crashes(monkeypatch):
    _install_librosa(monkeypatch, _FakeLibrosa(tempo=None, beats=(), onsets=()))
    res = analyze_beats("/fake/x.wav")
    assert res["sync"] == "none" and res["beats_ms"] == []
    # a raising decoder degrades with reason, never raises
    class _Boom(_FakeLibrosa):
        def _load(self, *_a, **_kw):
            raise RuntimeError("codec failed")
    _install_librosa(monkeypatch, _Boom())
    res2 = analyze_beats("/fake/x.wav")
    assert res2["degraded"] is True
    assert "RuntimeError" in res2["reason"]


def test_numpy_fallback_runs_without_librosa(tmp_path, monkeypatch):
    """sys.modules['librosa']=None makes `import librosa` raise ImportError,
    exercising the hand-written energy-onset fallback on a real WAV."""
    wav = _write_wav(tmp_path / "beats.wav")
    monkeypatch.setitem(sys.modules, "librosa", None)
    res = analyze_beats(wav)
    assert res["degraded"] is False            # the fallback is a valid path
    assert res["tempo_bpm"] is None            # no beat tracker -> no tempo claim
    assert res["sync"] == "none"               # beats only come from librosa
    assert 900 <= res["onset_ms"][0] <= 1100   # the spike lands at ~1.0 s


def test_corrupt_wav_falls_back_to_degraded(tmp_path, monkeypatch):
    bad = tmp_path / "bad.wav"
    bad.write_bytes(b"RIFFbroken")
    monkeypatch.setitem(sys.modules, "librosa", None)
    res = analyze_beats(str(bad))
    assert res["sync"] == "none"
    assert res["degraded"] is True
    assert res["reason"]


def test_beat_context_writes_the_degraded_telemetry_row(tmp_path):
    res = beat_context("/never/there.wav", job_id="j-audio-tel")
    assert res["degraded"] is True
    from app.agents import telemetry as tel
    rows = tel.activity_of("j-audio-tel", agent="audio_analysis",
                           status=tel.STATUS_FAILED)
    assert rows and "beat analysis degraded" in rows[-1]["detail"]
