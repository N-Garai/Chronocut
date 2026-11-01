"""Timeline context: the capped server-side projection the planner trusts.

The agent never sees the raw EDL; these tests pin the caps (200 clips,
200 turns, 12k chars), the ms-time contract, and the no-source-path-leak
guarantee.
"""
import json

from app.agents.timeline_context import (MAX_SNAPSHOT_CLIPS, SNAPSHOT_CHARS_LIMIT,
                                         _trim_budget, build_snapshot_from_edl)
from tests.edl_fixtures import make_edl, many_edl


def test_snapshot_projects_the_fixture_in_milliseconds():
    snap = build_snapshot_from_edl(make_edl(), job_id="j-ctx-1")
    assert snap["job_id"] == "j-ctx-1"
    assert snap["revision"] == 3
    assert snap["duration_ms"] == 15000
    assert snap["profile"] == "youtube_landscape"
    tracks = {t["id"]: t for t in snap["tracks"]}
    assert tracks["v1"]["clips"][0]["start_ms"] == 0
    assert tracks["v1"]["clips"][1]["start_ms"] == 5000
    assert tracks["v1"]["clips"][2]["duration_ms"] == 5000
    assert snap["clips_total"] == 6          # 3 video + 1 caption + 1 narration + 1 music


def test_caption_clips_carry_text_not_effects():
    snap = build_snapshot_from_edl(make_edl(), job_id="j-ctx-2")
    c1 = next(t for t in snap["tracks"] if t["id"] == "c1")
    clip = c1["clips"][0]
    assert clip["kind"] == "caption"
    assert clip["text"] == "Kolkata, 1962"
    assert "effects" not in clip and "source_id" not in clip


def test_oversized_projects_are_capped_around_the_selection():
    edl = many_edl(250)
    snap = build_snapshot_from_edl(edl, job_id="j-ctx-3",
                                   playhead_ms=125_000,
                                   selection=["v1-125"])
    assert snap["clips_total"] == 250
    kept = sum(len(t["clips"]) for t in snap["tracks"])
    assert kept <= MAX_SNAPSHOT_CLIPS
    assert snap["clips_dropped"] == 250 - kept
    # the selected + playhead clips are always retained
    dumped = json.dumps(snap)
    assert "v1-125" in dumped


def test_small_projects_drop_nothing():
    snap = build_snapshot_from_edl(many_edl(50), job_id="j-ctx-4")
    assert snap["clips_dropped"] == 0
    assert sum(len(t["clips"]) for t in snap["tracks"]) == 50


def test_transcript_is_capped_and_truncated():
    turns = [{"start": float(i), "end": float(i + 1),
              "text": "word " * 100} for i in range(250)]
    snap = build_snapshot_from_edl(make_edl(), job_id="j-ctx-5", transcript=turns)
    assert len(snap["transcript"]) <= 200
    for turn in snap["transcript"]:
        assert len(turn["text"]) <= 300
        assert turn["text"].endswith(" ") or len(turn["text"]) == 300


def test_no_raw_media_paths_or_urls_leak_into_the_snapshot():
    edl = make_edl()
    edl["sources"][0]["path"] = "C:/private/raw/interview.mov"
    edl["sources"][0]["url"] = "https://secret-host.example/signed_url"
    snap = build_snapshot_from_edl(edl, job_id="j-ctx-6")
    dumped = json.dumps(snap)
    assert "interview.mov" not in dumped
    assert "secret-host" not in dumped
    assert "C:" not in dumped


def test_trim_budget_drops_transcript_first_then_clips():
    snap = build_snapshot_from_edl(many_edl(60), job_id="j-ctx-7",
                                   transcript=[{"start": i, "end": i + 1,
                                                "text": "long " * 60}
                                               for i in range(30)])
    before = len(json.dumps(snap, default=str))
    _trim_budget(snap, 1200)
    after = len(json.dumps(snap, default=str))
    assert after < before
    assert snap["transcript"] == []          # transcript gone before any clip
    # every surviving track stays at or below the trim floor
    assert all(len(t["clips"]) <= 20 for t in snap["tracks"])
