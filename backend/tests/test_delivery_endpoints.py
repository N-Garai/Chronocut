"""Ledger + video delivery endpoints.

Regression coverage for two production incidents:
- /ledger 500: Firestore's DatetimeWithNanoseconds is not JSON serializable
  unless every ledger entry is recursively ISO-stringified.
- /video 404: a dead (0-byte / streamless) artifact was once reported as a
  successful render; the endpoint must serve healthy local files and
  redirect to the persisted object-storage copy when the ephemeral file is
  gone after an instance restart.
"""
import pytest
from datetime import datetime, timezone

from fastapi.testclient import TestClient

from app.main import app
from app.services.firestore_service import JobStateService

JOB = "j-delivery"


def _firestore_dt():
    try:
        from google.cloud.firestore_v1._helpers import DatetimeWithNanoseconds
    except Exception:
        class DatetimeWithNanoseconds(datetime):
            pass
    return DatetimeWithNanoseconds(2026, 11, 3, 12, 30, 15, 123000, tzinfo=timezone.utc)


@pytest.fixture()
def client():
    JobStateService.create_job(JOB, "u-test", {"media": []})
    return TestClient(app)


@pytest.fixture(autouse=True)
def _cleanup():
    yield
    try:
        JobStateService.update_job(JOB, {"status": "DELETED"})
    except Exception:
        pass


def _set_editor(paths=None, urls=None):
    JobStateService.update_job(JOB, {"editor_output": {
        "video_paths": paths or {}, "video_urls": urls or {},
        "primary_profile": "youtube_landscape"}})


# ------------------------------------------------------------------- ledger
def test_ledger_serializes_firestore_datetimes(client, monkeypatch):
    calls = [
        {"tool": "script", "cost_cents": 0.4, "cached": False,
         "timestamp": _firestore_dt(),
         "data": {"at": _firestore_dt(), "items": [_firestore_dt(), {"deep": _firestore_dt()}]}},
        {"tool": "tts", "cost_cents": 0.0, "cached": True, "timestamp": _firestore_dt()},
    ]
    monkeypatch.setattr(JobStateService, "get_ledger",
                        classmethod(lambda cls, job_id: calls))
    r = client.get(f"/api/v1/jobs/{JOB}/ledger")
    assert r.status_code == 200
    body = r.json()
    assert body["total_cost_cents"] == 0.4
    iso = "2026-11-03T12:30:15.123000+00:00"
    assert body["calls"][0]["timestamp"] == iso
    nested = body["calls"][0]["data"]
    assert nested["at"] == iso
    assert nested["items"][0] == iso
    assert nested["items"][1]["deep"] == iso


# -------------------------------------------------------------------- video
def test_video_404_when_nothing_was_delivered(client):
    _set_editor()
    r = client.get(f"/api/v1/jobs/{JOB}/video")
    assert r.status_code == 404
    assert r.json()["detail"] == "No video available yet"


def test_video_serves_a_healthy_local_file(client, tmp_path):
    f = tmp_path / "youtube_landscape.mp4"
    f.write_bytes(b"\x00\x00\x00\x18ftypmp42fake-payload")
    _set_editor(paths={"youtube_landscape": str(f)})
    r = client.get(f"/api/v1/jobs/{JOB}/video?profile=youtube_landscape")
    assert r.status_code == 200
    assert r.headers["accept-ranges"] == "bytes"
    assert b"fake-payload" in r.content


def test_video_redirects_to_object_storage_when_local_file_is_gone(client):
    _set_editor(paths={"youtube_landscape": "/nonexistent/gone.mp4"},
                urls={"youtube_landscape": "https://storage.example/renders/x.mp4"})
    r = client.get(f"/api/v1/jobs/{JOB}/video?profile=youtube_landscape",
                   follow_redirects=False)
    assert r.status_code == 307
    assert r.headers["location"] == "https://storage.example/renders/x.mp4"


def test_video_404_empty_local_file_without_a_url(client, tmp_path):
    f = tmp_path / "empty.mp4"
    f.write_bytes(b"")
    _set_editor(paths={"youtube_landscape": str(f)})
    r = client.get(f"/api/v1/jobs/{JOB}/video?profile=youtube_landscape")
    assert r.status_code == 404
    assert r.json()["detail"] == "Video file is empty"
