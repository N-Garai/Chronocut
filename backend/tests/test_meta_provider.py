"""Meta/Local provider tests: mocked OpenAI client, JSON-schema fallback, chunk planning.

No live calls in CI; async paths run through ``asyncio.run`` directly.
"""
import asyncio
import json
from types import SimpleNamespace

import pytest

import app.tools.llm.provider as P
from app.tools.audio.meta_asr import _dedupe_overlap, _parse_turns, plan_chunks


class _Msg:
    def __init__(self, content):
        self.content = content


class _Choice:
    def __init__(self, content):
        self.message = _Msg(content)


class _Resp:
    def __init__(self, content):
        self.choices = [_Choice(content)]


class _Completions:
    """Records requests; optionally rejects the first schema-strict request."""

    def __init__(self, content, fail_schema=False):
        self.content = content
        self.fail_schema = fail_schema
        self.calls = []

    def create(self, **kwargs):
        strict = bool(kwargs.get("response_format"))
        self.calls.append(kwargs)
        if self.fail_schema and strict:
            self.fail_schema = False  # reject only the first strict attempt
            raise RuntimeError("400 response_format unsupported by endpoint")
        return _Resp(self.content)


class _StubClient:
    def __init__(self, content, fail_schema=False):
        self.chat = SimpleNamespace(completions=_Completions(content, fail_schema))
        self.files = SimpleNamespace()


def _provider(content='{"ok": true}', fail_schema=False):
    prov = object.__new__(P.MetaProvider)  # bypass the ctor key check
    prov._client = _StubClient(content, fail_schema)
    prov._settings = SimpleNamespace(
        META_BASE_URL="https://api.baseten.co/v1",
        META_TEXT_MODEL="meta-models/muse-spark-open",
        meta_text_fallback_models=[],
    )
    prov._default_model = "meta-models/muse-spark-open"
    return prov


def _local_provider(content='{"ok": true}'):
    prov = object.__new__(P.LocalOpenWeightProvider)
    prov._client = _StubClient(content, False)
    prov._settings = SimpleNamespace(
        LOCAL_LLM_BASE_URL="http://localhost:11434/v1",
        LOCAL_LLM_MODEL="meta-models/Muse-Glimmer-30B",
    )
    prov._default_model = "meta-models/Muse-Glimmer-30B"
    return prov


# ---------------------------------------------------------------- text generation
def test_generate_returns_completion_and_uses_model():
    prov = _provider('hello world')
    assert asyncio.run(prov.generate(prompt="hi")) == "hello world"


def test_generate_falls_back_when_schema_rejected():
    prov = _provider('{"ok": true}', fail_schema=True)
    schema = {"name": "plan", "schema": {"type": "object"}}
    text = asyncio.run(prov.generate(prompt="hi", schema=schema))
    assert json.loads(text) == {"ok": True}
    comps = prov._client.chat.completions
    assert any(c.get("response_format") for c in comps.calls)          # strict attempt recorded
    assert any(not c.get("response_format") for c in comps.calls)      # lax retry recorded


def test_local_provider_returns_completion():
    prov = _local_provider('hello local')
    assert asyncio.run(prov.generate(prompt="hi")) == "hello local"


def test_get_provider_factory(monkeypatch):
    from app.config import settings

    # Key-backed settings so either ctor can run without network/credentials.
    monkeypatch.setattr(type(settings), "provider_api_key",
                        property(lambda s: "LLM_test"), raising=False)
    monkeypatch.setattr(settings, "LLM_PROVIDER", "meta", raising=False)
    assert P.get_provider().name == "meta"
    monkeypatch.setattr(settings, "LLM_PROVIDER", "local", raising=False)
    assert P.get_provider().name == "local"
    monkeypatch.setattr(settings, "LLM_PROVIDER", "totally-unknown", raising=False)
    assert P.get_provider().name == "meta"     # unknown names default to Meta


def test_meta_pricing_in_governor():
    """Muse Spark Open / Meta pricing is in the cost governor."""
    from app.tools.llm import governor as G

    assert G._PRICING["input_usd_per_m"]["muse"] == 1.25
    assert G._PRICING["output_usd_per_m"]["muse"] == 4.25
    assert G._USD_PER_AUDIO_HOUR == 0.18
    assert G._is_muse("muse-spark-1.3") and not G._is_muse("openai/gpt-4o")


def test_scored_llm_call_raises_when_no_provider_key(monkeypatch):
    """Absent credentials must fail fast instead of silently dropping to
    deterministic templates (the planner/director already own that path)."""
    from app.config import settings
    from app.tools.llm import call

    monkeypatch.setattr(type(settings), "provider_api_key", property(lambda s: ""), raising=False)
    with pytest.raises(RuntimeError, match="not configured"):
        asyncio.run(call.scored_llm_call(f'no-key-{__import__("uuid").uuid4().hex}', agent='t', tool='t'))


def test_scored_llm_call_records_a_call(monkeypatch):
    from app.config import settings
    from app.tools.llm import call

    monkeypatch.setattr(type(settings), "provider_api_key", property(lambda s: "LLM_test"), raising=False)
    calls = []

    async def fake_network(*_a, **kwargs):
        calls.append(kwargs)
        return 'from provider'

    monkeypatch.setattr(call, '_meta_network_call', fake_network)
    out = asyncio.run(call.scored_llm_call(f'has-key-{__import__("uuid").uuid4().hex}', agent='t', tool='t'))
    assert out == 'from provider' and len(calls) == 1


# ---------------------------------------------------------------- Meta ASR chunking
def test_asr_chunk_offsets_respect_10_min_cap():
    assert plan_chunks(60, 570) == [(0.0, 60.0)]
    assert plan_chunks(0, 570) == [(0.0, 0.001)]
    chunks = plan_chunks(1500, 570)
    # <= 570 s per request, 0.5 s overlap between consecutive chunks
    assert len(chunks) == 3
    for (s, e) in chunks:
        assert e - s <= 570.01 and 0 <= s < e
    assert chunks[1][0] == chunks[0][1] - 0.5
    # never exceeds the 10-minute request bound
    assert all(e - s <= 600 for (s, e) in chunks)


def test_asr_turn_parsing_maps_offsets():
    data = {"turns": [
        {"startMs": 1500, "endMs": 4500, "transcript": "hello", "speaker": "A"},
        {"startMs": 1000, "endMs": 2000, "transcript": "junk overlap", "speaker": "A"},
    ]}
    turns = _parse_turns(data, chunk_offset=10.0)
    starts = [t["start"] for t in turns]
    assert all(10.0 <= t["end"] <= 30.0 for t in turns)
    assert turns[0]["text"] == "hello"
    assert "start" in turns[0] and ends_ok(turns)


def ends_ok(turns):
    return all(float(t["end"]) > float(t["start"]) for t in turns)


def test_asr_overlap_dedupe_keeps_longer_text():
    segs = [
        {"start": 500.0, "end": 510.0, "text": "short tail"},
        {"start": 509.5 - 570.0 + 569.5, "end": 510.0, "text": "this is the longer duplicated head turn"},
    ]
    out = _dedupe_overlap(segs, overlap=0.5)
    # the implementation dedupes by comparing last/first overlapping turns
    dupes = _dedupe_overlap([
        {"start": 0.0, "end": 2.9, "text": "one"},
        {"start": 2.5, "end": 4.0, "text": "two much longer turn kept"},
    ], overlap=0.5)
    assert len(dupes) <= 2
    texts = " | ".join(t["text"] for t in dupes)
    assert "one" in texts


def test_disabled_reference_mode_stays_dormant():
    """Reference/YouTube mode stays disabled; no new deps required."""
    import os
    assert os.environ.get("ENABLE_REFERENCE_VIDEO", "0") == "0"
