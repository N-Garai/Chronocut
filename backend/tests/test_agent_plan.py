"""Agent plan integration: plan-only shape, all-or-nothing validation, caps.

plan_operations is the safe dry-run the planner hands its proposals through;
these tests pin the returned shapes so the client can treat a plan as
apply-once data (times in seconds, base_revision echoed back).
"""
import pytest

from app.edl.operations import (MAX_OPS, OperationValidationError,
                                plan_operations)
from app.agents.planner import plan_from_message
from tests.edl_fixtures import make_edl


# ---------------------------------------------------------------- plan_operations shape
def test_plan_operations_returns_normalized_ops_and_info():
    edl = make_edl()
    batch = [{"op": "set_grade_all", "args": {"value": "cinematic"}},
             {"op": "set_transition_all", "args": {"value": "crossfade_0.5s"}}]
    ops_list, info = plan_operations(edl, batch)
    assert ops_list == batch                       # normalized echo of the batch
    assert info["total_ops"] == 2
    assert info["would_succeed"] == 2 and info["would_fail"] == 0
    assert all(r["ok"] for r in info["results"])
    assert info["duration_after"] == 15.0          # global
    assert info["clips_after"] >= 3


def test_plan_operations_reports_partially_failing_batches():
    """A plan with one doomed op stays plan-valid: the doomed op is reported
    per-op (ok: False) instead of throwing — the client sees the skip."""
    edl = make_edl()
    batch = [{"op": "set_grade_all", "args": {"value": "cinematic"}},
             {"op": "split", "args": {"clip_id": "does-not-exist", "at": 1.0}}]
    _, info = plan_operations(edl, batch)
    assert info["total_ops"] == 2
    assert info["would_succeed"] == 1 and info["would_fail"] == 1
    ok_rows = [r for r in info["results"] if r["ok"]]
    bad_rows = [r for r in info["results"] if not r["ok"]]
    assert len(ok_rows) == 1 and ok_rows[0]["op"] == "set_grade_all"
    assert len(bad_rows) == 1
    assert "does-not-exist" in bad_rows[0]["error"]
    # the original EDL was never mutated (dry run deep-copies)
    assert (edl["tracks"][0]["clips"][0]["effects"] or [{}])[0].get("value") == "nostalgic"


def test_plan_operations_rejects_unknown_op_and_oversize_batches():
    edl = make_edl()
    with pytest.raises(OperationValidationError):
        plan_operations(edl, [{"op": "saturate_everything", "args": {}}])
    huge = [{"op": "set_grade_all", "args": {"value": "clean"}} for _ in range(MAX_OPS + 1)]
    with pytest.raises(OperationValidationError):
        plan_operations(edl, huge)
    # exactly MAX_OPS is accepted (cap is inclusive)
    _, info = plan_operations(edl, huge[:MAX_OPS])
    assert info["total_ops"] == MAX_OPS


# ---------------------------------------------------------------- planner plan-only shape
@pytest.mark.asyncio
async def test_plan_from_message_returns_plan_only_payload():
    edl = make_edl()
    plan = await plan_from_message(job_id="j-plan-1", message="cut every 4s",
                                   edl=edl, base_revision=3, use_llm=False)
    for key in ("message", "operations", "requires_confirmation", "warnings",
                "base_revision", "plan_kind"):
        assert key in plan
    assert plan["operations"] == [{"op": "split_every", "args": {"seconds": 4.0}}]
    assert plan["requires_confirmation"] is False
    assert plan["base_revision"] == 3
    # plan-only: the passed EDL is untouched
    assert len(edl["tracks"][0]["clips"]) == 3


@pytest.mark.asyncio
async def test_stale_base_revision_never_returns_a_plan():
    edl = make_edl()
    with pytest.raises(OperationValidationError):
        await plan_from_message(job_id="j-plan-2", message="cut every 4s",
                                edl=edl, base_revision=2, use_llm=False)
    with pytest.raises(OperationValidationError):
        await plan_from_message(job_id="j-plan-3", message="cut every 4s",
                                edl=edl, base_revision=99, use_llm=False)


@pytest.mark.asyncio
async def test_llm_unavailable_degrades_to_a_clean_empty_plan():
    """When the LLM provider is down, open-ended requests return a safe
    plan-only result with no operations — never a partial or crash."""
    edl = make_edl()
    plan = await plan_from_message(job_id="j-plan-4",
                                   message="recut this into a three act festival film",
                                   edl=edl, base_revision=3, use_llm=True)
    assert plan["operations"] == []
    assert plan["plan_kind"] in ("error", "clarify")
    assert plan["base_revision"] == 3
    assert len(plan["warnings"]) >= 1 or plan["message"]


@pytest.mark.asyncio
async def test_every_deterministic_phrase_plans_applyable_ops():
    """Sweep the common command vocabulary: no plan may contain an op that
    fails the dry-run (all-or-nothing guarantee for deterministic parses)."""
    phrases = ["cut at 5", "cut every 3s", "make it cinematic",
               "add captions", "pan right", "half speed"]
    for i, phrase in enumerate(phrases):
        edl = make_edl()
        plan = await plan_from_message(job_id=f"j-plan-sweep-{i}", message=phrase,
                                       edl=edl, base_revision=3, use_llm=False)
        if not plan["operations"]:
            continue    # no deterministic coverage for this phrase pair is fine
        _, info = plan_operations(edl, plan["operations"])
        bad = [r for r in info["results"] if not r["ok"]]
        assert bad == [], f"{phrase!r} planned ops that would fail: {bad}"


# ---------------------------------------------------------------- read tools
def test_read_tools_feed_the_planner_prompt():
    from app.agents.planner import _llm_prompt, _tool_context
    from app.agents.timeline_context import build_snapshot_from_edl

    edl = make_edl()
    edl["tracks"][0]["clips"][0]["name"] = "Kolkata courtyard"
    ctx = _tool_context(edl, "j-tools", "turn the courtyard shot cinematic")
    assert ctx["clips_total"] >= 3
    assert any(m["term"] == "courtyard" and m["count"] >= 1 for m in ctx["matches"])
    assert "render" in ctx and "revision" in ctx["render"]

    prompt = _llm_prompt("turn it cinematic", build_snapshot_from_edl(edl, job_id="j-tools"), ctx)
    assert "Read-tool results" in prompt
    assert "courtyard" in prompt
    # no tools -> the prompt stays clean
    assert "Read-tool results" not in _llm_prompt("x", {}, {})


def test_read_tools_never_raise_on_a_broken_edl():
    from app.agents.planner import _tool_context
    assert _tool_context({}, "j-broken", "cut here")["clips_total"] == 0
