"""Asset-bin, waveform, and low-level command endpoints.

Runs against the FastAPI app with the local JSON store: no network, no render
process, no FFmpeg required. Thumbnails must degrade to 404 rather than error.
"""
import pytest
from fastapi.testclient import TestClient

from app.api import timeline as timeline_api
from app.edl.store import load_edl, save_edl
from app.main import app
from app.services.firestore_service import JobStateService

JOB = "j-assets-command"


def _edl(duration=10.0):
    return {
        "version": "1.0",
        "revision": 1,
        "project": {"job_id": JOB, "profile": "preview_480", "duration": duration},
        "sources": [
            {"id": "src-img", "type": "image", "path": "/nonexistent/still.png"},
            {"id": "src-aud", "type": "narration", "path": "/nonexistent/voice.wav"},
        ],
        "tracks": [
            {"id": "v1", "type": "video", "clips": [
                {"id": "v1-01", "source_id": "src-img", "start": 0.0, "duration": 5.0, "in": 0.0},
                {"id": "v1-02", "source_id": "src-img", "start": 5.0, "duration": 5.0, "in": 0.0},
            ]},
            {"id": "c1", "type": "caption", "clips": []},
            {"id": "a1", "type": "narration", "clips": []},
        ],
    }


@pytest.fixture()
def client():
    JobStateService.create_job(JOB, "u-test", {"media": []})
    save_edl(JOB, _edl(), source="pipeline")
    return TestClient(app)


@pytest.fixture()
def missing_job_client():
    return TestClient(app)


# --------------------------------------------------------------------- assets
def test_asset_list_reports_kind_and_availability(client):
    r = client.get(f"/api/v1/jobs/{JOB}/assets")
    assert r.status_code == 200
    body = r.json()
    assert body["counts"] == {"total": 2, "image": 1, "video": 0, "audio": 1, "unavailable": 2}
    by_id = {a["asset_id"]: a for a in body["assets"]}
    assert by_id["src-img"]["kind"] == "image"
    assert by_id["src-img"]["available"] is False
    assert by_id["src-img"]["thumb_url"] is None
    assert by_id["src-aud"]["kind"] == "narration"
    assert by_id["src-aud"]["name"] == "voice.wav"


def test_asset_list_404s_for_an_unknown_job(missing_job_client):
    assert missing_job_client.get("/api/v1/jobs/ghost/assets").status_code == 404


def test_missing_thumbnail_degrades_to_404(client):
    assert client.get(f"/api/v1/jobs/{JOB}/assets/src-img/thumb").status_code == 404
    assert client.get(f"/api/v1/jobs/{JOB}/assets/ghost/thumb").status_code == 404


def test_thumbnail_generation_returns_none_without_a_file(tmp_path):
    from app.tools.media.thumbnails import ensure_thumbnail
    assert ensure_thumbnail(JOB, "src-img", str(tmp_path / "absent.png"), "image") is None


# ---------------------------------------------------------------- waveform
def test_waveform_404s_when_the_audio_file_is_gone(client):
    r = client.get(f"/api/v1/jobs/{JOB}/waveform")
    assert r.status_code == 404
    assert r.json()["detail"] == "Waveform unavailable"
    assert client.get(f"/api/v1/jobs/{JOB}/waveform?asset_id=src-aud").status_code == 404
    assert client.get(f"/api/v1/jobs/{JOB}/waveform?asset_id=src-img").status_code == 404


def test_waveform_404s_for_a_job_without_audio(missing_job_client):
    assert missing_job_client.get("/api/v1/jobs/ghost/waveform").status_code == 404


# ------------------------------------------------------- low-level command
def test_single_command_applies_and_bumps_the_revision(client):
    r = client.post(f"/api/v1/jobs/{JOB}/timeline/command",
                    json={"op": "split", "args": {"clip_id": "v1-01", "at": 2.5}})
    assert r.status_code == 200
    body = r.json()
    assert body["revision"] == 2
    assert body["result"]["ok"] is True
    clips = body["edl"]["tracks"][0]["clips"]
    assert [c["id"] for c in clips] == ["v1-01", "v1-03", "v1-02"]
    assert clips[0]["duration"] == 2.5 and clips[1]["duration"] == 2.5
    assert clips[1]["in"] == 2.5


def test_command_rejects_an_unknown_target(client):
    r = client.post(f"/api/v1/jobs/{JOB}/timeline/command",
                    json={"op": "split", "args": {"clip_id": "ghost", "at": 2.5}})
    assert r.status_code == 422
    assert "not found" in str(r.json()["detail"])
    # nothing was written
    _, revision = load_edl(JOB)
    assert revision == 1


def test_command_rejects_a_stale_base_revision(client):
    r = client.post(f"/api/v1/jobs/{JOB}/timeline/command",
                    json={"op": "split", "args": {"clip_id": "v1-01", "at": 2.5},
                          "base_revision": 1})
    assert r.status_code == 200
    stale = client.post(f"/api/v1/jobs/{JOB}/timeline/command",
                        json={"op": "split", "args": {"clip_id": "v1-02", "at": 7.5},
                              "base_revision": 1})
    assert stale.status_code == 409
    assert stale.json()["detail"] == {"stale_revision": 2}
    _, revision = load_edl(JOB)
    assert revision == 2


def test_command_rejects_a_batch_and_an_empty_body(client):
    assert client.post(f"/api/v1/jobs/{JOB}/timeline/command",
                       json={"operations": [{"op": "split"}, {"op": "delete"}]}).status_code == 400
    assert client.post(f"/api/v1/jobs/{JOB}/timeline/command", json={}).status_code == 400


# ------------------------------------------------------------------- renders
def test_render_queue_reaches_the_event_sink(client, monkeypatch):
    """Regression: the render route must resolve its event sink (it once raised
    NameError after the render record was created, breaking edit -> preview)."""
    monkeypatch.setattr(timeline_api, "create_render",
                        lambda *a, **k: {"render_id": "r-1", "status": "QUEUED"})
    monkeypatch.setattr(timeline_api.settings, "RENDER_DISPATCHER", "local")
    started = {}

    async def _noop(*args, **kwargs):
        started["called"] = True

    monkeypatch.setattr(timeline_api, "_run_local_render", _noop)
    r = client.post(f"/api/v1/jobs/{JOB}/render", json={"profile": "preview_480", "kind": "preview"})
    assert r.status_code == 200
    assert r.json()["render_id"] == "r-1"
    events = JobStateService.get_events(JOB)
    assert any(e.get("stage") == "render_queued" for e in events)
    assert started.get("called") is True


@pytest.fixture(autouse=True)
def _cleanup():
    """Mark the job deleted after each test; the shared local store file stays."""
    yield
    try:
        JobStateService.update_job(JOB, {"status": "DELETED"})
    except Exception:
        pass
