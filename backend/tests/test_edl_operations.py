"""EDL operations: trim/split/delete/ripple/split_every/undo snapshots + clamps."""
import pytest

from app.edl.operations import (
    MAX_OPS,
    OperationValidationError,
    apply_operation,
    apply_operations,
    normalize_operation,
    plan_operations,
    validate_operations,
)
from app.edl.schema import get_track, normalize_edl, validate_edl
from tests.edl_fixtures import asr_segments, make_edl, silence_ranges


def clips_of(edl, tid="v1"):
    return get_track(edl, tid)["clips"]


def ids_of(edl, tid="v1"):
    return [c["id"] for c in clips_of(edl, tid)]


def test_split_at_7_2_produces_correct_halves():
    edl = apply_operation(make_edl(), {"op": "split", "clip_id": "v1-02", "at": 7.2})
    v1 = clips_of(edl)
    # the right piece is inserted right after its parent (new id spills past 03)
    assert ids_of(edl) == ["v1-01", "v1-02", "v1-04", "v1-03"]
    left, right = v1[1], v1[2]
    assert left["start"] == 5.0 and left["duration"] == 2.2
    assert right["start"] == 7.2 and right["duration"] == 2.8
    assert right["in"] == 2.2        # source offset advances by the cut
    assert left["in"] == 0.0


def test_split_clamps_to_shot_bounds():
    edl = apply_operation(make_edl(), {"op": "split", "clip_id": "v1-01", "at": 0.001})
    v1 = clips_of(edl)
    # cut clamped to MIN_CLIP_DURATION: still a valid 2-way split, no splinter
    assert ids_of(edl) == ["v1-01", "v1-04", "v1-02", "v1-03"]
    assert v1[0]["duration"] == 0.06 and v1[1]["duration"] == 4.94
    assert sum(c["duration"] for c in v1) == 15.0


def test_split_unknown_clip_raises_strict():
    with pytest.raises(OperationValidationError):
        apply_operation(make_edl(), {"op": "split", "clip_id": "v1-99", "at": 3.0})


def test_ripple_delete_closes_the_gap():
    edl = apply_operation(make_edl(), {"op": "delete", "clip_id": "v1-02"})
    v1 = clips_of(edl)
    assert ids_of(edl) == ["v1-01", "v1-03"]
    assert v1[1]["start"] == 5.0       # the gap is closed on the same track


def test_undo_is_a_snapshot_round_trip():
    edl = make_edl()
    new_edl, results = apply_operations(edl, [{"op": "split", "clip_id": "v1-02", "at": 7.2},
                                              {"op": "delete", "clip_id": "v1-01"}])
    assert all(r["ok"] for r in results)
    # undo: applying nothing means going back to the stored snapshot (the client
    # sends the whole prior EDL). The document must round-trip cleanly.
    restored = validate_edl(normalize_edl(edl))
    assert restored["revision"] == 3 and ids_of(restored) == ["v1-01", "v1-02", "v1-03"]


def test_split_every_three_seconds():
    edl = apply_operation(make_edl(), {"op": "split_every", "seconds": 3.0})
    v1 = clips_of(edl)
    # source shots 0-5, 5-10, 10-15 -> cuts at 3, 6, 8, 13 -> 6 clips
    assert len(v1) == 6
    assert [c["start"] for c in v1] == [0.0, 3.0, 5.0, 8.0, 10.0, 13.0]
    assert sum(c["duration"] for c in v1) == 15.0


def test_split_every_seconds_clamped():
    with pytest.raises(OperationValidationError):
        apply_operation(make_edl(), {"op": "split_every", "seconds": 0.1})
    with pytest.raises(OperationValidationError):
        apply_operation(make_edl(), {"op": "split_every", "seconds": 99})


def test_trim_head_and_tail():
    edl = apply_operation(make_edl(), {"op": "trim", "clip_id": "v1-01", "edge": "start", "time": 1.5})
    c = clips_of(edl)[0]
    assert c["start"] == 1.5 and c["duration"] == 3.5 and c["in"] == 1.5
    edl2 = apply_operation(make_edl(), {"op": "trim", "clip_id": "v1-01", "edge": "end", "time": 2.0})
    assert clips_of(edl2)[0]["duration"] == 2.0


def test_trim_head_clamps_instead_of_raising():
    # 4.999 is past the last valid cut -> clamped to keep a MIN_CLIP sliver
    edl = apply_operation(make_edl(), {"op": "trim", "clip_id": "v1-01", "edge": "start", "time": 4.999})
    c = clips_of(edl)[0]
    assert c["start"] == 4.95 and c["duration"] == 0.05 and c["in"] == 4.95
    # a no-op trim (time <= current start) is rejected
    with pytest.raises(OperationValidationError):
        apply_operation(make_edl(), {"op": "trim", "clip_id": "v1-01", "edge": "start", "time": 0.0})


def test_remove_silence_global_ripple_with_context():
    edl, results = apply_operations(
        make_edl(), [{"op": "remove_silence"}],
        context={"silence_ranges": silence_ranges()}, strict=True)
    # [0,6) eats v1-01 whole and 1s of v1-02; [12,15) eats v1-03's tail.
    # Remaining video: [0,4) + [4,9) -> content ends at 9s, sfx untouched.
    end = edl["project"]["duration"]
    assert end == 9.0
    assert all(r["ok"] for r in results)


def test_remove_silence_without_context_fails():
    with pytest.raises(OperationValidationError):
        apply_operations(make_edl(), [{"op": "remove_silence"}], strict=True)


def test_ensure_captions_from_asr_segments():
    edl = apply_operation(make_edl(), {"op": "ensure_captions"},
                          context={"asr_segments": asr_segments()})
    caps = clips_of(edl, "c1")
    assert len(caps) == 3                      # pieces capped at 80 chars / 8 s
    assert all(c["duration"] <= 8.0 for c in caps)
    assert all(c["text"] for c in caps)
    # captions sorted by start and the old caption set was replaced
    assert caps == sorted(caps, key=lambda c: c["start"])


def test_ensure_captions_without_context_fails():
    with pytest.raises(OperationValidationError):
        apply_operations(make_edl(), [{"op": "ensure_captions"}], strict=True)


def test_set_profile_updates_resolution():
    edl = apply_operation(make_edl(), {"op": "set_profile", "profile": "reels"})
    assert edl["project"]["profile"] == "reels"
    assert edl["project"]["resolution"] == {"width": 1080, "height": 1920}
    with pytest.raises(OperationValidationError):
        apply_operation(make_edl(), {"op": "set_profile", "profile": "nope"})


def test_add_and_update_caption():
    edl = apply_operation(make_edl(),
                          {"op": "add_caption", "start": 9.0, "duration": 2.0, "text": "hi"})
    caps = clips_of(edl, "c1")
    assert caps[-1]["text"] == "hi" and caps[-1]["start"] == 9.0
    edl2 = apply_operation(edl, {"op": "update_caption", "clip_id": caps[-1]["id"], "text": "bye"})
    find = get_track(edl2, "c1")["clips"][-1]
    assert find["text"] == "bye"


def test_unknown_op_rejected_at_normalization():
    with pytest.raises(OperationValidationError) as ei:
        normalize_operation({"op": "teleport_clip"})
    assert "unknown op" in str(ei.value)


def test_missing_required_arg_rejected():
    with pytest.raises(OperationValidationError) as ei:
        normalize_operation({"op": "delete"})
    assert "missing arg" in str(ei.value)


def test_more_than_max_ops_rejected():
    ops = [{"op": "delete", "clip_id": "v1-01"}] * (MAX_OPS + 1)
    with pytest.raises(OperationValidationError):
        validate_operations(ops)


def test_batch_is_not_abort_on_first_failure():
    bad = [{"op": "delete", "clip_id": "v1-99"}, {"op": "split", "clip_id": "v1-01", "at": 2.0}]
    new_edl, results = apply_operations(make_edl(), bad)
    assert results[0]["ok"] is False
    assert results[1]["ok"] is True
    assert ids_of(new_edl) == ["v1-01", "v1-04", "v1-02", "v1-03"]


def test_plan_operations_reports_would_fail():
    _, info = plan_operations(make_edl(), [{"op": "delete", "clip_id": "ghost"},
                                           {"op": "set_grade_all", "value": "cinematic"}])
    assert info["total_ops"] == 2 and info["would_fail"] == 1 and info["would_succeed"] == 1


def test_insert_broll_inserts_and_ripples():
    edl = make_edl()
    v1 = apply_operation(edl, {"op": "insert_broll", "source_id": "src-photo-03",
                               "at_ms": 6000, "duration_s": 2.0,
                               "motion": "ken_burns_slow_zoom", "kind": "still"})
    clips = clips_of(v1)
    assert len(clips) == 4
    b = [c for c in clips if (c.get("name") or "").startswith("B-roll")][0]
    assert b["start"] == 6.0 and b["duration"] == 2.0
    assert b["effects"] == [{"type": "motion", "value": "ken_burns_slow_zoom"}]
    # downstream clips shifted right by the insert
    shifted = [c for c in clips if c["id"] == "v1-03"][0]
    assert shifted["start"] == 12.0
    pre = [c for c in clips if c["id"] == "v1-02"][0]
    assert pre["start"] == 5.0
    assert v1["project"]["duration"] == 17.0


def test_insert_broll_validates_source_and_motion():
    with pytest.raises(OperationValidationError):
        apply_operation(make_edl(), {"op": "insert_broll", "source_id": "ghost", "at_ms": 100})
    with pytest.raises(OperationValidationError):
        apply_operation(make_edl(), {"op": "insert_broll", "source_id": "ambient:RAIN", "at_ms": 100})
    with pytest.raises(OperationValidationError):
        apply_operation(make_edl(), {"op": "insert_broll", "source_id": "src-photo-01",
                                     "at_ms": 100, "motion": "hyperdrive"})


def test_insert_broll_at_end_derives_duration_from_source():
    edl = apply_operation(make_edl(), {"op": "insert_broll", "source_id": "src-photo-01", "at_ms": 15000})
    clips = clips_of(edl)
    assert clips[-1]["start"] == 15.0
    assert clips[-1]["duration"] == 3.0                  # image default
    assert clips[-1]["effects"][0]["value"] == "ken_burns_slow_zoom"


def test_set_speed_rescales_duration():
    edl = apply_operation(make_edl(), {"op": "set_speed", "clip_id": "v1-01", "value": 2.0})
    c = clips_of(edl)[0]
    assert c["speed"] == 2.0 and c["duration"] == 2.5
    with pytest.raises(OperationValidationError):
        apply_operation(make_edl(), {"op": "set_speed", "clip_id": "v1-01", "value": 99.0})
