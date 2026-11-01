"""Agent telemetry: one event bus, one ring buffer, redaction guarantees.

Every producer (pipeline agents, timeline agent, renders) writes through
record_activity; rows cap at 50/job, seq is monotonic per job, the payload
carries locate data (clip_ids / time_range), and detail strings never leak
prompt bodies or transcript text.
"""
from app.agents import telemetry as tel
from app.agents.telemetry import ActivityContext, activity_of, record_activity


def test_row_schema_and_locate_payload():
    row = record_activity("j-tel-schema", "editor", "apply_batch",
                          status=tel.STATUS_SUCCEEDED,
                          detail="applied 3 ops",
                          clip_ids=["v1-01", "v1-02"],
                          time_range=[1.23456, 4.5],
                          revision_before=2, revision_after=3,
                          duration_ms=42, parent_agent="supervisor")
    for key in ("action_id", "agent", "action", "status", "detail", "clip_ids",
                "time_range", "revision_before", "revision_after",
                "duration_ms", "timestamp", "seq"):
        assert key in row
    assert row["action_id"].startswith("act_")
    assert row["clip_ids"] == ["v1-01", "v1-02"]
    assert row["time_range"] == [1.235, 4.5]           # rounded to ms precision
    assert row["revision_before"] == 2 and row["revision_after"] == 3
    assert row["parent_agent"] == "supervisor"


def test_seq_is_monotonic_per_job():
    rows = [record_activity("j-tel-seq", "editor", "step", emit_sse=True)
            for _ in range(4)]
    seqs = [r["seq"] for r in rows]
    assert seqs == sorted(set(seqs))                    # strictly increasing
    assert seqs[-1] - seqs[0] == 3


def test_ring_buffer_caps_at_fifty_keeping_latest():
    for _ in range(tel.RING_LEN + 12):
        record_activity("j-tel-ring", "editor", "tick")
    rows = activity_of("j-tel-ring")
    assert len(rows) == tel.RING_LEN                    # 50
    # newest kept, oldest evicted: seq continuity survives the ring
    assert rows[0]["seq"] == 12 and rows[-1]["seq"] == tel.RING_LEN + 11


def test_filters_by_agent_action_status():
    record_activity("j-tel-filter", "editor", "plan", status=tel.STATUS_SUCCEEDED)
    record_activity("j-tel-filter", "render", "encode", status=tel.STATUS_RUNNING)
    record_activity("j-tel-filter", "render", "encode", status=tel.STATUS_FAILED)
    got = activity_of("j-tel-filter", agent="render", action="encode")
    assert len(got) == 2
    got = activity_of("j-tel-filter", agent="render", status=tel.STATUS_FAILED)
    assert len(got) == 1 and got[0]["status"] == tel.STATUS_FAILED
    # limit applies to the filtered tail
    assert len(activity_of("j-tel-filter", agent="render", limit=1)) == 1


def test_detail_redaction_never_leaks_prompts_or_transcripts():
    assert "super secret" not in tel._redact("prompt=super secret")
    assert "we arrived by" not in tel._redact("transcript: we arrived by the river")
    assert "```python" not in tel._redact("look ```python code```")
    record_activity("j-tel-redact", "editor", "llm_call",
                    detail="prompt=<full user prompt body>")
    rows = activity_of("j-tel-redact")
    assert rows and "prompt=<full user prompt body>" not in rows[-1]["detail"]
    assert rows[-1]["detail"] == ""                 # truncated at the marker -> nothing leaked


def test_activity_context_emits_running_then_terminal():
    with ActivityContext("j-tel-ctx", "editor", "analyze", parent_agent="supervisor"):
        running = activity_of("j-tel-ctx", status=tel.STATUS_RUNNING)
        assert len(running) == 1
    rows = activity_of("j-tel-ctx", status=tel.STATUS_SUCCEEDED)
    assert len(rows) == 1
    assert rows[0]["duration_ms"] is not None           # timed by the context


def test_activity_context_marks_failures():
    try:
        with ActivityContext("j-tel-ctx-fail", "editor", "explode"):
            raise RuntimeError("boom")
    except RuntimeError:
        pass
    rows = activity_of("j-tel-ctx-fail", status=tel.STATUS_FAILED)
    assert len(rows) == 1
    assert "boom" in rows[0]["detail"]


def test_rows_reachable_through_the_event_store_for_sse_replay():
    """record_activity mirrors rows into JobStateService as agent_activity
    events so cold-load replay (GET /agent/activity) and SSE share one bus."""
    from app.services.firestore_service import JobStateService
    record_activity("j-tel-store-1", "scout", "triage", parent_agent="archivist")
    events = JobStateService.get_events("j-tel-store-1")
    agent_rows = [e for e in events if e.get("stage") == "agent_activity"]
    assert agent_rows
    assert agent_rows[-1]["agent"] == "scout"
    assert agent_rows[-1]["parent_agent"] == "archivist"


def test_record_activity_ignores_blank_jobs():
    assert record_activity(None, "editor", "noop") is None


def test_plan_rows_carry_an_expandable_operation_list_without_content():
    """Rows expose op names + targets for the feed's expandable plan view,
    never caption text, prompts, or transcript bodies."""
    row = record_activity(
        "j-tel-ops", "timeline_agent", "plan",
        operations=[
            {"op": "delete", "args": {"clip_id": "v1-02"}},
            {"op": "set_profile", "args": {"profile": "shorts"}},
            {"op": "add_caption", "args": {"text": "a private family line"}},
            "not-an-op",
        ],
    )
    assert row["operations"] == [
        {"op": "delete", "target": "v1-02"},
        {"op": "set_profile", "target": "shorts"},
        {"op": "add_caption"},
    ]
    assert "private family line" not in str(row)
    # rows without a plan stay lean
    plain = record_activity("j-tel-ops", "editor", "render")
    assert "operations" not in plain


def test_operation_list_is_capped_at_twenty():
    row = record_activity("j-tel-ops-cap", "timeline_agent", "plan",
                          operations=[{"op": "split", "args": {}}] * 40)
    assert len(row["operations"]) == 20


def test_rows_carry_the_provider_model_badge(monkeypatch):
    """Every row names the model that did the work (visible usage badge)."""
    from app.config import settings

    monkeypatch.setattr(settings, "LLM_PROVIDER", "meta", raising=False)
    monkeypatch.setattr(settings, "META_TEXT_MODEL", "meta-llama/Meta-Llama-3.1-8B-Instruct", raising=False)
    row = record_activity("j-tel-badge", "editor", "plan")
    assert (row["provider"], row["model"]) == ("meta", "muse-spark-1.3")

    overridden = record_activity("j-tel-badge", "archivist", "transcribe",
                                 provider="meta", model="muse-voice-transcribe")
    assert overridden["model"] == "muse-voice-transcribe"

    monkeypatch.setattr(settings, "LLM_PROVIDER", "meta", raising=False)
    fallback = record_activity("j-tel-badge", "editor", "plan")
    assert fallback["provider"] == "meta" and fallback["model"]
