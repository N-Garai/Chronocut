"""Agent read tools: get_timeline/get_clip/find_clips/get_transcript/get_render_status.

Every tool answers from the same snapshot projection used by the planner —
never from raw store documents — so the agent's view of the timeline is one
consistent projection.
"""
import logging
from typing import Any, Dict, List, Optional

from app.agents.timeline_context import build_snapshot_from_edl
from app.services.firestore_service import JobStateService

logger = logging.getLogger("chronocut.agents.agent_tools")

MAX_RESULT_ROWS = 60


def find_clip(prj_edl: Dict[str, Any], clip_id: str):
    for t in prj_edl.get("tracks") or []:
        for c in t.get("clips") or []:
            if str(c.get("id")) == str(clip_id):
                return t, c
    return None, None


def get_timeline(edl: Dict[str, Any], *, job_id: str = "", playhead_ms: int = 0,
                 selection: Optional[List[str]] = None) -> Dict[str, Any]:
    return build_snapshot_from_edl(edl, job_id=job_id, playhead_ms=playhead_ms,
                                   selection=selection)


def get_clip(edl: Dict[str, Any], clip_id: str) -> Dict[str, Any]:
    track, clip = find_clip(edl, clip_id)
    if clip is None:
        return {"error": f"clip {clip_id} not found", "found": False}
    sources = {s.get("id"): s for s in edl.get("sources") or []}
    src = sources.get(str(clip.get("source_id") or ""), {})
    return {
        "found": True,
        "clip": {
            **clip,
            "track": track.get("id") if track else "",
            "source": {k: src.get(k) for k in ("id", "type", "duration", "width", "height")
                       if src.get(k) is not None},
        },
    }


def find_clips(edl: Dict[str, Any], *, text: str = "", track: str = "",
               start_s: Optional[float] = None, end_s: Optional[float] = None) -> Dict[str, Any]:
    hits: List[Dict[str, Any]] = []
    text_lower = (text or "").lower().strip()
    for t in edl.get("tracks") or []:
        tid = str(t.get("id") or "")
        if track and tid != track:
            continue
        for c in t.get("clips") or []:
            try:
                st = float(c.get("start") or 0)
                en = st + float(c.get("duration") or 0)
            except (TypeError, ValueError):
                continue
            if start_s is not None and en < float(start_s):
                continue
            if end_s is not None and st > float(end_s):
                continue
            if text_lower:
                hay = " ".join(str(x) for x in (c.get("text"), c.get("name"),
                                                c.get("id"), c.get("source_id")) if x).lower()
                if text_lower not in hay:
                    continue
            hits.append({"id": str(c.get("id")), "track": tid,
                         "start": round(st, 3), "duration": round(float(c.get("duration") or 0), 3)})
            if len(hits) >= MAX_RESULT_ROWS:
                return {"count": len(hits), "truncated": True, "clips": hits}
    return {"count": len(hits), "truncated": False, "clips": hits}


def get_transcript(edl: Dict[str, Any], *, start_s: Optional[float] = None,
                   end_s: Optional[float] = None) -> Dict[str, Any]:
    turns: List[Dict[str, Any]] = []
    meta = edl.get("metadata") or {}
    ctx = meta.get("agent_plan", {}).get("context") or meta.get("archivist") or {}
    transcript = (ctx.get("transcript") or ctx.get("turns") or [])
    if not transcript:
        return {"count": 0, "turns": []}
    for t in transcript:
        try:
            s = float(t.get("start", 0))
            e = float(t.get("end", s))
        except (TypeError, ValueError):
            continue
        if start_s is not None and e < float(start_s):
            continue
        if end_s is not None and s > float(end_s):
            continue
        turns.append({"start": round(s, 3), "end": round(e, 3),
                      "text": str(t.get("text") or "")[:300]})
        if len(turns) >= MAX_RESULT_ROWS:
            break
    return {"count": len(turns), "turns": turns}


def get_render_status(edl: Dict[str, Any], job_id: str) -> Dict[str, Any]:
    job = JobStateService.get_job(job_id) or {}
    rendered = edl.get("metadata", {}).get("render", {})
    return {
        "revision": int(edl.get("revision") or 1),
        "rendered_revision": int(job.get("rendered_revision") or rendered.get("rendered_revision") or 0),
        "stale": job.get("render_status") in (None, "STALE"),
        "render_status": job.get("render_status"),
        "render_id": job.get("render_id"),
        "profile": job.get("render_profile") or rendered.get("rendered_profile"),
        "preview_url": (job.get("editor_output", {}).get("video_urls")
                        or {}).get("primary") or job.get("last_render_url"),
        "error": (job.get("error_log") or {}).get("message"),
    }
