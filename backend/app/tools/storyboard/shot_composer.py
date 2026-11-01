import logging
import os
import time
import asyncio
from typing import Optional, Dict, Any, List, Callable

logger = logging.getLogger("chronocut.tools.storyboard")

__all__ = ["compose_shots"]

from app.config import settings

# Allow-lists so a bad/partial director plan can NEVER inject an invalid
# value that breaks the render. Anything unrecognized is ignored and the
# hardcoded mapping is kept (guaranteed no-regression fallback).
ALLOWED_CAMERA_MOVES = {
    None, "hold", "push_in", "pull_out", "pan_left", "pan_right",
    "parallax", "slowmo_0.5", "speed_ramp",
}
ALLOWED_TRANSITIONS = {
    "cut", "crossfade_0.5s", "crossfade_1s", "fade", "dissolve",
    "dip_black", "hard_cut", "match_cut",
}
ALLOWED_FILTER_PRESETS = {"clean", "nostalgic", "professional", "cinematic", "b&w"}

_FILTER_PRESET_TO_GRADE = {
    "clean": None,
    "nostalgic": "nostalgic",
    "professional": "professional",
    "cinematic": "cinematic",
    "b&w": "bw",
}


def _emit_sub(job_id, sub_agent, parent_sub, progress, message):
    """Append a hierarchical sub-agent event (indented under its parent in the UI)."""
    if not job_id:
        return
    try:
        from app.services.firestore_service import JobStateService
        JobStateService.append_event(job_id, {
            "stage": "director",
            "progress_percent": progress,
            "message": message,
            "sub_agent": sub_agent,
            "parent_sub": parent_sub,
        })
    except Exception:
        pass


def _effect_for_tone(tone: str) -> str:
    # E2: neutral used to map to "crossfade_0.5s" (a transition, not an effect) →
    # no-op in the renderer. Map it to a real cinematic effect instead.
    return {
        "nostalgic": "ken_burns_slow_zoom",
        "emotional": "ken_burns_slow_zoom",
        "professional": "ken_burns_fast_pan",
        "reflective": "ken_burns_slow_zoom",
        "neutral": "ken_burns_slow_zoom",
    }.get(tone, "ken_burns_slow_zoom")


def _color_grade_for_tone(tone: str) -> Optional[str]:
    if tone in ("nostalgic", "emotional"):
        return "nostalgic"
    if tone in ("professional",):
        return "professional"
    return None


def _motion_for_emotion(emotion: str) -> Optional[str]:
    # D2: extend camera moves beyond only climax/tension so the director (or the
    # deterministic map) can choose push_in/pull_out/pan/parallax per beat.
    return {
        "climax": "push_in",
        "tension": "slowmo_0.5",
        "release": "pull_out",
        "setup": "pan_right",
        "reflective": None,
        "neutral": None,
    }.get(emotion, None)


def _make_shot(shot_id, seg_id, visual_source, duration, text, tone, emotion, i0):
    """Build a base shot dict (transition + motion + grade + caption fields)."""
    return {
        "shot_id": shot_id,
        "script_segment_id": seg_id,
        "visual_source": visual_source,
        "duration_seconds": duration,
        "transition": "cut" if i0 else "crossfade_0.5s",
        "motion": _motion_for_emotion(emotion),
        "color_grade": _color_grade_for_tone(tone),
        "overlay_text": None,
        "audio_text": text,
        "voiceover": True,
        "sfx": None,
        "sound_bed": None,
    }


def _build_query(seg: Dict[str, Any], tone: str, shot_keywords: List[str], prompt: str = "") -> str:
    """Compose a concrete, short Pexels/Pixabay query.

    The screenwriter may echo the whole prompt as a "visual", which is a terrible
    search term. We therefore: (1) prefer the clean LLM-derived ``shot_keywords``
    (subjects like 'city lights night'), (2) only keep per-segment ``suggested_visuals``
    that contain real content words (drop prompt echoes and pure descriptors like
    'wide shot'), and (3) cap the length so the query stays specific.
    """
    from app.tools.footage.keyword_gen import _is_content, _dedupe

    cleaned = []
    for v in (seg.get("suggested_visuals") or []):
        v = str(v or "").strip()
        if not v:
            continue
        # Drop terms that just echo the whole prompt.
        if prompt and v.lower().startswith(prompt[:18].lower()) and len(prompt) > 18:
            continue
        if _is_content(v):
            cleaned.append(v)
    pool = list(shot_keywords or []) + cleaned
    if not pool and seg.get("text"):
        t = str(seg["text"]).strip()
        if prompt and not t.lower().startswith(prompt[:18].lower()):
            pool = [t]
    pool = _dedupe(pool)
    parts = pool[:3]
    if not parts:
        parts = [prompt] if prompt else ["documentary"]
    q = " ".join(parts)
    return q[:60].strip() or "documentary"


def _apply_director_override(shot: Dict[str, Any], override: Optional[Dict[str, Any]]) -> None:
    """Let the LLM director (or reference_brief-derived plan) override a
    shot's look. Every value is validated against an allow-list; invalid entries
    are dropped so the hardcoded mapping remains the guaranteed fallback."""
    if not override:
        return
    cam = override.get("camera_move")
    if cam in ALLOWED_CAMERA_MOVES:
        shot["motion"] = cam
    tr = override.get("transition")
    if tr in ALLOWED_TRANSITIONS:
        shot["transition"] = tr
    preset = override.get("filter_preset")
    if preset in ALLOWED_FILTER_PRESETS:
        shot["color_grade"] = _FILTER_PRESET_TO_GRADE.get(preset)
    txt = override.get("text_overlay")
    if isinstance(txt, str) and txt.strip():
        shot["overlay_text"] = txt.strip()[:80]
    if isinstance(override.get("voiceover"), bool):
        shot["voiceover"] = override["voiceover"]
    if isinstance(override.get("sound_bed"), str):
        shot["sound_bed"] = override["sound_bed"]


def _scale_to_length(storyboard: List[Dict[str, Any]], length_seconds: Optional[float]) -> None:
    """Honor the user-requested length. Rescale every shot's duration so the
    render can't collapse to a 5s clip when 30s was requested.

    Shots flagged ``_fixed_duration`` (uploaded photos/videos whose native length
    must be preserved) are never rescaled — only the flexible (B-roll) shots are
    stretched/compressed to fill whatever time the fixed media doesn't cover.
    """
    if not length_seconds or length_seconds <= 0:
        for s in storyboard:
            if not s.get("_fixed_duration"):
                s["duration_seconds"] = max(float(s.get("duration_seconds", 5.0)), 2.0)
        return
    fixed = [s for s in storyboard if s.get("_fixed_duration")]
    flexible = [s for s in storyboard if not s.get("_fixed_duration")]
    fixed_total = sum(float(s.get("duration_seconds", 0)) for s in fixed)
    if not flexible:
        return
    remaining = length_seconds - fixed_total
    if remaining <= 0:
        return
    raw = [max(float(s.get("duration_seconds", 5.0)), 0.1) for s in flexible]
    total_raw = sum(raw)
    if total_raw <= 0:
        return
    scale = remaining / total_raw
    running = 0.0
    for i, s in enumerate(flexible):
        if i == len(flexible) - 1:
            dur = remaining - running
        else:
            dur = max(2.0, round(raw[i] * scale, 1))
            running += dur
        s["duration_seconds"] = round(dur, 1)


async def compose_shots(
    script_segments: List[Dict[str, Any]],
    photo_files: List[str],
    profile: str = "youtube_landscape",
    job_id: Optional[str] = None,
    reference_brief: Optional[Dict[str, Any]] = None,
    director_plan: Optional[Dict[Any, Dict[str, Any]]] = None,
    length_seconds: Optional[float] = None,
    cancel_check: Optional[Any] = None,
    user_prompt: Optional[str] = None,
    search_keywords: Optional[List[str]] = None,
    video_clips: Optional[List[Dict[str, Any]]] = None,
) -> List[Dict[str, Any]]:
    """Assemble the final shot list.

    Uploaded media (photos + videos) form the *backbone* of the cut. Each
    uploaded clip becomes a shot carrying the narration of the script segments
    mapped to it, so a 'from_media' job is literally built from the upload. B-roll
    is only used to fill any remaining length the uploaded media doesn't cover.
    """
    from app.agents.sub_agents.broll_sourcing_specialist import BRollSourcingSpecialist

    storyboard = []
    photo_idx = 0
    video_idx = 0
    n = len(script_segments)
    used_urls: set = set()

    # Wall-clock budget for B-roll resolution. Slow or failing stock providers
    # must not be able to stall the whole job; after the budget expires the
    # remaining shots fall straight to matte.
    footage_deadline = time.monotonic() + float(settings.FOOTAGE_BUDGET_SECONDS or 360)

    def _footage_budget_left() -> bool:
        return time.monotonic() < footage_deadline

    def _matte_source() -> Dict[str, Any]:
        return {"type": "color_matte", "url": None, "file": None,
                "effect": "none", "transition": "crossfade_0.5s"}

    # Free-tier OOM guard: cap total shots when there is no uploaded media.
    if not photo_files and not video_clips and n > 6:
        n = 6
        script_segments = script_segments[:6]

    # Build the ordered media backbone (photos then videos) from the upload.
    media = []
    for p in (photo_files or []):
        media.append({"kind": "photo", "file": p, "duration": 5.0, "fixed": False})
    for vc in (video_clips or []):
        vdur = float(vc.get("duration") or 0.0) or 5.0
        media.append({
            "kind": "video", "file": vc.get("file"),
            "duration": round(min(max(vdur, 1.0), 60.0), 1), "fixed": True,
        })

    if media:
        n_media = len(media)
        for m_idx, m in enumerate(media):
            if cancel_check and cancel_check():
                raise asyncio.CancelledError("compose_shots cancelled")
            # Distribute script segments across the media shots (contiguous slices)
            # so the narration from the upload is preserved across its clips.
            if n_media == 1:
                segs_for = script_segments
            else:
                start = (m_idx * n) // n_media
                end = ((m_idx + 1) * n) // n_media
                segs_for = script_segments[start:end]
            seg0 = segs_for[0] if segs_for else {
                "segment_id": m_idx + 1, "tone": "reflective",
                "emotion": "reflective", "text": ""}
            seg_id = seg0.get("segment_id", m_idx + 1)
            text = " ".join(str(s.get("text", "")) for s in segs_for).strip()
            tone = seg0.get("tone", "reflective")
            emotion = seg0.get("emotion", "reflective")
            duration = m["duration"]
            if m["kind"] == "photo":
                visual_source = {"type": "user_photo", "url": None, "file": m["file"],
                                "effect": _effect_for_tone(tone), "transition": "crossfade_0.5s"}
                _emit_sub(job_id, "VisualMatcherSpecialist", "StoryboardComposerAgent", 60,
                          f"Matched user photo → beat {seg_id}.")
            else:
                visual_source = {"type": "user_video", "url": None, "file": m["file"],
                                "effect": "none", "transition": "crossfade_0.5s"}
                _emit_sub(job_id, "VisualMatcherSpecialist", "StoryboardComposerAgent", 60,
                          f"Matched user video → beat {seg_id}.")
            shot = _make_shot(len(storyboard) + 1, seg_id, visual_source, duration,
                              text, tone, emotion, m_idx == 0)
            if m.get("fixed"):
                shot["_fixed_duration"] = True
            override = (director_plan or {}).get(seg_id) or (director_plan or {}).get(str(seg_id))
            _apply_director_override(shot, override)
            if shot.get("overlay_text") is None and settings.ENABLE_CAPTIONS and text:
                caption = " ".join(str(text).split()[:8]).strip()
                if caption:
                    shot["overlay_text"] = caption + ("…" if len(str(text).split()) > 8 else "")
            storyboard.append(shot)

        # If the uploaded media already covers the requested length, keep ONLY the
        # media (drop filler B-roll) so the cut stays true to the upload. Fit it to
        # the requested length by trimming the final shot if it would run long.
        media_total = sum(float(s.get("duration_seconds", 0)) for s in storyboard)
        if (length_seconds or 0) <= 0 or media_total >= (length_seconds or media_total) * 0.8:
            if length_seconds and media_total > float(length_seconds) and storyboard:
                overflow = media_total - float(length_seconds)
                last = storyboard[-1]
                trimmed = float(last.get("duration_seconds", 0)) - overflow
                if trimmed >= 2.0:
                    last["duration_seconds"] = round(trimmed, 1)
                    last.pop("_fixed_duration", None)
                # else: leave slightly over requested (acceptable; keeps all footage)
        else:
            # Media is shorter than requested: fill the remainder with B-roll.
            remaining = (length_seconds or media_total) - media_total
            used_seg_ids = {s.get("script_segment_id") for s in storyboard}
            for seg_idx, seg in enumerate(script_segments):
                if remaining <= 2:
                    break
                if seg.get("segment_id") in used_seg_ids:
                    continue
                if cancel_check and cancel_check():
                    raise asyncio.CancelledError("compose_shots cancelled")
                bid = len(storyboard) + 1
                bseg_id = seg.get("segment_id", bid)
                btone = seg.get("tone", "reflective")
                bemotion = seg.get("emotion", "reflective")
                bduration = round(float(seg.get("audio_end", 0)) - float(seg.get("audio_start", 0)), 1) or 5.0
                shot_keywords = [search_keywords[seg_idx % len(search_keywords)]] if search_keywords else []
                query = _build_query(seg, btone, shot_keywords, user_prompt or "")
                if _footage_budget_left():
                    resolved = await BRollSourcingSpecialist().resolve(
                        query, duration=bduration, job_id=job_id, profile=profile, avoid_urls=used_urls
                    )
                    if resolved.get("url"):
                        used_urls.add(resolved["url"])
                    _emit_sub(job_id, "BRollSourcingSpecialist", "StoryboardComposerAgent", 62,
                              f"Resolved B-roll for '{query[:48]}' → {resolved.get('source', 'unknown')}.")
                else:
                    resolved = {}
                    _emit_sub(job_id, "BRollSourcingSpecialist", "StoryboardComposerAgent", 62,
                              f"Footage budget exhausted — B-roll for '{query[:40]}' falls back to matte.")
                vs = {"type": resolved.get("type", "color_matte"), "url": resolved.get("url"),
                      "file": resolved.get("file"), "effect": resolved.get("effect", "none"),
                      "transition": "crossfade_0.5s"}
                shot = _make_shot(bid, bseg_id, vs, bduration, seg.get("text", ""), btone, bemotion, False)
                override = (director_plan or {}).get(bseg_id) or (director_plan or {}).get(str(bseg_id))
                _apply_director_override(shot, override)
                if shot.get("overlay_text") is None and settings.ENABLE_CAPTIONS and seg.get("text"):
                    caption = " ".join(str(seg.get("text", "")).split()[:8]).strip()
                    if caption:
                        shot["overlay_text"] = caption + ("…" if len(str(seg.get("text", "")).split()) > 8 else "")
                storyboard.append(shot)
                remaining -= float(shot["duration_seconds"])
    else:
        for i, seg in enumerate(script_segments):
            # Cooperative cancellation — stop LLM/CPU usage immediately if the
            # job was cancelled (this is the long B-roll resolution loop).
            if cancel_check and cancel_check():
                raise asyncio.CancelledError("compose_shots cancelled")
            seg_id = seg.get("segment_id", i + 1)
            text = seg.get("text", "")
            tone = seg.get("tone", "reflective")
            emotion = seg.get("emotion", "reflective")
            duration = round(float(seg.get("audio_end", 0)) - float(seg.get("audio_start", 0)), 1) or 5.0
            shot_keywords = []
            if search_keywords:
                shot_keywords = [search_keywords[i % len(search_keywords)]]
            query = _build_query(seg, tone, shot_keywords, user_prompt or "")
            visuals = [str(v).strip() for v in (seg.get("suggested_visuals") or []) if v and str(v).strip()]

            if photo_files and photo_idx < len(photo_files):
                file_path = photo_files[photo_idx]
                photo_idx += 1
                _emit_sub(job_id, "VisualMatcherSpecialist", "StoryboardComposerAgent", 60, f"Matched user photo → beat {seg_id}.")
                visual_source = {
                    "type": "user_photo", "url": None, "file": file_path,
                    "effect": _effect_for_tone(tone), "transition": "crossfade_0.5s",
                }
            else:
                if _footage_budget_left():
                    resolved = await BRollSourcingSpecialist().resolve(
                        query, duration=duration, job_id=job_id, profile=profile, avoid_urls=used_urls
                    )
                    src = resolved.get("source", "unknown")
                    if resolved.get("url"):
                        used_urls.add(resolved["url"])
                    _emit_sub(job_id, "BRollSourcingSpecialist", "StoryboardComposerAgent", 62,
                              f"Resolved B-roll for '{query[:48]}' → {src}.")
                else:
                    resolved = {}
                    _emit_sub(job_id, "BRollSourcingSpecialist", "StoryboardComposerAgent", 62,
                              f"Footage budget exhausted — B-roll for '{query[:40]}' falls back to matte.")
                visual_source = {
                    "type": resolved.get("type", "color_matte"),
                    "url": resolved.get("url"),
                    "file": resolved.get("file"),
                    "effect": resolved.get("effect", "none"),
                    "transition": "crossfade_0.5s",
                }

            transition = "cut" if i == 0 else "crossfade_0.5s"
            shot = {
                "shot_id": i + 1,
                "script_segment_id": seg_id,
                "visual_source": visual_source,
                "duration_seconds": max(duration, 2.0),
                "transition": transition,
                "motion": _motion_for_emotion(emotion),
                "color_grade": _color_grade_for_tone(tone),
                "overlay_text": None,
                "audio_text": text,
                "voiceover": seg.get("voiceover", True),
                "sfx": seg.get("sfx") or None,
                "sound_bed": seg.get("sound_bed") or None,
            }

            # Apply director overrides (validated; hardcoded values are fallback).
            override = (director_plan or {}).get(seg_id) or (director_plan or {}).get(str(seg_id))
            _apply_director_override(shot, override)

            # I2: if no explicit overlay was set and captions are enabled, burn a
            # short caption derived from the narration (first ~8 words) so the video
            # is accessible without changing the look when captions are off.
            if shot.get("overlay_text") is None and settings.ENABLE_CAPTIONS and text:
                caption = " ".join(str(text).split()[:8]).strip()
                if caption:
                    shot["overlay_text"] = caption + ("…" if len(str(text).split()) > 8 else "")

            # Redundant-narration guard. If the voiceover would merely restate
            # the visual query (e.g. "rainy neon city" spoken over rainy-neon footage),
            # drop the voiceover so the visuals can breathe and we don't double-say.
            if shot.get("voiceover") is not False and text and visuals:
                lowered = text.lower()
                if any(str(v).strip().lower()[:12] in lowered for v in visuals if v):
                    shot["voiceover"] = False

            storyboard.append(shot)

    _scale_to_length(storyboard, length_seconds)
    return storyboard
