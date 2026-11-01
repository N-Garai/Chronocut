"""OpenTimelineIO export: maps, markers, URIs, and round-trips.

The export never touches real media (URI-only references), so the conformance
test is: build -> parse back with otio.adapters -> structural/metadata checks.
"""
import json

import opentimelineio as otio
import pytest

from app.tools import otio_export as ox
from tests.edl_fixtures import make_edl


def test_edl_maps_to_otio_timeline():
    t = ox.edl_to_otio(make_edl())
    assert isinstance(t, otio.schema.Timeline)
    assert t.name == "Fixture"
    track_names = [tr.name for tr in t.tracks]
    for tid in ("v1", "a1", "m1"):
        assert tid in track_names
    video = next(tr for tr in t.tracks if tr.name == "v1")
    assert len(video) == 3
    assert [c.name for c in video] == ["v1-01", "v1-02", "v1-03"]


def test_per_clip_metadata_carries_the_agent_intent():
    t = ox.edl_to_otio(make_edl())
    video = next(tr for tr in t.tracks if tr.name == "v1")
    meta = video[0].metadata["chronocut"]
    assert meta["clip_id"] == "v1-01"
    assert meta["source_id"] == "src-photo-01"
    assert [dict(e) for e in (meta["effects"] or [])] == [{"type": "grade", "value": "nostalgic"}]
    assert meta["speed"] == 1.0
    # audio metadata carries the mix intent (gain + ducking)
    music = next(tr for tr in t.tracks if tr.name == "m1")
    m_meta = music[0].metadata["chronocut"]
    assert m_meta["gain"] == pytest.approx(0.22)
    assert m_meta["duck_under"] is True


def test_timeline_metadata_carries_revision_and_profile():
    t = ox.edl_to_otio(make_edl())
    cm = t.metadata["chronocut"]
    assert cm["revision"] == 3
    assert cm["profile"] == "youtube_landscape"
    assert cm["duration"] == 15.0


def test_captions_export_as_markers_on_the_video_track():
    t = ox.edl_to_otio(make_edl())
    video = next(tr for tr in t.tracks if tr.name == "v1")
    assert len(video.markers) == 1
    m = video.markers[0]
    assert m.name == "Kolkata, 1962"[:120]
    assert m.metadata["chronocut"]["caption"] is True
    assert m.marked_range.start_time.value == pytest.approx(1.0)
    assert m.marked_range.duration.value == pytest.approx(3.0)


def test_media_references_are_always_external_uri_refs():
    t = ox.edl_to_otio(make_edl())
    video = next(tr for tr in t.tracks if tr.name == "v1")
    for c in video:
        assert isinstance(c.media_reference, otio.schema.ExternalReference)
    # path-less fixture sources resolve to an empty URI — no media is opened
    assert video[0].media_reference.target_url == ""
    # urland path-bearing sources map to a URI
    edl = make_edl()
    edl["sources"][0]["url"] = "https://cdn.example/x.mp4"
    t2 = ox.edl_to_otio(edl)
    video2 = next(tr for tr in t2.tracks if tr.name == "v1")
    assert video2[0].media_reference.target_url == "https://cdn.example/x.mp4"
    edl["sources"][0]["url"] = ""
    edl["sources"][0]["path"] = r"C:\media\x.mp4"
    t3 = ox.edl_to_otio(edl)
    video3 = next(tr for tr in t3.tracks if tr.name == "v1")
    assert video3[0].media_reference.target_url == "file:///C:/media/x.mp4"


def test_otio_json_round_trips_through_the_adapter():
    doc = ox.edl_to_otio_json(make_edl())
    parsed = otio.adapters.read_from_string(doc, "otio_json")
    assert isinstance(parsed, otio.schema.Timeline)
    assert parsed.name == "Fixture"
    video = next(tr for tr in parsed.tracks if tr.name == "v1")
    assert len(video) == 3
    # duration survived: 15 s project on the video track
    assert video[2].source_range.duration.value == pytest.approx(5.0)
    assert parsed.metadata["chronocut"]["revision"] == 3


def test_write_otio_writes_a_parseable_document(tmp_path):
    out_path = tmp_path / "render.otio"
    written = ox.write_otio(make_edl(), str(out_path))
    assert written == str(out_path)
    data = json.loads(out_path.read_text(encoding="utf-8"))
    assert data["OTIO_SCHEMA"].startswith("Timeline")
    parsed = otio.adapters.read_from_file(str(out_path))
    assert isinstance(parsed, otio.schema.Timeline)


def test_degrades_to_otio_shaped_envelope_without_the_package(
        monkeypatch, tmp_path):
    monkeypatch.setattr(ox, "OTIO_AVAILABLE", False)
    doc = ox.edl_to_otio_json(make_edl())
    data = json.loads(doc)
    assert data["OTIO_SCHEMA"] == "Timeline.1"
    assert data["metadata"]["chronocut"]["opentimeio_package"] == "missing"
    assert data["tracks"]
    # and the endpoint path never raises
    assert ox.write_otio(make_edl(), str(tmp_path / "still.otio")) == \
        str(tmp_path / "still.otio")
