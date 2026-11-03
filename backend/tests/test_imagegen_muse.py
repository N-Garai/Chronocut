"""Meta Image (muse-image-1.0) B-roll generation: gate, budget, cache, degrade.

All HTTP is mocked. The provider must be a strict no-op when off, refuse
attempts when the daily image budget is gone, reuse cached stills without a
second billed request, and degrade EDL beats back to uploaded stills on
provider-off.
"""
import base64

import pytest

from app.config import settings
from app.tools.imagegen import muse


PNG = base64.b64encode(b"\x89PNG-fake-bytes").decode()


class _Resp:
    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self._payload


@pytest.fixture()
def http_post(monkeypatch):
    """Stub requests.post; records calls. Default: success with a fake PNG."""
    calls = []

    def fake_post(url, headers=None, json=None, timeout=None):
        calls.append({"url": url, "json": json})
        return _Resp({"created": 1, "data": [{"b64_json": PNG}]})

    monkeypatch.setattr("requests.post", fake_post)
    return calls


@pytest.fixture()
def provider_on(monkeypatch, http_post):
    """Provider + key + a 2-image daily budget; returns (budget, post_calls)."""
    monkeypatch.setattr(settings, "IMAGE_GEN_PROVIDER", "muse")
    monkeypatch.setattr(settings, "MODEL_API_KEY", "model_api_key", raising=False)
    monkeypatch.setattr(settings, "META_API_KEY", None, raising=False)
    budget = muse._ImageBudget(2)
    monkeypatch.setattr(muse, "_budget", budget)
    return budget, http_post


def test_provider_off_is_a_strict_noop(http_post, monkeypatch):
    monkeypatch.setattr(settings, "IMAGE_GEN_PROVIDER", "off")
    res = muse.generate_still("a 1962 tram at dusk", "/tmp/never.png", job_id=None)
    assert res["ok"] is False
    assert res["noop"] == "provider_off"
    assert http_post == []                        # zero network calls


def test_unconfigured_credentials_noop(monkeypatch, http_post):
    monkeypatch.setattr(settings, "IMAGE_GEN_PROVIDER", "muse")
    monkeypatch.setattr(settings, "MODEL_API_KEY", None, raising=False)
    monkeypatch.setattr(settings, "META_API_KEY", None, raising=False)
    res = muse.generate_still("a courtyard", "/tmp/never.png")
    assert res["noop"] == "not_configured"
    assert http_post == []


def test_quota_exhaustion_refuses_attempts(tmp_path, http_post, monkeypatch):
    monkeypatch.setattr(settings, "IMAGE_GEN_PROVIDER", "muse")
    monkeypatch.setattr(settings, "MODEL_API_KEY", "k", raising=False)
    # one image costs one budget unit -> a 2-image day allows exactly two
    budget = muse._ImageBudget(2)
    monkeypatch.setattr(muse, "_budget", budget)
    first = muse.generate_still("a tram", str(tmp_path / "x.png"))
    assert first["ok"] is True
    assert budget.status()["used"] == 1
    second = muse.generate_still("another", str(tmp_path / "y.png"))
    assert second["ok"] is True
    assert budget.status()["used"] == 2
    later = muse.generate_still("a different still", str(tmp_path / "z.png"))
    assert later["ok"] is False
    assert later["noop"] == "quota_exhausted"
    assert len(http_post) == 2                    # no third network call
    # a budget that cannot even afford one still refuses immediately
    tiny = muse._ImageBudget(0)
    monkeypatch.setattr(muse, "_budget", tiny)
    refused = muse.generate_still("yet another", str(tmp_path / "w.png"))
    assert refused["noop"] == "quota_exhausted"
    assert len(http_post) == 2


def test_generate_still_success_writes_the_file(tmp_path, provider_on):
    budget, calls = provider_on
    out = muse.generate_still("hot summer courtyard", str(tmp_path / "still.png"))
    assert out["ok"] is True
    assert out["file"].endswith(".png")
    assert out["cached"] is False
    assert out["images"] == 1
    import os.path
    assert os.path.isfile(out["file"]) and os.path.getsize(out["file"]) > 0
    assert len(calls) == 1
    assert "/images/generations" in calls[0]["url"]
    body = calls[0]["json"]
    assert body["model"] == "muse-image-1.0"
    assert body["n"] == 1
    assert body["response_format"] == "b64_json"
    assert budget.status()["used"] == 1


def test_cached_still_reuse_costs_no_image(tmp_path, provider_on):
    budget, calls = provider_on
    out_path = str(tmp_path / "broll_00.png")
    first = muse.generate_still("the same prompt", out_path)
    assert first["ok"] and first["cached"] is False
    second = muse.generate_still("the same prompt", out_path)
    assert second["ok"] and second["cached"] is True
    assert len(calls) == 1                          # zero extra HTTP
    assert budget.status()["used"] == 1             # cache hit is free


def test_provider_error_degrades_ok_false(tmp_path, monkeypatch, provider_on):
    _, calls = provider_on

    def failing_post(*_a, **_kw):
        return _Resp({"error": {"type": "server_error", "message": "503 backend"}})

    monkeypatch.setattr("requests.post", failing_post)
    res = muse.generate_still("a monsoon street", str(tmp_path / "b.png"))
    assert res["ok"] is False
    assert "no image in response" in res["error"]
    # budget reserved for the failed attempt was released
    assert res.get("noop") is None


def _edl_with_generated_source(job_id, tmp_path):
    return {
        "version": "1.0", "revision": 1,
        "project": {"job_id": job_id, "profile": "youtube_landscape", "duration": 3.0},
        "sources": [
            {"id": "fallback-img", "type": "image", "path": "/real/fallback.png"},
            {"id": muse.generated_source_id("tram at dusk"),
             "type": "image", "path": "", "generated": True, "prompt": "tram at dusk"},
        ],
        "tracks": [{"id": "v1", "type": "video", "clips": [
            {"id": "v1-99", "source_id": muse.generated_source_id("tram at dusk"),
             "start": 0.0, "duration": 3.0, "in": 0.0}]}],
    }


def test_generated_source_id_is_prompt_stable():
    assert muse.generated_source_id("tram at dusk") == \
        muse.generated_source_id("tram at dusk")
    assert muse.generated_source_id("  tram at dusk ".strip()).startswith("gen-")
    assert muse.generated_source_id("a canal") != muse.generated_source_id("a river")


def test_ensure_generated_assets_provider_off_degrades_to_uploaded_still(
        tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "IMAGE_GEN_PROVIDER", "off")
    job_id = "j-imagegen-degrade"
    edl = _edl_with_generated_source(job_id, tmp_path)
    gen_id = muse.generated_source_id("tram at dusk")
    changed = muse.ensure_generated_assets(
        job_id, edl, str(tmp_path / "assets"))
    assert changed is True
    src = next(s for s in edl["sources"] if s["id"] == gen_id)
    assert src["path"] == ""                        # never fetched
    assert src["degraded"] == "provider_off"
    clip = edl["tracks"][0]["clips"][0]
    assert clip["source_id"] == "fallback-img"      # beat re-points to the upload


def test_ensure_generated_assets_success_fills_the_path(tmp_path, provider_on):
    budget, calls = provider_on
    job_id = "j-imagegen-ok"
    edl = _edl_with_generated_source(job_id, tmp_path)
    gen_id = muse.generated_source_id("tram at dusk")
    changed = muse.ensure_generated_assets(
        job_id, edl, str(tmp_path / "assets"))
    assert changed is True
    src = next(s for s in edl["sources"] if s["id"] == gen_id)
    assert src["path"].endswith(".png")
    import os.path
    assert os.path.isfile(src["path"])
    assert "degraded" not in src
    assert budget.status()["used"] == 1


def test_ensure_generated_assets_skips_non_generated_sources(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "IMAGE_GEN_PROVIDER", "muse")
    monkeypatch.setattr(settings, "MODEL_API_KEY", "k", raising=False)
    monkeypatch.setattr(muse, "_budget", muse._ImageBudget(10 ** 6))
    plain = {"version": "1.0", "revision": 1,
             "project": {"job_id": "j-imagegen-skip", "duration": 1.0},
             "sources": [{"id": "s1", "type": "image", "path": ""}],  # not generated
             "tracks": []}
    assert muse.ensure_generated_assets("j-imagegen-skip", plain,
                                        str(tmp_path / "a")) is False
