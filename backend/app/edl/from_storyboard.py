"""Storyboard -> EDL conversion.

Maps the legacy storyboard produced by the pipeline onto the v1 EDL so every
job has immediate timeline data without changing the pipeline output schema:

- Each shot becomes a video-track clip (source, duration, grade, motion,
  transition).
- Narration becomes a narration-track clip per shot (``{shot_id}.mp3`` in
  ``narration_dir`` — the exact files the render path voices).
- Director text overlays become caption clips.
- The ambient bed becomes a single music-track clip.

The result is a validated EDL dict ready for ``store.save_edl``.
"""
import logging
import os
from typing import Any, Dict, List, Optional

from app.edl.schema import (
    ALLOWED_GRADES,
    ALLOWED_MOTIONS,
    ALLOWED_TRANSITIONS,
    TRACK_CAPTION,
    TRACK_MUSIC,
    TRACK_NARRATION,
    TRACK_VIDEO,
    normalize_edl,
    validate_edl,
)

logger = logging.getLogger("chronocut.edl.from_storyboard")


def _grade(value: Any) -> Optional[str]:
    v = str(value or "").strip().lower()
    return v if v in ALLOWED_GRADES else None


def _motion(value: Any) -> Optional[str]:
    v = str(value or "").strip().lower()
    if v in ("", "none"):
        return None
    return v if v in ALLOWED_MOTIONS else None


def _transition(value: Any) -> Optional[str]:
    v = str(value or "").strip().lower()
    if v in ("", "none", "fade0"):
        return None
    if v in ALLOWED_TRANSITIONS:
        return v
    # editor.py sometimes emits bare "crossfade"
    if v == "crossfade":
        return "crossfade_0.5s"
    return None


def _classify(file_path: str) -> str:
    ext = os.path.splitext(file_path or "")[1].lower()
    if ext in {".png", ".jpg", ".jpeg", ".jpe", ".jfif", ".bmp", ".gif", ".webp",
               ".tiff", ".tif", ".svg", ".avif", ".heic", ".heif", ".jp2", ".tga"}:
        return "image"
    if ext in {".mp4", ".m4v", ".mov", ".webm", ".mkv", ".avi", ".wmv", ".flv",
               ".f4v", ".3gp", ".3g2", ".ts", ".mts", ".m2ts", ".ogv", ".mpg",
               ".mpeg", ".vob", ".asf", ".divx"}:
        return "video"
    if ext in {".mp3", ".wav", ".m4a", ".aac", ".ogg", ".oga", ".flac", ".opus",
               ".wma", ".aiff", ".aif", ".au", ".amr", ".mka"}:
        return "audio"
    return "image"


def build_edl_from_storyboard(
    storyboard: List[Dict[str, Any]],
    *,
    job_id: str,
    profile: str = "youtube_landscape",
    narration_dir: Optional[str] = None,
    background_music: Optional[str] = None,
    ambient_kind: Optional[str] = None,
    title: str = "",
    created_by: str = "pipeline",
) -> Dict[str, Any]:
    """Convert a composed storyboard into a normalized EDL v1 document."""
    raw = {
        "version": "1.0",
        "revision": 1,
        "project": {"job_id": job_id, "title": title, "profile": profile},
        "sources": [],
        "tracks": [],
        "metadata": {
            "created_by": created_by,
            "agent_plan": {"editor": "EditorAgent"},
            "review": {"status": "PENDING"},
            "render": {"preview_profile": "preview_480", "final_profile": profile},
        },
    }
    sources: List[Dict[str, Any]] = []
    video_clips: List[Dict[str, Any]] = []
    caption_clips: List[Dict[str, Any]] = []
    narration_clips: List[Dict[str, Any]] = []
    seen: Dict[str, str] = {}
    cursor = 0.0

    n = len(storyboard or [])
    for i, shot in enumerate(storyboard or []):
        vs = shot.get("visual_source") or {}
        file_path = vs.get("file")
        url = (vs.get("url") or "").strip() or None
        if file_path and not os.path.exists(file_path):
            file_path = None
        if not file_path and not url:
            continue

        key = file_path or url
        # remote URLs can repeat across shots; reuse the source entry
        src_id = seen.get(key)
        if src_id:
            source = next(s for s in sources if s["id"] == src_id)
        else:
            src_no = len(sources) + 1
            src_id = f"src-{src_no:03d}"
            seen[key] = src_id
            source = {
                "id": src_id,
                "type": _classify(file_path or (url or "")),
                "path": file_path or "",
                "url": url,
                "sha256": None,
                "duration": None,
                "width": None,
                "height": None,
            }
            if url and not file_path:
                source["remote"] = True
            sources.append(source)

        duration = max(0.5, float(shot.get("duration_seconds", 3.0) or 3.0))
        effects: List[Dict[str, str]] = []
        grade = _grade(shot.get("color_grade"))
        if grade:
            effects.append({"type": "grade", "value": grade})
        motion = _motion(shot.get("motion"))
        motion = motion or _motion(vs.get("effect"))
        if motion:
            effects.append({"type": "motion", "value": motion})
        transition_out = None
        if i < n - 1:
            transition_out = _transition(shot.get("transition")) or _transition(vs.get("transition"))
        video_clips.append({
            "id": f"v1-{i + 1:02d}",
            "source_id": src_id,
            "start": round(cursor, 3),
            "duration": round(duration, 3),
            "in": 0.0,
            "speed": 1.0,
            "transform": {"scale": 1.0, "x": 0.0, "y": 0.0, "crop": None},
            "effects": effects,
            "transition_in": None,
            "transition_out": transition_out,
            "overlay_text": shot.get("overlay_text"),
            "name": f"shot-{shot.get('shot_id', i + 1)}",
        })

        # Director text overlay -> caption clip at the start of the shot.
        overlay = str(shot.get("overlay_text") or "").strip()
        if overlay:
            caption_clips.append({
                "id": f"c1-{len(caption_clips) + 1:02d}",
                "start": round(cursor, 3),
                "duration": round(min(duration, 6.0), 3),
                "text": overlay[:240],
                "style": {"position": "bottom", "size": 42, "color": "#ffffff", "fade": True},
            })

        # Narration: one clip per shot. When the render-path mp3 exists (TTS ran
        # on this machine) the clip is file-backed; otherwise the clip carries
        # the shot's audio_text so an external render worker (which has the TTS
        # model) can voice it — a 512MB API container must not run torch.
        if narration_dir:
            narr_path = os.path.join(narration_dir, f"{shot.get('shot_id', i + 1)}.mp3")
            narr_text = str(shot.get("audio_text") or "").strip()
            if os.path.exists(narr_path) and os.path.getsize(narr_path) > 0:
                narr_src_id = f"src-narr-{shot.get('shot_id', i + 1)}"
                if not any(s["id"] == narr_src_id for s in sources):
                    sources.append({
                        "id": narr_src_id,
                        "type": "audio",
                        "path": narr_path,
                        "sha256": None,
                        "duration": None,
                        "width": None,
                        "height": None,
                    })
                narration_clips.append({
                    "id": f"a1-{len(narration_clips) + 1:02d}",
                    "source_id": narr_src_id,
                    "start": round(cursor, 3),
                    "duration": round(duration, 3),
                    "in": 0.0,
                    "speed": 1.0,
                    "gain": 1.0,
                })
            elif narr_text:
                narr_src_id = f"src-narr-{shot.get('shot_id', i + 1)}"
                if not any(s["id"] == narr_src_id for s in sources):
                    sources.append({
                        "id": narr_src_id,
                        "type": "narration_text",
                        "path": "",
                        "url": "",
                        "text": narr_text[:800],
                        "lang": str(shot.get("language") or "") or None,
                        "sha256": None,
                        "duration": None,
                        "width": None,
                        "height": None,
                    })
                narration_clips.append({
                    "id": f"a1-{len(narration_clips) + 1:02d}",
                    "source_id": narr_src_id,
                    "start": round(cursor, 3),
                    "duration": round(duration, 3),
                    "in": 0.0,
                    "speed": 1.0,
                    "gain": 1.0,
                })

        cursor += duration

    total = round(cursor, 3) or 10.0

    if background_music and os.path.exists(background_music):
        sources.append({
            "id": "src-music-01",
            "type": "audio",
            "path": background_music,
            "sha256": None,
            "duration": None,
            "width": None,
            "height": None,
        })
    elif ambient_kind and ambient_kind not in ("", "none"):
        sources.append({
            "id": "src-music-01",
            "type": "synth",
            "kind": str(ambient_kind),
            "path": "",
            "duration": total,
        })
    music_clips = []
    if any(s["id"] == "src-music-01" for s in sources):
        music_clips = [{
            "id": "m1-01",
            "source_id": "src-music-01",
            "start": 0.0,
            "duration": total,
            "in": 0.0,
            "speed": 1.0,
            "gain": 0.22,
            "duck_under": "a1",
        }]

    raw["sources"] = sources
    raw["tracks"] = [
        {"id": "v1", "type": "video", "clips": video_clips},
        {"id": "c1", "type": "caption", "clips": caption_clips},
        {"id": "a1", "type": "narration", "clips": narration_clips},
        {"id": "m1", "type": "music", "clips": music_clips},
        {"id": "s1", "type": "sfx", "clips": []},
    ]
    raw["project"]["duration"] = total

    try:
        edl = normalize_edl(raw)
        return validate_edl(edl)
    except Exception as e:
        logger.error("from_storyboard produced an invalid EDL for %s: %s", job_id, e)
        raise
