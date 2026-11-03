"""Video understanding: whole-clip analysis through the provider layer.

The ARCHIVIST ingest must ask the provider for a structured summary (Files API
path) and merge it with the keyframe tags, degrading silently when no provider
is configured.
"""
import asyncio

import pytest

import app.tools.media.ingest_video as ingest


class _Provider:
    name = "meta"
    default_model = "muse-spark-1.3"

    def __init__(self, payload):
        self.payload = payload
        self.calls = []

    async def describe_video(self, path, *, prompt, job_id=None):
        self.calls.append({"path": path, "prompt": prompt, "job_id": job_id})
        return self.payload


def test_understanding_merges_into_the_clip(monkeypatch):
    provider = _Provider({"summary": "A crowded platform at dusk.",
                          "setting": "railway station", "mood": "restless",
                          "subjects": ["train", "crowd"]})
    monkeypatch.setattr("app.tools.llm.provider.get_provider", lambda: provider)
    monkeypatch.setattr(ingest, "_extract_audio", lambda *_a, **_kw: False)
    monkeypatch.setattr(ingest, "_extract_frame", lambda *_a, **_kw: False)

    out = asyncio.run(ingest.ingest_video_file("/media/clip.mp4", job_id="j-vid"))
    assert out["understanding"]["summary"].startswith("A crowded platform")
    assert out["understanding"]["mood"] == "restless"
    assert "A crowded platform" in out["visual_description"]
    assert provider.calls and provider.calls[0]["job_id"] == "j-vid"
    assert "documentary editor" in provider.calls[0]["prompt"]


def test_understanding_degrades_without_a_provider(monkeypatch):
    def _boom():
        raise RuntimeError("no key")
    monkeypatch.setattr("app.tools.llm.provider.get_provider", _boom)
    monkeypatch.setattr(ingest, "_extract_audio", lambda *_a, **_kw: False)
    monkeypatch.setattr(ingest, "_extract_frame", lambda *_a, **_kw: False)

    out = asyncio.run(ingest.ingest_video_file("/media/clip.mp4", job_id="j-vid-2"))
    assert out["understanding"] == {}
    assert out["visual_description"] == ""
    assert out["transcript"] == ""


def test_understanding_keeps_frame_tags_when_summary_is_empty(monkeypatch):
    monkeypatch.setattr("app.tools.llm.provider.get_provider",
                        lambda: _Provider({}))
    monkeypatch.setattr(ingest, "_extract_audio", lambda *_a, **_kw: False)
    monkeypatch.setattr(ingest, "_extract_frame", lambda *_a, **_kw: True)

    async def fake_tag_json(*_a, **kwargs):
        return {"description": "a red doorway", "objects": ["door"], "mood": "calm"}

    monkeypatch.setattr("app.tools.llm.call.scored_llm_json", fake_tag_json)
    out = asyncio.run(ingest.ingest_video_file("/media/clip.mp4", job_id="j-vid-3"))
    assert out["understanding"] == {}
    assert out["visual_description"] == "a red doorway"
    assert out["visual_objects"] == ["door"]


def test_understanding_caps_the_transcript_hint(monkeypatch):
    provider = _Provider({"summary": "ok"})
    monkeypatch.setattr("app.tools.llm.provider.get_provider", lambda: provider)
    monkeypatch.setattr(ingest, "_extract_frame", lambda *_a, **_kw: False)
    long_text = "x" * 5000
    asyncio.run(ingest._understand_video("/media/clip.mp4", job_id="j", duration=12.0,
                                         transcript=long_text))
    prompt = provider.calls[0]["prompt"]
    assert len(prompt) < 1200
    assert "12.0s" in prompt
