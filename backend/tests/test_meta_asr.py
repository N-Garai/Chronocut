"""Meta ASR chunking: window planning, overlap dedupe, failure ergonomics.

Pure-logic surfaces only — the network path is covered by provider tests.
"""
import pytest

from app.tools.audio.meta_asr import (ASRError, _dedupe_overlap, plan_chunks)


def test_short_audio_is_a_single_window():
    assert plan_chunks(5.0, 10) == [(0.0, 5.0)]
    assert plan_chunks(10.0, 10) == [(0.0, 10.0)]
    assert plan_chunks(0.0, 10) == [(0.0, 0.001)]      # degenerate but valid


def test_long_audio_chunks_keep_the_overlap_intact():
    chunks = plan_chunks(20.0, 10, overlap=0.5)
    assert chunks == [(0.0, 10.0), (9.5, 19.5), (19.0, 20.0)]
    # every window respects the per-request cap
    assert all(end - start <= 10.0 for start, end in chunks)
    # consecutive windows overlap by exactly the head overlap
    assert chunks[1][0] == chunks[0][1] - 0.5
    assert chunks[2][0] == chunks[1][1] - 0.5
    # coverage is contiguous from 0 to the end
    assert chunks[0][0] == 0.0 and chunks[-1][1] == pytest.approx(20.0)


def test_exactly_aligned_duration_is_not_rechunked_forever():
    chunks = plan_chunks(30.0, 10, overlap=0.5)
    # 4 windows cover 30 s with no runaway duplication
    assert len(chunks) == 4
    assert all(e <= 30.0 for _, e in chunks)


def test_dedupe_overlap_drops_duplicated_overlap_spans():
    segs = [
        {"start": 0.0, "end": 5.0, "text": "We arrived by the river."},
        # the 0.5 s head overlap re-heard the same sentence, slightly longer
        {"start": 4.5, "end": 9.6, "text": "we arrived by the river."},
        {"start": 9.5, "end": 14.0, "text": "Then we moved to the house."},
    ]
    out = _dedupe_overlap(segs, overlap=0.5)
    assert len(out) == 2
    assert out[0] == segs[1]                    # the longer duplicate wins
    assert out[1] == segs[2]


def test_dedupe_overlap_keeps_shorter_duplicates_back():
    segs = [
        {"start": 0.0, "end": 5.0, "text": "Mother sang the old songs."},
        {"start": 4.6, "end": 6.0, "text": "mother sang the old songs."},
    ]
    out = _dedupe_overlap(segs, overlap=0.5)
    assert len(out) == 1 and out[0] is segs[0]   # the shorter echo is discarded


def test_dedupe_overlap_preserves_distinct_text():
    segs = [
        {"start": 0.0, "end": 5.0, "text": "Sunset over the ghat."},
        {"start": 4.9, "end": 9.0, "text": "Boats drifted downstream."},
    ]
    assert _dedupe_overlap(segs, overlap=0.5) == segs


def test_dedupe_overlap_noop_cases():
    segs = [{"start": 0.0, "end": 2.0, "text": "a"}]
    assert _dedupe_overlap(segs, overlap=0.5) == segs
    segs = [{"start": 0.0, "end": 2.0, "text": "a"},
            {"start": 2.0, "end": 4.0, "text": "a"}]
    assert _dedupe_overlap(segs, overlap=0.0) == segs   # overlap off = passthrough


def test_asr_error_exists_for_the_retry_surface():
    assert issubclass(ASRError, Exception)
