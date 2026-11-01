"""EDL v1 schema: normalization, clamping, unknown fields/ids."""
import pytest

from app.edl.schema import (
    ALLOWED_PROFILE_RESOLUTIONS,
    EDLValidationError,
    edl_summary,
    find_clip,
    get_track,
    new_clip_id,
    normalize_edl,
    round3,
    track_clip_ids,
    validate_edl,
)
from tests.edl_fixtures import make_edl


def test_round3_and_finiteness():
    assert round3(0.123456) == 0.123
    with pytest.raises(EDLValidationError):
        round3(float("inf"))
    with pytest.raises(EDLValidationError):
        round3(float("nan"))


def test_normalize_fills_defaults():
    edl = make_edl()
    clip = get_track(edl, "v1")["clips"][1]
    assert clip["id"] == "v1-02"
    assert clip["speed"] == 1.0
    assert clip["transform"]["scale"] == 1.0
    assert clip["transition_in"] is None
    # unknown grades/motions are dropped, not fatal
    assert clip["effects"] == []
    assert get_track(edl, "v1")["clips"][0]["effects"] == [{"type": "grade", "value": "nostalgic"}]


def test_normalize_unknown_profile_falls_back():
    edl = validate_edl(normalize_edl({
        "version": "1.0", "revision": 1,
        "project": {"job_id": "j", "profile": "not_a_profile", "duration": 10.0},
        "sources": [], "tracks": [],
    }))
    assert edl["project"]["profile"] == "youtube_landscape"
    assert edl["project"]["profile"] in ALLOWED_PROFILE_RESOLUTIONS


def test_normalize_repairs_bad_durations():
    edl = validate_edl(normalize_edl({
        "version": "1.0", "revision": 1,
        "project": {"job_id": "j", "duration": 10.0},
        "sources": [{"id": "s1", "type": "image", "path": ""}],
        "tracks": [{"type": "video", "clips": [
            {"source_id": "s1", "start": 0.0, "duration": 0.0},
            {"source_id": "s1", "start": 0.0, "duration": -3},
        ]}],
    }))
    clips = get_track(edl, "v1")["clips"]
    assert all(0 < c["duration"] <= 0.041 for c in clips)


def test_validate_rejects_unknown_source():
    raw = make_edl()
    raw["tracks"][0]["clips"][0]["source_id"] = "src-ghost"
    with pytest.raises(EDLValidationError) as ei:
        validate_edl(raw)
    assert "src-ghost" in str(ei.value)


def test_validate_rejects_duration_past_project():
    raw = make_edl()
    raw["tracks"][0]["clips"][2]["duration"] = 50.0
    with pytest.raises(EDLValidationError) as ei:
        validate_edl(raw)
    assert "past project duration" in str(ei.value)


def test_validate_rejects_bad_caption_text():
    raw = make_edl()
    cap = get_track(raw, "c1")["clips"][0]
    cap["text"] = ""
    with pytest.raises(EDLValidationError):
        validate_edl(raw)
    cap["text"] = "x" * 500
    with pytest.raises(EDLValidationError) as ei:
        validate_edl(raw)
    assert "exceeds" in str(ei.value)


def test_validate_rejects_speed_out_of_bounds():
    raw = make_edl()
    raw["tracks"][0]["clips"][0]["speed"] = 99.0
    with pytest.raises(EDLValidationError) as ei:
        validate_edl(raw)
    assert "speed" in str(ei.value)


def test_new_clip_id_is_monotonic():
    assert new_clip_id("v1", []) == "v1-01"
    assert new_clip_id("v1", ["v1-01", "v1-02"]) == "v1-03"
    assert new_clip_id("v1", ["weird", "v1-07"]) == "v1-08"


def test_find_clip_and_track_helpers():
    edl = make_edl()
    track, clip = find_clip(edl, "v1-02")
    assert track["id"] == "v1" and clip["start"] == 5.0
    assert find_clip(edl, "nope") == (None, None)
    assert track_clip_ids(edl, "v1") == ["v1-01", "v1-02", "v1-03"]


def test_edl_summary_shape():
    s = edl_summary(make_edl())
    assert s["clips"] == 3
    assert s["duration"] == 15.0
    assert s["grades"] == ["nostalgic"]
    assert s["captions"] == 1
    assert s["music_source"] == "ambient:RAIN"
    assert s["transitions"] == []
