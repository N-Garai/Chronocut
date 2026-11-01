"""The deterministic agent command parser: fast paths, rejects, conflicts.

The parser runs at 0 ms in the planner for phrases in the shared command
vocabulary; anything outside it falls through to the (mocked-elsewhere) LLM.
Times are seconds in ops; the client works in ms.
"""
import pytest

from app.edl.operations import OperationValidationError, plan_operations
from app.agents.planner import (PROFILE_ALIASES, _deterministic_parse,
                                _needs_confirmation, _parse_time,
                                plan_from_message)
from tests.edl_fixtures import make_edl


# ---------------------------------------------------------------- times
def test_parse_time_formats():
    assert _parse_time("12.5") == 12.5
    assert _parse_time("90s") == 90.0
    assert _parse_time("1:30.25") == pytest.approx(90.25)
    assert _parse_time("2:05") == pytest.approx(125.0)
    assert _parse_time("") is None
    assert _parse_time("abc") is None
    assert _parse_time("12.5.7") is None


# ---------------------------------------------------------------- profile aliases
def test_profile_aliases_belong_to_schema():
    from app.edl.schema import ALLOWED_PROFILE_RESOLUTIONS
    for v in PROFILE_ALIASES.values():
        assert v in ALLOWED_PROFILE_RESOLUTIONS


# ---------------------------------------------------------------- deterministic paths
def test_split_at_playhead_targets_clip_under_playhead():
    edl = make_edl()
    ops = _deterministic_parse("split here", edl, playhead_s=12.5)
    assert ops and ops[0]["op"] == "split"
    assert ops[0]["args"]["clip_id"] == "v1-03"        # 10..15 covers 12.5
    assert ops[0]["args"]["at"] == 12.5


def test_split_every_maps_to_macro():
    edl = make_edl()
    assert _deterministic_parse("cut every 3s", edl) == [
        {"op": "split_every", "args": {"seconds": 3.0}}]
    # out-of-range cadence is dropped, not guessed
    assert _deterministic_parse("cut every 60s", edl) == []


def test_split_at_time_targets_overlapping_clip():
    edl = make_edl()
    ops = _deterministic_parse("cut at 12.5", edl)
    assert ops == [{"op": "split",
                    "args": {"clip_id": "v1-03", "at": 12.5}}]
    # a time in no clip's range invents nothing
    assert _deterministic_parse("cut at 99", edl) == []


def test_delete_needs_selection():
    edl = make_edl()
    assert _deterministic_parse("delete", edl) == []   # no target -> no invented op
    ops = _deterministic_parse("delete", edl, selection=["v1-02"])
    assert [(o["op"], o["args"]["clip_id"]) for o in ops] == [("delete", "v1-02")]


def test_make_it_cinematic_is_the_full_intent_batch():
    edl = make_edl()
    ops = _deterministic_parse("make it cinematic", edl)
    assert [o["op"] for o in ops] == ["set_grade_all", "set_transition_all", "set_motion_all"]
    assert ops[0]["args"]["value"] == "cinematic"
    assert ops[1]["args"]["value"] == "crossfade_0.5s"
    assert ops[2]["args"]["value"] == "push_in"


def test_grade_word_selection_is_allowlisted():
    edl = make_edl()
    ops = _deterministic_parse("grade it nostalgic", edl)
    assert ops[0]["args"]["value"] == "nostalgic"
    assert len(ops) == 1                     # no cinematic bundle for plain grades
    # an unknown look word still maps onto the valid cinematic default
    ops2 = _deterministic_parse("make the color moody", edl)
    assert ops2[0]["args"]["value"] == "cinematic"


def test_transition_and_motion_phrases():
    edl = make_edl()
    assert _deterministic_parse("1 second crossfades", edl)[0]["args"]["value"] == "crossfade_1s"
    assert _deterministic_parse("0.5s crossfade", edl)[0]["args"]["value"] == "crossfade_0.5s"
    assert _deterministic_parse("pan right", edl)[0]["args"]["value"] == "pan_right"
    assert _deterministic_parse("slow push in", edl)[0]["args"]["value"] == "push_in"


def test_speed_word_only_when_multiplier_is_sane():
    edl = make_edl()
    ops = _deterministic_parse("half speed", edl, selection=["v1-01"])
    assert ops == [{"op": "set_speed", "args": {"clip_id": "v1-01", "value": 0.5}}]
    # absurd multipliers never reach the batch
    edl2 = make_edl()
    assert _deterministic_parse("speed 99x", edl2, selection=["v1-01"]) == []


def test_caption_text_extract():
    edl = make_edl()
    ops = _deterministic_parse('caption "Kolkata 1962" at 2s', edl)
    assert ops == [{"op": "add_caption",
                    "args": {"start": 2.0, "duration": 2.5, "text": "Kolkata 1962"}}]
    assert _deterministic_parse("remove the captions", edl) == [
        {"op": "ensure_captions", "args": {"mode": "remove"}}]
    assert _deterministic_parse("add captions", edl) == [
        {"op": "ensure_captions", "args": {}}]


def test_remove_silence_phrase():
    edl = make_edl()
    ops = _deterministic_parse("remove the pauses", edl)
    assert ops == [{"op": "remove_silence", "args": {}}]
    ops = _deterministic_parse("cut dead air at 1.5s noise -32db", edl)
    assert ops[0]["op"] == "remove_silence"
    assert ops[0]["args"]["noise_db"] == -32.0


def test_profile_switch_phrase():
    edl = make_edl()
    ops = _deterministic_parse("make the format 9:16", edl)
    assert ops == [{"op": "set_profile", "args": {"profile": "instagram_portrait"}}]


def test_unrelated_message_plans_nothing_deterministically():
    edl = make_edl()
    assert _deterministic_parse("frobnicate the widgets sideways", edl) == []


# ---------------------------------------------------------------- planner integration
@pytest.mark.asyncio
async def test_plan_from_message_deterministic_split():
    edl = make_edl()
    plan = await plan_from_message(job_id="j-parser-1", message="cut at 12.5",
                                   edl=edl, base_revision=3, use_llm=False)
    assert plan["plan_kind"] == "deterministic"
    assert [o["op"] for o in plan["operations"]] == ["split"]
    assert plan["operations"][0]["args"]["at"] == 12.5
    assert plan["base_revision"] == 3


@pytest.mark.asyncio
async def test_stale_revision_is_rejected():
    edl = make_edl()   # revision 3
    with pytest.raises(OperationValidationError):
        await plan_from_message(job_id="j-parser-2", message="cut here",
                                edl=edl, base_revision=2, use_llm=False)


@pytest.mark.asyncio
async def test_unknown_phrase_returns_plan_only_no_ops():
    edl = make_edl()
    plan = await plan_from_message(job_id="j-parser-3", message="frobnicate the widgets",
                                   edl=edl, base_revision=3, use_llm=False)
    assert plan["operations"] == []
    assert plan["plan_kind"] == "none"
    assert plan["requires_confirmation"] is False
    # plan-only: nothing was written
    assert "revision" in edl and edl["revision"] == 3


@pytest.mark.asyncio
async def test_planned_ops_dry_run_against_the_edl():
    """Everything the planner returns must survive plan_operations."""
    edl = make_edl()
    plan = await plan_from_message(job_id="j-parser-4", message="make it cinematic",
                                   edl=edl, base_revision=3, use_llm=False)
    normalized, info = plan_operations(edl, plan["operations"])
    assert all(r["ok"] for r in info["results"])
    assert {o["op"] for o in normalized} == {"set_grade_all", "set_transition_all", "set_motion_all"}


def test_needs_confirmation_rules():
    edl = make_edl()
    # profile change = always confirm
    assert _needs_confirmation(edl, [{"op": "set_profile", "args": {"profile": "reels"}}])
    # replace music = confirm
    assert _needs_confirmation(edl, [{"op": "replace_music",
                                      "args": {"source_id": "ambient:RAIN"}}])
    # removing captions = confirm
    assert _needs_confirmation(edl, [{"op": "ensure_captions", "args": {"mode": "remove"}}])
    # a single small trim = no confirmation
    assert not _needs_confirmation(edl, [{"op": "trim", "args": {
        "clip_id": "v1-01", "edge": "end", "time": 4.0}}])
    # deleting 4+ clips = confirm (mass-delete guard)
    many = [{"op": "delete", "args": {"clip_id": f"v1-0{i}"}} for i in range(1, 5)]
    assert _needs_confirmation(edl, many)
