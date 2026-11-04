"""EDL document schema, validation, and normalization.

The EDL is stored with times in seconds rounded to three decimals. Clients use
integer milliseconds internally and convert on save (no float drift).
"""
import copy
import logging
import re
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger("chronocut.edl.schema")

EDL_VERSION = "1.0"
EDL_MAX_CLIPS = 500
EDL_MAX_TRACKS = 5
CAPTION_TEXT_MAX = 240
SPEED_MIN = 0.25
SPEED_MAX = 4.0

TRACK_VIDEO = "v1"
TRACK_CAPTION = "c1"
TRACK_NARRATION = "a1"
TRACK_MUSIC = "m1"
TRACK_SFX = "s1"
TRACK_ORDER: List[str] = [TRACK_VIDEO, TRACK_CAPTION, TRACK_NARRATION, TRACK_MUSIC, TRACK_SFX]
TRACK_TYPE: Dict[str, str] = {
    TRACK_VIDEO: "video",
    TRACK_CAPTION: "caption",
    TRACK_NARRATION: "narration",
    TRACK_MUSIC: "music",
    TRACK_SFX: "sfx",
}
# Track kind values (clip-side types) — distinct from the TRACK_* ids above.
TYPE_VIDEO = TRACK_TYPE[TRACK_VIDEO]
TYPE_CAPTION = TRACK_TYPE[TRACK_CAPTION]
TYPE_NARRATION = TRACK_TYPE[TRACK_NARRATION]
TYPE_MUSIC = TRACK_TYPE[TRACK_MUSIC]
TYPE_SFX = TRACK_TYPE[TRACK_SFX]
TYPE_MEDIA = (TYPE_VIDEO, TYPE_NARRATION, TYPE_MUSIC, TYPE_SFX)

ALLOWED_GRADES = {"clean", "nostalgic", "professional", "cinematic", "warm", "neutral", "teal_orange", "bw", "b&w"}
ALLOWED_MOTIONS = {
    "hold", "push_in", "pull_out", "pan_left", "pan_right", "parallax",
    "ken_burns_slow_zoom", "ken_burns_in", "ken_burns_out", "slowmo_0.5", "speed_ramp",
}
ALLOWED_TRANSITIONS = {
    "cut", "crossfade", "crossfade_0.5s", "crossfade_1s", "fade", "dissolve",
    "dip_black", "hard_cut", "match_cut",
}
ALLOWED_EFFECT_TYPES = {"grade", "motion"}
ALLOWED_TRACK_TYPES = set(TRACK_TYPE.values())
ALLOWED_PROFILE_RESOLUTIONS = {
    "preview_480": (854, 480, 30),
    "youtube_landscape": (1280, 720, 30),
    "youtube_1080": (1920, 1080, 30),
    "instagram_portrait": (1080, 1920, 30),
    "instagram_square": (1080, 1080, 30),
    "shorts": (1080, 1920, 30),
    "reels": (1080, 1920, 30),
    "square": (1080, 1080, 30),
}


class EDLValidationError(ValueError):
    """Raised when an EDL document fails structural validation."""

    def __init__(self, errors: List[str]):
        first = errors[0] if errors else "invalid EDL"
        self.errors = errors
        super().__init__(f"EDL validation failed ({len(errors)} error(s)): {first}")


def round3(x) -> float:
    """All EDL times are rounded to 3 decimals."""
    v = float(x)
    if v != v or v in (float("inf"), float("-inf")):
        raise EDLValidationError(["non-finite time value"])
    return round(v + 0.0, 3)


def _finite(value, field: str) -> float:
    try:
        v = float(value)
    except (TypeError, ValueError):
        raise EDLValidationError([f"{field} is not a number"])
    if v != v or v in (float("inf"), float("-inf")):
        raise EDLValidationError([f"{field} is not finite"])
    return v


def new_job_project(job_id: str, *, title: str = "", profile: str = "youtube_landscape") -> Dict[str, Any]:
    width, height, fps = ALLOWED_PROFILE_RESOLUTIONS.get(profile, (1280, 720, 30))
    now = datetime.now(timezone.utc).isoformat()
    return {
        "job_id": job_id,
        "title": title or "Untitled project",
        "created_at": now,
        "updated_at": now,
        "profile": profile,
        "fps": fps,
        "resolution": {"width": width, "height": height},
        "duration": 10.0,
    }


def _empty_edl(job_id: str, title: str = "", profile: str = "youtube_landscape") -> Dict[str, Any]:
    return {
        "version": EDL_VERSION,
        "revision": 1,
        "project": new_job_project(job_id, title=title, profile=profile),
        "sources": [],
        "tracks": [{"id": t, "type": TRACK_TYPE[t], "clips": []} for t in TRACK_ORDER],
        "metadata": {
            "created_by": "pipeline",
            "agent_plan": {},
            "review": {"status": "PENDING"},
            "render": {"preview_profile": "preview_480", "final_profile": profile},
        },
    }


def _norm_transform(t: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    t = dict(t) if isinstance(t, dict) else {}
    return {
        "scale": _finite(t.get("scale", 1.0), "transform.scale"),
        "x": _finite(t.get("x", 0.0), "transform.x"),
        "y": _finite(t.get("y", 0.0), "transform.y"),
        "crop": t.get("crop"),
    }


def _norm_effects(effects) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for e in effects or []:
        if not isinstance(e, dict):
            continue
        etype = str(e.get("type") or "").lower()
        value = e.get("value")
        if etype == "grade":
            value = str(value or "neutral").lower()
            if value not in ALLOWED_GRADES:
                continue
        elif etype == "motion":
            value = str(value or "hold").lower()
            if value not in ALLOWED_MOTIONS:
                continue
        else:
            continue
        out.append({"type": etype, "value": value})
    return out


def _norm_transition(value) -> Optional[str]:
    if not value:
        return None
    v = str(value).strip().lower()
    return v if v in ALLOWED_TRANSITIONS else None


def normalize_edl(raw: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """Coerce an EDL-like object into the canonical v1 shape.

    Fills defaults (speed 1.0, transform, gain), generates source ids when
    missing, normalizes effect/transition enums, rounds all times to 3 decimals,
    and recomputes project.duration from the tracks.
    """
    raw = copy.deepcopy(dict(raw or {}))
    if raw.get("version") != EDL_VERSION:
        # keep the requested version but mark normalized docs at 1.0
        raw["version"] = EDL_VERSION

    project = raw.get("project") or {}
    job_id = str(project.get("job_id") or uuid.uuid4())
    profile = str(project.get("profile") or "youtube_landscape")
    if profile not in ALLOWED_PROFILE_RESOLUTIONS:
        profile = "youtube_landscape"

    sources = []
    for i, s in enumerate(raw.get("sources") or []):
        if not isinstance(s, dict):
            continue
        sources.append({
            "id": str(s.get("id") or f"src-{i + 1:03d}"),
            "type": str(s.get("type") or "image"),
            "path": s.get("path") or "",
            "sha256": s.get("sha256"),
            "duration": None if s.get("duration") in (None, "") else _finite(s.get("duration"), "source.duration"),
            "width": s.get("width"),
            "height": s.get("height"),
        })
        # Optional fields consumed downstream (compiler resolve_sources /
        # external render workers): remote fetch URL, on-runner TTS text,
        # language hint, and the synth ambient kind.
        src = sources[-1]
        if s.get("url"):
            src["url"] = str(s.get("url"))
        if s.get("text"):
            src["text"] = str(s.get("text"))
        if s.get("lang"):
            src["lang"] = s.get("lang")
        if s.get("kind"):
            src["kind"] = str(s.get("kind"))
    source_ids = {s["id"] for s in sources}

    tracks_in = {t.get("id"): t for t in (raw.get("tracks") or []) if isinstance(t, dict)}
    clips_total = 0
    tracks: List[Dict[str, Any]] = []
    max_end = 0.0
    for tid in TRACK_ORDER:
        band = tracks_in.get(tid, {})
        ttype = TRACK_TYPE[tid]
        incoming = (band.get("clips") or []) if isinstance(band, dict) else []
        clips: List[Dict[str, Any]] = []
        for idx, c in enumerate(incoming):
            if not isinstance(c, dict) or clips_total >= EDL_MAX_CLIPS:
                break
            start = max(0.0, _finite(c.get("start"), "clip.start"))
            duration = _finite(c.get("duration"), "clip.duration")
            if duration <= 0:
                # Normalized EDL repairs zero/negative durations to a 1-frame sliver
                duration = 0.04
            clip: Dict[str, Any] = {"id": str(c.get("id") or new_clip_id(tid, [x["id"] for x in clips]))}
            clip["start"] = round3(start)
            clip["duration"] = round3(duration)
            if ttype == TYPE_CAPTION:
                text = str(c.get("text") or "")[:CAPTION_TEXT_MAX]
                clip["text"] = text
                style = c.get("style") or {}
                clip["style"] = {
                    "position": str(style.get("position") or "bottom"),
                    "size": int(style.get("size") or 42),
                    "color": str(style.get("color") or "#ffffff"),
                    "fade": bool(style.get("fade", True)),
                }
            if ttype in TYPE_MEDIA:
                sid = c.get("source_id")
                clip["source_id"] = sid if sid in source_ids else None
                clip["in"] = round3(max(0.0, _finite(c.get("in", 0.0), "clip.in")))
                clip["speed"] = round(min(SPEED_MAX, max(SPEED_MIN, _finite(c.get("speed", 1.0), "clip.speed"))), 3)
            if ttype == TYPE_VIDEO:
                clip["transform"] = _norm_transform(c.get("transform"))
                clip["effects"] = _norm_effects(c.get("effects"))
                clip["transition_in"] = _norm_transition(c.get("transition_in"))
                clip["transition_out"] = _norm_transition(c.get("transition_out"))
                clip["overlay_text"] = c.get("overlay_text")
                clip["name"] = c.get("name")
            if ttype in (TYPE_NARRATION, TYPE_MUSIC):
                gain = _finite(c.get("gain", 1.0 if ttype == TYPE_NARRATION else 0.22), "clip.gain")
                clip["gain"] = round(min(2.0, max(0.0, gain)), 3)
                if ttype == TYPE_MUSIC:
                    clip["duck_under"] = c.get("duck_under")
            clips.append(clip)
            clips_total += 1
            max_end = max(max_end, start + duration)
        tracks.append({"id": tid, "type": ttype, "clips": clips})

    project = new_job_project(job_id, title=str(project.get("title") or ""), profile=profile)
    project["duration"] = round3(max_end or _finite(project.get("duration", 10.0), "project.duration"))

    metadata = dict(raw.get("metadata") or {})
    metadata.setdefault("created_by", "pipeline")
    metadata.setdefault("agent_plan", {})
    metadata.setdefault("review", {"status": "PENDING"})
    metadata.setdefault(
        "render", {"preview_profile": "preview_480", "final_profile": profile}
    )

    return {
        "version": EDL_VERSION,
        "revision": max(1, int(_finite(raw.get("revision", 1), "revision"))),
        "project": project,
        "sources": sources,
        "tracks": tracks,
        "metadata": metadata,
    }


def validate_edl(edl: Dict[str, Any]) -> Dict[str, Any]:
    """Validate a normalized document and return it (unchanged) on success."""
    errors: List[str] = []
    if edl.get("version") != EDL_VERSION:
        errors.append(f"version must be {EDL_VERSION}")
    try:
        rev = int(edl.get("revision"))
    except (TypeError, ValueError):
        rev = None
    if rev is None or rev < 1:
        errors.append("revision must be a positive integer")

    project = edl.get("project") or {}
    profile = str(project.get("profile"))
    if profile not in ALLOWED_PROFILE_RESOLUTIONS:
        errors.append(f"unknown project profile: {profile}")
        profile = "youtube_landscape"
    try:
        duration = float(project.get("duration"))
    except (TypeError, ValueError):
        duration = None
    if duration is None or duration <= 0:
        errors.append("project.duration must be positive")

    sources = edl.get("sources") or []
    source_by_id: Dict[str, Tuple[str, Optional[float]]] = {}
    for s in sources:
        if isinstance(s, dict) and s.get("id"):
            source_by_id[str(s["id"])] = (
                str(s.get("type") or ""), None if s.get("duration") in (None, "") else float(s.get("duration") or 0)
            )

    clips_total = 0
    for t in edl.get("tracks") or []:
        ttype = str(t.get("type") or "")
        if ttype not in ALLOWED_TRACK_TYPES:
            errors.append(f"unknown track type: {ttype}")
            continue
        for c in t.get("clips") or []:
            clips_total += 1
            if clips_total > EDL_MAX_CLIPS:
                errors.append(f"EDL exceeds {EDL_MAX_CLIPS} clips")
                raise EDLValidationError(errors)
            cid = c.get("id")
            if not cid:
                errors.append(f"track {t.get('id')}: clip without id")
                continue
            start = _finite(c.get("start"), f"{cid}.start")
            dur = _finite(c.get("duration"), f"{cid}.duration")
            if start < 0:
                errors.append(f"{cid}.start must be >= 0")
            if dur <= 0:
                errors.append(f"{cid}.duration must be positive")
            if duration is not None and start + dur > duration + 0.001:
                errors.append(f"{cid} extends past project duration")
            if ttype == TYPE_CAPTION:
                if not str(c.get("text") or "").strip():
                    errors.append(f"{cid}: caption text is empty")
                if len(str(c.get("text") or "")) > CAPTION_TEXT_MAX:
                    errors.append(f"{cid}: caption text exceeds {CAPTION_TEXT_MAX} characters")
            else:
                sid = c.get("source_id")
                if sid not in source_by_id:
                    errors.append(f"{cid}: unknown source_id {sid}")
                else:
                    stype, sduration = source_by_id[sid]
                    if stype in ("audio", "video") and sduration is not None and dur > sduration + 0.05:
                        errors.append(f"{cid}: duration exceeds source duration ({sduration}s)")
                speed = float(c.get("speed", 1.0))
                if speed < SPEED_MIN - 1e-9 or speed > SPEED_MAX + 1e-9:
                    errors.append(f"{cid}: speed {speed} outside [{SPEED_MIN}, {SPEED_MAX}]")
            if ttype == TYPE_VIDEO:
                for e in c.get("effects") or []:
                    etype = str(e.get("type") or "")
                    value = str(e.get("value") or "")
                    if etype == "grade" and value not in ALLOWED_GRADES:
                        errors.append(f"{cid}: unknown grade '{value}'")
                    if etype == "motion" and value not in ALLOWED_MOTIONS:
                        errors.append(f"{cid}: unknown motion '{value}'")
                for key in ("transition_in", "transition_out"):
                    v = c.get(key)
                    if v is not None and str(v) not in ALLOWED_TRANSITIONS:
                        errors.append(f"{cid}: unknown {key} '{v}'")
    if errors:
        raise EDLValidationError(errors)
    return edl


_PAT_CLIP_ID = re.compile(r"[a-z][a-z0-9]*-\d{2,4}")


def valid_clip_id(cid: str) -> bool:
    return bool(_PAT_CLIP_ID.match(str(cid or "")))


def new_clip_id(track_id: str, existing_ids: List[str]) -> str:
    seq = 1
    prefix = f"{track_id}-"
    for cid in existing_ids:
        if str(cid).startswith(prefix):
            try:
                seq = max(seq, int(str(cid)[len(prefix):]) + 1)
            except ValueError:
                pass
    return f"{prefix}{seq:02d}"


def get_track(edl: Dict[str, Any], track_id: str) -> Optional[Dict[str, Any]]:
    for t in edl.get("tracks") or []:
        if t.get("id") == track_id:
            return t
    return None


def find_clip(edl: Dict[str, Any], clip_id: str) -> Tuple[Optional[Dict[str, Any]], Optional[Dict[str, Any]]]:
    """Returns (track, clip) when found."""
    for t in edl.get("tracks") or []:
        for c in t.get("clips") or []:
            if c.get("id") == clip_id:
                return t, c
    return None, None


def track_clip_ids(edl: Dict[str, Any], track_id: str) -> List[str]:
    t = get_track(edl, track_id)
    return [c.get("id") for c in (t or {}).get("clips", [])]


def edl_summary(edl: Dict[str, Any]) -> Dict[str, Any]:
    """Human-usable revision summary used for the changelog / SSE payloads."""
    v1 = get_track(edl, TRACK_VIDEO) or {"clips": []}
    grades = set()
    motions = set()
    transitions = set()
    for c in v1.get("clips", []):
        for e in c.get("effects", []):
            (grades if e.get("type") == "grade" else motions).add(e.get("value"))
        if c.get("transition_out"):
            transitions.add(c["transition_out"])
    captions = get_track(edl, TRACK_CAPTION) or {"clips": []}
    music = get_track(edl, TRACK_MUSIC) or {"clips": []}
    try:
        duration = float(edl.get("project", {}).get("duration") or 0)
    except (TypeError, ValueError):
        duration = 0.0
    return {
        "clips": len(v1.get("clips") or []),
        "duration": round3(duration),
        "grades": sorted(g for g in grades if g),
        "motions": sorted(m for m in motions if m),
        "transitions": sorted(t for t in transitions if t),
        "captions": len(captions.get("clips") or []),
        "music_source": (music.get("clips") or [{}])[0].get("source_id") if music.get("clips") else None,
    }
