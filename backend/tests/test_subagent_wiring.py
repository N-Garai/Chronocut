"""Sub-agent runtime wiring: engaged specialists actually run and leave a trace.

Covers the deterministic keyword gate (off = zero model calls), fragment→parent
op mapping with allow-list enforcement, agent_context persistence in stage
order, and the planner merging specialist ops into one validated batch.
"""
import asyncio

import pytest

from app.agents import agent_context as ctx
from app.agents import subagents as S
from app.agents.planner import plan_from_message
from app.agents.timeline_context import build_snapshot_from_edl
from app.services.firestore_service import JobStateService
from tests.edl_fixtures import make_edl

JOB = "j-subwire"


class _Msg:
    def __init__(self, content):
        self.message = type("M", (), {"content": content})


def _fake_llm(monkeypatch, payload):
    """Patch the provider call used by SubAgentRunner; counts invocations."""
    calls = []

    async def fake(*_a, **kwargs):
        calls.append(kwargs.get("agent"))
        return payload

    import app.tools.llm.call as call_mod
    monkeypatch.setattr(call_mod, "scored_llm_json", fake)
    return calls


def test_message_keywords_are_deterministic():
    assert S.choices_from_message("make it cinematic") == {
        "motionist": "cinematic", "colorist": "cinematic", "transitionist": "auto"}
    assert S.choices_from_message("add captions and slow motion")["typographer"] == "plain"
    assert S.choices_from_message("slow motion")["motionist"] == "auto"
    # a plain structural command engages nothing
    assert S.choices_from_message("cut every 3 seconds") == {}
    assert S.choices_from_message("") == {}


def test_off_keywords_make_zero_model_calls(monkeypatch):
    calls = _fake_llm(monkeypatch, {"fragments": []})
    out = asyncio.run(S.engage_editor_specialists(JOB, "delete the selected clip", "{}"))
    assert out["engaged"] == [] and out["ops"] == []
    assert calls == []


def test_fragments_map_to_allowed_parent_ops():
    assert S.fragments_to_ops("colorist", [{"value": "nostalgic"}]) == [
        {"op": "set_grade_all", "args": {"value": "nostalgic"}}]
    assert S.fragments_to_ops("motionist", {"motion": "push_in"}) == [
        {"op": "set_motion_all", "args": {"value": "push_in"}}]
    assert S.fragments_to_ops("transitionist", [{"recipe": "crossfade"}]) == [
        {"op": "set_transition_all", "args": {"value": "crossfade"}}]
    assert S.fragments_to_ops("typographer", [{"text": "a title"}]) == [
        {"op": "ensure_captions", "args": {}}]
    # allow-list is enforced: an invented recipe yields nothing
    assert S.fragments_to_ops("colorist", [{"value": "hyper_pink"}]) == []
    assert S.fragments_to_ops("transitionist", [{"recipe": "warp_smear"}]) == []


def test_rhythmist_cut_points_become_trims_and_are_capped():
    frag = {"cut_points": [{"clip_id": f"v1-0{i}", "edge": "end", "time": 1.0 + i}
                           for i in range(1, 9)]}
    ops = S.fragments_to_ops("rhythmist", frag)
    assert len(ops) == 6
    assert ops[0] == {"op": "trim", "args": {"clip_id": "v1-01", "edge": "end", "time": 2.0}}
    # a cut point without a target is dropped
    assert S.fragments_to_ops("rhythmist", {"cut_points": [{"edge": "end"}]}) == []


def test_engagement_records_context_and_merges_ops(monkeypatch):
    _fake_llm(monkeypatch, {"fragments": [{"value": "nostalgic", "reason": "warm archive"}]})
    out = asyncio.run(S.engage_editor_specialists(JOB, "make it cinematic", "{}"))
    assert out["engaged"], "cinematic request must engage at least one specialist"
    assert any(o["op"] == "set_grade_all" for o in out["ops"])
    rows = ctx.entries_for(JOB, "editor")
    assert rows and rows[0]["parent"] == "editor" and rows[0]["call"] is True


def test_degraded_specialist_never_blocks(monkeypatch):
    async def boom(*_a, **_kw):
        raise RuntimeError("provider down")

    import app.tools.llm.call as call_mod
    monkeypatch.setattr(call_mod, "scored_llm_json", boom)
    out = asyncio.run(S.engage_editor_specialists(JOB, "make it cinematic and warm", "{}"))
    assert out["ops"] == []
    assert out["degraded"], "failures are reported as degraded"
    assert any("degraded" in w for w in out["warnings"])


def test_call_cap_is_enforced(monkeypatch):
    calls = _fake_llm(monkeypatch, {"fragments": [{"value": "warm"}]})
    runner = S.SubAgentRunner("editor", job_id=JOB)
    for _ in range(S.MAX_CALLS_PER_APPLY + 3):
        runner.invoke  # keep the runner hot
        asyncio.run(runner.invoke("colorist", context_snippet="{}"))
    assert len(calls) == S.MAX_CALLS_PER_APPLY


def test_pipeline_stage_records_context_and_telemetry(monkeypatch):
    S.record_pipeline_stage(JOB, "archivist", "excerpter", keyword="light",
                            data={"turns": 12}, note="cleaned 12 turns")
    rows = ctx.entries_for(JOB, "archivist")
    assert rows[-1]["subagent"] == "excerpter"
    assert rows[-1]["data"]["turns"] == 12
    assert rows[-1]["call"] is False                       # no model call
    from app.agents.telemetry import activity_of
    tel = activity_of(JOB, agent="excerpter")
    assert tel and tel[-1]["parent_agent"] == "archivist"


def test_pipeline_stage_rejects_a_foreign_parent():
    assert S.record_pipeline_stage(JOB, "render", "excerpter") is None


def test_context_is_capped_and_small(monkeypatch):
    for i in range(ctx.MAX_ENTRIES + 10):
        S.record_pipeline_stage(JOB, "screenwriter", "narrativist",
                                data={"segments": i, "note": "x" * 500})
    doc = ctx.load(JOB)
    assert len(doc["entries"]) == ctx.MAX_ENTRIES
    assert doc["entries"][-1]["parent"] == "screenwriter"


def test_snapshot_carries_the_stage_context():
    S.record_pipeline_stage(JOB, "director", "scene_caster", data={"shots": 4})
    snap = build_snapshot_from_edl(make_edl(), job_id=JOB)
    assert "stage_context" in snap
    assert snap["stage_context"]["director"][0]["subagent"] == "scene_caster"


def test_stage_order_matches_the_pipeline():
    assert ctx.STAGE_ORDER == ["archivist", "screenwriter", "director", "editor", "render"]
    assert [p for p, _sid, _kw in S.PIPELINE_STAGES] == ctx.STAGE_ORDER


def test_planner_merges_specialist_ops_into_one_plan(monkeypatch):
    async def fake_engage(_job_id, _message, _ctx):
        return {"ops": [{"op": "set_grade_all", "args": {"value": "nostalgic"}},
                        {"op": "set_grade_all", "args": {"value": "hyper_pink"}}],
                "engaged": ["colorist"], "degraded": [], "warnings": []}

    import app.agents.subagents as sub
    monkeypatch.setattr(sub, "engage_editor_specialists", fake_engage)
    edl = make_edl()
    plan = asyncio.run(plan_from_message(job_id=JOB, message="cut every 3 seconds",
                                         edl=edl, base_revision=int(edl.get("revision") or 1),
                                         use_llm=False))
    ops = plan["operations"]
    grades = [o for o in ops if o["op"] == "set_grade_all"]
    assert grades == [{"op": "set_grade_all", "args": {"value": "nostalgic"}}]
    assert plan["subagents"]["engaged"] == ["colorist"]
    # every op in the response is one validated batch
    assert all("op" in o and "args" in o for o in ops)


@pytest.fixture(autouse=True)
def _cleanup():
    yield
    try:
        JobStateService.update_job(JOB, {ctx.FIELD: {"version": 1, "entries": []}})
    except Exception:
        pass
