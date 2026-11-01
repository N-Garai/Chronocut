"""ARCHIVIST stage wiring: one ingestion path, provider layer only.

The transcription and tagging workers must delegate to the provider chain
(Meta first, local Whisper fallback) instead of vendor SDKs, and the
orchestrator must go through the Archivist rather than a parallel path.
"""
import asyncio
import inspect

from app.agents.archivist import ArchivistAgent
from app.agents.sub_agents.audio_transcriber import AudioTranscriberSubAgent
from app.agents.sub_agents.image_tagger import ImageTaggerSubAgent

AUDIO = "/media/interview.wav"
PHOTO = "/media/photo.png"


def test_audio_worker_delegates_to_the_provider_chain(monkeypatch):
    import app.tools.audio as audio_pkg
    calls = {}

    async def fake_transcribe(path, language="en", job_id=None):
        calls.update(path=path, language=language, job_id=job_id)
        return {"full_text": "we left at dawn", "segments": [{"start": 0, "end": 2, "text": "we left at dawn"}],
                "provider": "meta", "duration_seconds": 2.0}

    monkeypatch.setattr(audio_pkg, "provider_audio_transcribe", fake_transcribe)
    out = asyncio.run(AudioTranscriberSubAgent().transcribe(AUDIO, job_id="j-arch"))
    assert calls == {"path": AUDIO, "language": "en", "job_id": "j-arch"}
    assert out["provider"] == "meta"
    assert out["segments"][0]["text"] == "we left at dawn"


def test_audio_worker_never_raises_on_provider_failure(monkeypatch):
    import app.tools.audio as audio_pkg

    async def boom(*_a, **_kw):
        raise RuntimeError("meta asr down")

    monkeypatch.setattr(audio_pkg, "provider_audio_transcribe", boom)
    out = asyncio.run(AudioTranscriberSubAgent().transcribe(AUDIO))
    assert out["full_text"] == "" and "meta asr down" in out["error"]


def test_image_worker_delegates_to_provider_tagging(monkeypatch):
    import app.tools.llm.call as call_pkg
    calls = []

    async def fake_tag_json(*_a, **kwargs):
        calls.append(kwargs)
        return {"description": "a courtyard in 1962", "objects": ["courtyard"]}

    monkeypatch.setattr(call_pkg, "scored_llm_json", fake_tag_json)
    out = asyncio.run(ImageTaggerSubAgent().tag_single(PHOTO, job_id="j-arch"))
    assert calls and calls[0].get("job_id") == "j-arch"
    assert any("media" in kw for kw in calls)
    assert out["description"].startswith("a courtyard")


def test_image_worker_isolates_a_failing_file(monkeypatch):
    import app.tools.llm.call as call_pkg

    async def boom(*_a, **_kw):
        raise RuntimeError("vision 503")

    monkeypatch.setattr(call_pkg, "scored_llm_json", boom)
    out = asyncio.run(ImageTaggerSubAgent().tag_single(PHOTO))
    assert out["filename"] == PHOTO and "vision 503" in out["error"]


def test_archivist_combines_both_workers(monkeypatch):
    import app.tools.audio as audio_pkg
    import app.tools.llm.call as call_pkg

    async def fake_transcribe(path, language="en", job_id=None):
        return {"full_text": "the river was high", "segments": [{"start": 0, "end": 1, "text": "the river was high"}]}

    async def fake_tag_json(*_a, **kwargs):
        return {"description": "river bank"}

    monkeypatch.setattr(audio_pkg, "provider_audio_transcribe", fake_transcribe)
    monkeypatch.setattr(call_pkg, "scored_llm_json", fake_tag_json)
    out = asyncio.run(ArchivistAgent().process(
        {"audio_files": [AUDIO], "photo_files": [PHOTO]}, job_id="j-arch"))
    assert out["transcript"] == "the river was high"
    assert out["segments"] and out["segments"][0]["text"] == "the river was high"
    assert out["image_tags"][PHOTO]["description"] == "river bank"
    assert out["audio_files_processed"] == 1 and out["photo_files_processed"] == 1


def test_orchestrator_stage_uses_the_archivist():
    from app.agents import orchestrator

    src = inspect.getsource(orchestrator.LeadOrchestratorAgent.run_job)
    assert "ArchivistAgent" in src
    # the parallel vendor paths are gone
    assert "_tag_v2(" not in src
    assert "_image_gen(" not in src


def test_audio_package_exports_the_provider_entrypoint():
    """The stage imports `from app.tools.audio import provider_audio_transcribe`;
    a missing export used to fail the whole transcription step silently."""
    from app.tools import audio as audio_pkg

    assert callable(audio_pkg.provider_audio_transcribe)
    assert "provider_audio_transcribe" in audio_pkg.__all__


def test_legacy_vendor_wrappers_are_gone():
    import importlib

    for mod in ("app.tools.audio_tools", "app.tools.image_tools"):
        try:
            importlib.import_module(mod)
        except ModuleNotFoundError:
            continue
        raise AssertionError(f"{mod} still exists (dead vendor wrapper)")
