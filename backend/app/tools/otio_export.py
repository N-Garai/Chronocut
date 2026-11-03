"""OpenTimelineIO interchange export.

Maps the validated EDL snapshot (tracks ``v1``/``c1``/``a1``/``m1``/``s1``)
to an OTIO timeline with per-clip metadata and caption markers, referencing
media by URI — no media files are touched, so the export stays safe on the
API container.

``opentimelineio`` is import-guarded: when the package is missing the module
degrades to a JSON-serialized OTIO-shaped document instead of raising, so the
``/jobs/{id}/edl.otio`` endpoint and the render-side export never hard-fail.
"""
import json
import logging
from typing import Any, Dict, List, Optional

from app.edl.schema import (
    TRACK_CAPTION,
    TRACK_MUSIC,
    TRACK_NARRATION,
    TRACK_SFX,
    TRACK_VIDEO,
    get_track,
)

logger = logging.getLogger("chronocut.tools.otio_export")

try:  # optional dependency; degrade to JSON when absent
    import opentimelineio as otio  # type: ignore
    from opentimelineio.schema import ExternalReference  # type: ignore

    OTIO_AVAILABLE = True
except Exception:  # pragma: no cover - exercised when the package is absent
    otio = None
    ExternalReference = None
    OTIO_AVAILABLE = False

_RATE_EPS = 1e-6


def _seconds_to_rational_time(value: float):
    """Convert seconds to an otio RationalTime at the project's rate."""
    from opentimelineio.opentime import RationalTime  # type: ignore

    return RationalTime(max(0.0, float(value)), 24.0)


def _uri_for_source(source: Dict[str, Any]) -> str:
    url = str(source.get("url") or "")
    if url:
        return url
    path = str(source.get("path") or "")
    if path:
        return "file:///" + path.replace("\\", "/").lstrip("/")
    return ""


def edl_to_otio(edl: Dict[str, Any]):
    """Return an OTIO Timeline for the EDL, or ``None`` when OTIO is missing.

    Video-track clips carry their grade/motion/transition/effects/transform
    inside ``metadata['chronocut']`` so a round-trip into professional
    editors preserves the agent's intent as data.
    """
    if not OTIO_AVAILABLE:
        return None

    project = edl.get("project") or {}
    sources = {str(s.get("id")): s for s in edl.get("sources") or []}
    rate = 24
    try:
        fps = float(project.get("fps") or 24)
        if fps > _RATE_EPS:
            rate = int(round(fps))
    except (TypeError, ValueError):
        pass

    timeline = otio.schema.Timeline(name=str(project.get("title") or "ChronoCut EDL"))

    video_track = otio.schema.Track(name="v1", kind=otio.schema.TrackKind.Video)
    captions: List[Dict[str, Any]] = []
    for cap in reversed((get_track(edl, TRACK_CAPTION) or {}).get("clips") or []):
        try:
            start = float(cap.get("start") or 0.0)
        except (TypeError, ValueError):
            continue
        captions.append({
            "start": start,
            "duration": float(cap.get("duration") or 2.0),
            "text": str(cap.get("text") or ""),
        })

    def _clip_value(clip: Dict[str, Any], key: str):
        return clip.get(key)

    v_clips = (get_track(edl, TRACK_VIDEO) or {}).get("clips") or []
    for clip in v_clips:
        try:
            start = float(clip.get("start") or 0.0)
            duration = max(_RATE_EPS, float(clip.get("duration") or 0.5))
            in_point = float(clip.get("in") or 0.0)
        except (TypeError, ValueError):
            continue
        speed = float(clip.get("speed") or 1.0) or 1.0
        source_rate = rate * speed if speed > _RATE_EPS else float(rate)
        source = sources.get(str(clip.get("source_id") or ""), {})
        target_url = _uri_for_source(source)
        ref = ExternalReference(
            target_url=target_url,
            available_range=otio.opentime.TimeRange(
                start_time=otio.opentime.RationalTime(in_point, source_rate),
                duration=otio.opentime.RationalTime(duration, source_rate),
            ),
        )
        otio_clip = otio.schema.Clip(
            name=str(clip.get("id") or ""),
            source_range=otio.opentime.TimeRange(
                start_time=otio.opentime.RationalTime(0.0, rate),
                duration=otio.opentime.RationalTime(duration, rate),
            ),
            media_reference=ref,
            metadata={
                "chronocut": {
                    "clip_id": str(clip.get("id") or ""),
                    "source_id": str(clip.get("source_id") or ""),
                    "effects": [dict(e) for e in (clip.get("effects") or [])],
                    "transform": dict(clip.get("transform") or {}),
                    "transition_in": _clip_value(clip, "transition_in"),
                    "transition_out": _clip_value(clip, "transition_out"),
                    "speed": speed,
                    "overlay_text": _clip_value(clip, "overlay_text"),
                    "name": _clip_value(clip, "name"),
                }
            },
        )
        video_track.append(otio_clip)

    timeline.tracks.append(video_track)

    for track_id, kind in (
        (TRACK_NARRATION, otio.schema.TrackKind.Audio),
        (TRACK_MUSIC, otio.schema.TrackKind.Audio),
        (TRACK_SFX, otio.schema.TrackKind.Audio),
    ):
        t_clips = (get_track(edl, track_id) or {}).get("clips") or []
        if not t_clips:
            continue
        audio_track = otio.schema.Track(name=track_id, kind=kind)
        for clip in t_clips:
            try:
                duration = max(_RATE_EPS, float(clip.get("duration") or 0.5))
                in_point = float(clip.get("in") or 0.0)
            except (TypeError, ValueError):
                continue
            source = sources.get(str(clip.get("source_id") or ""), {})
            audio_track.append(
                otio.schema.Clip(
                    name=str(clip.get("id") or ""),
                    source_range=otio.opentime.TimeRange(
                        start_time=otio.opentime.RationalTime(in_point, rate),
                        duration=otio.opentime.RationalTime(duration, rate),
                    ),
                    media_reference=ExternalReference(
                        target_url=_uri_for_source(source),
                        available_range=otio.opentime.TimeRange(
                            start_time=otio.opentime.RationalTime(in_point, rate),
                            duration=otio.opentime.RationalTime(duration, rate),
                        ),
                    ),
                    metadata={"chronocut": {
                        "gain": float(clip.get("gain") or 0.0),
                        "duck_under": bool(clip.get("duck_under")),
                    }},
                )
            )
        timeline.tracks.append(audio_track)

    # Caption markers live on the video track at their timeline times.
    for cap in captions:
        marker = otio.schema.Marker(
            name=cap["text"][:120],
            marked_range=otio.opentime.TimeRange(
                start_time=_seconds_to_rational_time(cap["start"]),
                duration=_seconds_to_rational_time(cap["duration"]),
            ),
            metadata={"chronocut": {"caption": True}},
        )
        video_track.markers.append(marker)

    timeline.metadata.update({
        "chronocut": {
            "version": str(edl.get("version") or "1.0"),
            "revision": int(edl.get("revision") or 1),
            "profile": str(project.get("profile") or "youtube_landscape"),
            "duration": float(project.get("duration") or 0.0),
        }
    })
    return timeline


def edl_to_otio_json(edl: Dict[str, Any]) -> str:
    """Serialize the EDL to an OTIO document string.

    Falls back to a plain-JSON OTIO-shaped envelope when the OTIO package or
    its adapter stack is unavailable so the endpoint always returns a payload.
    """
    timeline = edl_to_otio(edl)
    if timeline is not None:
        try:
            if hasattr(otio.adapters, "write_to_string"):
                return otio.adapters.write_to_string(timeline, "otio_json")
            return otio.adapters.etjs(timeline)  # legacy adapter name
        except Exception as e:  # adapter or version differences
            logger.warning("OTIO JSON serialization failed: %s", e)
    project = edl.get("project") or {}
    sources = [dict(s) for s in edl.get("sources") or []]
    payload: Dict[str, Any] = {
        "OTIO_SCHEMA": "Timeline.1",
        "name": str(project.get("title") or "ChronoCut EDL"),
        "metadata": {"chronocut": {
            "revision": int(edl.get("revision") or 1),
            "profile": str(project.get("profile") or ""),
            "duration": float(project.get("duration") or 0.0),
            "opentimeio_package": "missing",
        }},
        "sources": sources,
        "tracks": [dict(t) for t in edl.get("tracks") or []],
    }
    return json.dumps(payload, ensure_ascii=False)


def write_otio(edl: Dict[str, Any], out_path: str) -> Optional[str]:
    """Write an .otio JSON document next to the final render."""
    try:
        doc = edl_to_otio_json(edl)
        with open(out_path, "w", encoding="utf-8") as f:
            f.write(doc)
        return out_path
    except Exception as e:
        logger.warning("otio export failed: %s", e)
        return None
