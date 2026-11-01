"""Sub-agent registry + runner: schema, choice gating, caps, degradation.

Nineteen entries organized as five parents (EDITOR = supervisor + 6); choice
keywords engage zero model calls; fragments are validated deterministically at
merge; the ≤8-calls-per-apply cap is enforced in the runner; any sub-agent
failure degrades with a telemetry row per 13.6.
"""
import asyncio

from app.agents import telemetry as tel
from app.agents.subagents import (MAX_CALLS_PER_APPLY, REGISTRY, REGISTRY_BY_ID,
                                  SubAgentRunner, _FAMILY_ORDER, engaged_for,
                                  engages, entry, fragment_is_valid,
                                  registry_summary)


# ---------------------------------------------------------------- registry schema
def test_nineteen_entries_with_editor_supervisor_plus_six():
    assert len(REGISTRY) == 19
    editor = _FAMILY_ORDER["EDITOR"]
    assert len(editor) == 7
    assert editor[0] == "supervisor"
    assert all(sid != "supervisor" for sid in editor[1:])
    # every family-order id exists and belongs to that parent
    for parent, ids in _FAMILY_ORDER.items():
        for sid in ids:
            e = REGISTRY_BY_ID.get(sid)
            assert e is not None, f"missing registry entry {sid}"
            assert e["parent"] == parent.lower()
            assert e["family"] == parent


def test_every_entry_is_complete_and_names_its_allowlists():
    """Each registry entry names a recipe and/or analyzer allowlist."""
    for e in REGISTRY:
        for key in ("id", "parent", "family", "kind", "purpose", "prompt_template",
                    "choices", "keyword", "engagement_values", "tools",
                    "output_schema", "recipes", "analyzers", "max_calls"):
            assert key in e, f"{e['id']} missing {key}"
        assert e["kind"] in ("planner_specialist", "pipeline_tool")
        assert e["engagement_values"], f"{e['id']} has no engagement choices"
        assert "off" in e["engagement_values"], f"{e['id']} cannot be opted out"
        assert e["recipes"] or e["analyzers"], \
            f"{e['id']} names neither recipes nor analyzers"
        assert e["max_calls"] >= 1


def test_registry_summary_reflects_the_five_parents():
    s = registry_summary()
    assert s["count"] == 19
    assert s["max_calls_per_apply"] == MAX_CALLS_PER_APPLY == 8
    assert set(s["by_parent"]) == {"ARCHIVIST", "SCREENWRITER", "DIRECTOR",
                                   "EDITOR", "RENDER"}


def test_entry_lookup_tolerates_unknown_ids():
    assert entry("colorist") is REGISTRY_BY_ID["colorist"]
    assert entry("not_a_real_agent") is None
    assert entry("") is None


# ---------------------------------------------------------------- choice gating
def test_unknown_ids_never_engage():
    assert engages("not_a_sub_agent", "auto") is False


def test_off_keywords_engage_zero_calls():
    for kw in (None, "", "off", "OFF", " center ", "cut_only"):
        assert all(engages(e["id"], kw) is False for e in REGISTRY), \
            f"choice {kw!r} must engage zero model calls"


def test_known_choice_engages_its_sub_agent():
    assert engages("colorist", "cinematic") is True
    assert engages("colorist", "gentle") is True
    assert engages("typographer", "kinetic") is True
    assert engages("colorist", "sparkle") is False     # not in the choice set


def test_engaged_for_walks_family_order_and_skips_unengaged():
    plan = {"colorist": "cinematic", "supervisor": "off",
            "typographer": "kinetic", "unknown_agent": "auto"}
    assert engaged_for(plan) == ["colorist", "typographer"]
    assert engaged_for({e["id"]: "off" for e in REGISTRY}) == []


# ---------------------------------------------------------------- fragment validation
def test_fragment_validation_accepts_only_allowlisted_recipes():
    assert fragment_is_valid("colorist", [{"clip_id": "v1-01", "value": "cinematic"}])
    assert fragment_is_valid("motionist", [{"clip_id": "v1-01", "motion": "push_in"}])
    # off-allowlist recipe values are rejected at merge
    assert fragment_is_valid("colorist", [{"value": "chrome_glow"}]) is False
    assert fragment_is_valid("motionist", [{"motion": "orbit"}]) is False


def test_fragment_validation_shape_rules():
    assert fragment_is_valid("colorist", {"a": {"value": "cinematic"}})
    assert fragment_is_valid("colorist", []) is True       # empty batch = vacuous ok
    assert fragment_is_valid("colorist", {"k": "v"})       # bare dict allowed
    # list fragments must be all dicts
    assert fragment_is_valid("colorist", ["cinematic"]) is False
    assert fragment_is_valid("colorist", None) is False
    assert fragment_is_valid("nobody", []) is False


# ---------------------------------------------------------------- runner: batching + cap
class _Stub:
    """scored_llm_json stand-in: echoes fragments, counts calls."""
    calls = 0

    @classmethod
    async def ok(cls, *_a, **_kw):
        cls.calls += 1
        return {"fragments": [{"value": "cinematic"}]}

    @classmethod
    async def broken(cls, *_a, **_kw):
        cls.calls += 1
        raise RuntimeError("model unavailable")

    @classmethod
    async def bad_fragments(cls, *_a, **_kw):
        cls.calls += 1
        return {"fragments": [{"value": "chrome_glow"}]}   # off-allowlist


def test_runner_batches_one_prompt_per_sub_agent(monkeypatch):
    import app.tools.llm.call as llm_call
    _Stub.calls = 0
    monkeypatch.setattr(llm_call, "scored_llm_json", _Stub.ok)
    runner = SubAgentRunner("editor", job_id="j-sub-batch")
    out = asyncio.run(runner.invoke("colorist", context_snippet="edl..."))
    # one call reaches the LLM and returns validated fragments
    assert _Stub.calls == 1
    assert out == {"sid": "colorist", "status": "ok",
                   "fragments": [{"value": "cinematic"}]}
    rows = tel.activity_of("j-sub-batch", agent="colorist")
    assert rows[-1]["parent_agent"] == "editor"


def test_runner_hard_caps_at_eight_calls(monkeypatch):
    import app.tools.llm.call as llm_call
    _Stub.calls = 0
    monkeypatch.setattr(llm_call, "scored_llm_json", _Stub.ok)
    runner = SubAgentRunner("editor", job_id="j-sub-cap")

    async def loop():
        last = None
        for _ in range(12):
            last = await runner.invoke("colorist", context_snippet="x")
        return last

    last = asyncio.run(loop())
    assert _Stub.calls == MAX_CALLS_PER_APPLY           # exactly 8 LLM calls, no more
    assert last["status"] == "degraded"
    assert "cap" in last["detail"]


def test_runner_degrades_on_model_failure_with_telemetry_rows(monkeypatch):
    import app.tools.llm.call as llm_call
    job_id = "j-sub-degrade"
    monkeypatch.setattr(llm_call, "scored_llm_json", _Stub.broken)
    runner = SubAgentRunner("editor", job_id=job_id)
    out = asyncio.run(runner.invoke("motionist", context_snippet="x"))
    assert out["status"] == "degraded"
    assert out["fragments"] == []
    rows = tel.activity_of(job_id, agent="motionist", status=tel.STATUS_FAILED)
    assert len(rows) == 1
    assert rows[0]["parent_agent"] == "editor"
    assert "RuntimeError" in rows[0]["detail"]


def test_runner_degrades_on_invalid_fragments(monkeypatch):
    """Fragment validation at merge: an LLM answer with off-allowlist recipes
    never reaches the apply — the caller sees a degraded result instead."""
    import app.tools.llm.call as llm_call
    _Stub.calls = 0
    monkeypatch.setattr(llm_call, "scored_llm_json", _Stub.bad_fragments)
    runner = SubAgentRunner("editor", job_id="j-sub-invalid")
    out = asyncio.run(runner.invoke("colorist", context_snippet="x"))
    assert out["status"] == "degraded"
    assert out["fragments"] == []
