"""Timeline snapshot for the agent.

``build_timeline_snapshot`` projects the stored EDL into a compact,
capped context payload (200 clips, 200 transcript turns, 12k chars) that the
planner uses. Snapshot times are integer milliseconds; EDL operation times stay
in seconds, matching the operation contract.
"""
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
from app.services.firestore_service import JobStateService

logger = logging.getLogger("chronocut.agents.timeline_context")

MAX_SNAPSHOT_CLIPS = 200
MAX_TRANSCRIPT_TURNS = 200
SNAPSHOT_CHARS_LIMIT = 12000
_TRACK_MAP = {
    TRACK_VIDEO: "video",
    TRACK_CAPTION: "caption",
    TRACK_NARRATION: "narration",
    TRACK_MUSIC: "music",
    TRACK_SFX: "sfx",
}


def _sec_ms(v) -> int:
    try:
        return max(0, int(round(float(v or 0.0) * 1000.0)))
    except (TypeError, ValueError):
        return 0


def _clip_summary(clip: Dict[str, Any], track_type: str,
                  sources: Dict[str, Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    try:
        start = _sec_ms(clip.get("start"))
        duration = _sec_ms(clip.get("duration"))
        if (not clip.get("id")) or duration <= 0:
            return None
        done: Dict[str, Any] = {"id": str(clip["id"]), "start_ms": start, "duration_ms": duration}
        if track_type == "caption":
            done["kind"] = "caption"
            done["text"] = str(clip.get("text") or "")[:160]
            return done
        sid = clip.get("source_id")
        stu = sources.get(str(sid or ""))
        done["kind"] = str((stu or {}).get("type") or "video")
        if track_type in ("video", "narration", "music", "sfx"):
            done["in_ms"] = _sec_ms(clip.get("in"))
            if stu:
                done["label"] = str(stu.get("name") or "")[:80] or None
        if track_type == "video":
            done["transition_in"] = clip.get("transition_in")
            done["transition_out"] = clip.get("transition_out")
            done["name"] = str(clip.get("name") or "")[:80] or done.get("label")
        else:
            done["gain"] = float(clip.get("gain") or 0.0)
        return done
    except Exception:
        return None


def build_timeline_snapshot(job_id: str, edl: Optional[Dict[str, Any]],
                            playhead_ms: int = 0,
                            selection: Optional[List[str]] = None,
                            *,
                            transcript: Optional[List[Dict[str, Any]]] = None) -> Dict[str, Any]:
    """Server-side projection of the stored EDL used as planner context.

    Runs from the stored EDL plus the client's playhead and selection — the
    client never sends the whole EDL, so the agent cannot be fed a tampered
    timeline. Snapshot times are integer milliseconds; the projection is
    capped at MAX_SNAPSHOT_CLIPS around the playhead + selection plus a
    summary when the project is too large.
    """
    if not edl:
        edl = JobStateService.get_job(job_id, field="edl") or {}
    return build_snapshot_from_edl(edl or {}, job_id=job_id,
                                   playhead_ms=playhead_ms, selection=selection,
                                   transcript=transcript)


def build_snapshot_from_edl(edl: Dict[str, Any], *,
                            job_id: str = "",
                            playhead_ms: int = 0,
                            selection: Optional[List[str]] = None,
                            transcript: Optional[List[Dict[str, Any]]] = None) -> Dict[str, Any]:
    project = edl.get("project") or {}
    sources = {s.get("id"): s for s in edl.get("sources") or [] if isinstance(s, dict)}
    selection = [str(s) for s in (selection or [])]

    raw_clips: List[Dict[str, Any]] = []
    tracks = list(edl.get("tracks") or [])
    for t in tracks:
        for c in (t.get("clips") or []):
            raw_clips.append((t, c))
    raw_clips.sort(key=lambda tc: (tc[0].get("id", ""), _sec_ms(tc[1].get("start"))))

    # Keep clips around playhead/selection when over the cap.
    keep: List[Any] = []
    if len(raw_clips) > MAX_SNAPSHOT_CLIPS:
        selection_ids = set(selection)
        def _includes(tc) -> bool:
            t, c = tc
            start_ms = _sec_ms(c.get("start"))
            end_ms = start_ms + _sec_ms(c.get("duration"))
            return (str(c.get("id")) in selection_ids
                    or (playhead_ms and start_ms <= playhead_ms <= end_ms))
        keep = [tc for tc in raw_clips if _includes(tc)]
        kept_ids = {str(c.get("id")) for _, c in keep}
        for tc in raw_clips:
            if len(keep) >= MAX_SNAPSHOT_CLIPS:
                break
            if str(tc[1].get("id")) in kept_ids:
                continue
            keep.append(tc)
            kept_ids.add(str(tc[1].get("id")))
    else:
        keep = list(raw_clips)
    kept_ids = {str(c.get("id")) for _, c in keep}

    track_clips: Dict[str, List[Dict[str, Any]]] = {}
    dropped_clips = 0
    for t, c in raw_clips:
        tid = str(t.get("id") or "")
        cid = str(c.get("id") or "")
        if cid in kept_ids:
            track_clips.setdefault(tid, []).append(_clip_summary(c, t.get("type"), sources) or {"id": cid})
        else:
            dropped_clips += 1

    track_out: List[Dict[str, Any]] = []
    for t in tracks:
        tid = str(t.get("id") or "")
        track_out.append({
            "id": tid,
            "kind": _TRACK_MAP.get(tid, str(t.get("type") or "")),
            "clips": [
                bc for bc in track_clips.get(tid, [])
                if bc and (not isinstance(bc, dict) or bc.get("duration_ms", 0) >= 0)
            ],
            "summary": {"count": len(t.get("clips") or [])} if tid not in track_clips else {"count": len(t.get("clips") or [])},
        })

    turns = [
        {"start_ms": _sec_ms(s.get("start")), "end_ms": _sec_ms(s.get("end")),
         "text": str(s.get("text") or "")[:300]}
        for s in (transcript or [])[:MAX_TRANSCRIPT_TURNS]
    ]

    # What the pipeline stages already decided (compact; counts/keywords only).
    try:
        from app.agents.agent_context import summary as _ctx_summary
        stage_context = _ctx_summary(job_id) if job_id else {}
    except Exception:
        stage_context = {}

    snap = {
        "job_id": str(job_id or project.get("job_id") or ""),
        "revision": int(edl.get("revision") or 1),
        "duration_ms": _sec_ms(project.get("duration")),
        "playhead_ms": int(max(0, playhead_ms or 0)),
        "selection": selection,
        "tracks": track_out,
        "transcript": turns,
        "profile": str(project.get("profile") or "youtube_landscape"),
        "clips_total": sum(len(t.get("clips") or []) for t in tracks),
        "clips_dropped": dropped_clips,
        "stage_context": stage_context,
    }
    _trim_budget(snap, SNAPSHOT_CHARS_LIMIT)
    kept_now = sum(len(t.get("clips") or []) for t in snap["tracks"])
    snap["clips_dropped"] = int(snap.get("clips_total") or 0) - int(kept_now)
    return snap


def _trim_budget(snap: Dict[str, Any], limit: int) -> None:
    """Drop transcript lines, then the oldest/least relevant clips until under cap."""
    def _size() -> int:
        import json as _json
        return len(_json.dumps(snap, default=str))
    while _size() > limit and snap["transcript"]:
        snap["transcript"] = snap["transcript"][5:-1] if len(snap["transcript"]) > 6 else []
    if _size() <= limit:
        return
    for t in snap["tracks"]:
        while _size() > limit and len(t["clips"]) > 20:
            t["clips"] = t["clips"][len(t["clips"]) // 3:]
