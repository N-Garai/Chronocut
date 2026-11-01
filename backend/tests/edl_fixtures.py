"""Shared EDL fixtures (deterministic ids and times) for the new test files."""
from typing import Any, Dict, List

from app.edl.schema import normalize_edl, validate_edl


def make_edl() -> Dict[str, Any]:
    """v1 = [0-5) photo, [5-10) photo, [10-15) photo; a1 narration 0-15;
    one caption piece. Sources are path-less (pure documents, no files)."""
    return validate_edl(normalize_edl({
        "version": "1.0",
        "revision": 3,
        "project": {
            "job_id": "11111111-2222-3333-4444-555555555555",
            "title": "Fixture",
            "profile": "youtube_landscape",
            "duration": 15.0,
        },
        "sources": [
            {"id": "src-photo-01", "type": "image", "path": "", "width": 1600, "height": 1200},
            {"id": "src-photo-02", "type": "image", "path": "", "width": 1600, "height": 1200},
            {"id": "src-photo-03", "type": "image", "path": "", "width": 1600, "height": 1200},
            {"id": "src-audio-01", "type": "audio", "path": "", "duration": 15.0},
            {"id": "ambient:RAIN", "type": "audio", "path": "", "duration": 60.0},
        ],
        "tracks": [
            {"id": "v1", "type": "video", "clips": [
                {"id": "v1-01", "source_id": "src-photo-01", "start": 0.0, "duration": 5.0,
                 "in": 0.0, "speed": 1.0, "effects": [{"type": "grade", "value": "nostalgic"}]},
                {"id": "v1-02", "source_id": "src-photo-02", "start": 5.0, "duration": 5.0, "in": 0.0},
                {"id": "v1-03", "source_id": "src-photo-03", "start": 10.0, "duration": 5.0, "in": 0.0},
            ]},
            {"id": "c1", "type": "caption", "clips": [
                {"id": "c1-01", "start": 1.0, "duration": 3.0, "text": "Kolkata, 1962",
                 "style": {"position": "bottom", "size": 42, "color": "#ffffff", "fade": True}},
            ]},
            {"id": "a1", "type": "narration", "clips": [
                {"id": "a1-01", "source_id": "src-audio-01", "start": 0.0, "duration": 15.0, "in": 0.0},
            ]},
            {"id": "m1", "type": "music", "clips": [
                {"id": "m1-01", "source_id": "ambient:RAIN", "start": 0.0, "duration": 15.0,
                 "in": 0.0, "gain": 0.22, "duck_under": "a1"},
            ]},
        ],
        "metadata": {"review": {"status": "PENDING"}},
    }))


def many_edl(n: int) -> Dict[str, Any]:
    """An EDL with ``n`` one-second video clips (snapshot-cap testing)."""
    ids = [f"src-photo-{i + 1:03d}" for i in range(n)]
    sources = [{"id": sid, "type": "image", "path": ""} for sid in ids]
    clips: List[Dict[str, Any]] = []
    for i, sid in enumerate(ids):
        clips.append({"id": f"v1-{i + 1:03d}", "source_id": sid,
                      "start": float(i), "duration": 1.0, "in": 0.0})
    return validate_edl(normalize_edl({
        "version": "1.0", "revision": 1,
        "project": {"job_id": "99999999-9999-9999-9999-999999999999",
                    "profile": "youtube_landscape", "duration": float(n)},
        "sources": sources,
        "tracks": [{"id": "v1", "type": "video", "clips": clips}],
    }))


def asr_segments() -> List[Dict[str, Any]]:
    return [
        {"start": 0.5, "end": 2.5, "text": "We arrived by the river."},
        {"start": 3.0, "end": 8.0, "text": "Mother sang the old songs every evening while the kettle boiled on the stove."},
        {"start": 9.0, "end": 12.0, "text": "Then we moved to the house on College Street."},
    ]


def silence_ranges() -> List[Dict[str, Any]]:
    return [
        {"start": 0.0, "end": 6.0},   # straddles v1-01/v1-02 boundary -> head+tail
        {"start": 12.0, "end": 15.0},
    ]
