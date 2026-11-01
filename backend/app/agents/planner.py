"""Agent planner: deterministic fast path + LLM refinement.

Fast path first — the same command-bus vocabulary as manual edits — run
locally at 0 ms for phrases like "cut", "split every 3s", "delete", "make it
cinematic", "add captions". Open-ended requests go to Muse Spark with a
strict JSON schema that emits operations from the **shared EDL vocabulary**
(a parallel agent schema is forbidden). The planner validates the base
revision, builds the server-side snapshot, dry-runs every operation, and
returns a plan-only result; the client applies it as one BatchCommand.
"""
import asyncio
import logging
import re
import time
from typing import Any, Dict, List, Optional, Tuple

from app.edl.operations import ALLOWED_OPS, OperationValidationError, plan_operations
from app.edl.schema import (
    ALLOWED_GRADES,
    ALLOWED_MOTIONS,
    ALLOWED_PROFILE_RESOLUTIONS,
    ALLOWED_TRANSITIONS,
    TRACK_CAPTION,
    TRACK_MUSIC,
    TRACK_VIDEO,
    get_track,
)
from app.services.firestore_service import JobStateService

logger = logging.getLogger("chronocut.agents.planner")

PROFILE_ALIASES = {
    "vertical": "instagram_portrait", "portrait": "instagram_portrait",
    "reel": "instagram_portrait", "reels": "instagram_portrait",
    "shorts": "instagram_portrait", "tiktok": "instagram_portrait",
    "square": "instagram_square",
    "landscape": "youtube_landscape", "16:9": "youtube_landscape",
    "9:16": "instagram_portrait", "1:1": "instagram_square",
    "1080p": "youtube_1080", "720p": "youtube_landscape",
}

# ---------------------------------------------------------------------------
# deterministic parse fast path; the core command set plus extras
# ---------------------------------------------------------------------------
_NUM = r"(\d+(?:\.\d+)?)"
_MMSS = r"(?:(\d+):(\d{1,2})(?:\.(\d+))?)"
_TIME_SNIPPETS = [
    rf"(?P<secs>{_NUM})\s*(?:s|sec(?:ond)?s?)?\b",
    rf"(?P<mm>{_MMSS})",
]


def _parse_time(raw: str) -> Optional[float]:
    m = re.fullmatch(r"\s*(\d+):(\d{1,2})(?:\.(\d+))?\s*", raw or "")
    if m:
        mins = int(m.group(1)); secs = int(m.group(2))
        frac = float("0." + m.group(3)) if m.group(3) else 0.0
        return mins * 60.0 + secs + frac
    m = re.fullmatch(r"\s*(\d+(?:\.\d+)?)\s*(?:s|sec(?:ond)?s?)?\s*", raw or "")
    if m:
        return float(m.group(1))
    return None


def _clip_at(edl: Dict[str, Any], t: float) -> Optional[str]:
    """List of clip ids overlapping t on the video track (latest start wins)."""
    best: Tuple[float, str] = (-1.0, "")
    for c in (get_track(edl, TRACK_VIDEO) or {}).get("clips") or []:
        try:
            st = float(c.get("start") or 0)
            en = st + float(c.get("duration") or 0)
        except (TypeError, ValueError):
            continue
        if st - 1e-6 <= t <= en + 1e-6 and st > best[0]:
            best = (st, str(c.get("id")))
    return best[1] or None


def _deterministic_parse(message: str, edl: Dict[str, Any], *,
                         playhead_s: float = 0.0,
                         selection: Optional[List[str]] = None) -> List[Dict[str, Any]]:
    """Regex fast path. Returns raw EDL operations (no validation yet)."""
    msg = (message or "").strip().lower()
    if not msg:
        return []
    ops: List[Dict[str, Any]] = []
    sel = list(selection or [])

    def op(name: str, **args) -> None:
        ops.append({"op": name, "args": args})

    def first_selected_or_playhead() -> Optional[str]:
        if sel:
            return sel[0]
        return _clip_at(edl, playhead_s)

    # --- delete / clips
    if re.fullmatch(r"\s*(delete|remove)(\s+(this|it|clip|the\s+(clip|selection)))?\s*", msg):
        if not sel:
            return []
        for cid in sel:
            op("delete", clip_id=cid)
        return ops

    # --- split at playhead / time / every N seconds
    m = re.fullmatch(r"\s*(?:cut|split|slice)(?:\s+(?:here|at\s+playhead(?:\s+now)?))?\s*", msg)
    if m:
        cid = first_selected_or_playhead()
        if not cid:
            return []
        op("split", clip_id=cid, **{"at": round(playhead_s, 3)})
        return ops
    m = re.match(r"\s*(?:cut|split|slice)\s+(?:every|each)\s+" + _NUM + r"\s*(?:s|sec(?:ond)?s?)?\s*$", msg)
    if m:
        sec = float(m.group(1))
        if 0.5 <= sec <= 30.0:
            op("split_every", seconds=sec)
        return ops
    m = re.match(r"\s*(?:cut|split|slice)\s+at\s+([0-9:.]+)\s*$", msg)
    if m:
        t = _parse_time(m.group(1))
        if t is None:
            return []
        cid = _clip_at(edl, t)
        if not cid:
            return []
        op("split", clip_id=cid, **{"at": round(t, 3)})
        return ops

    # --- trim left/right (preserve effects on the surviving half)
    m = re.fullmatch(r"\s*(?:trim|cut|shorten)\s+(?:from\s+)?(?:the\s+)?(left|start)\s*", msg)
    if m:
        cid = first_selected_or_playhead()
        if cid:
            op("trim", clip_id=cid, edge="start", time=round(playhead_s, 3))
        return ops
    m = re.fullmatch(r"\s*(?:trim|cut|shorten)\s+(?:until|to|at)?\s*(?:the\s+)?(?:right|end)\s*", msg)
    if m:
        cid = first_selected_or_playhead()
        if cid:
            op("trim", clip_id=cid, edge="end", time=round(playhead_s, 3))
        return ops

    # "remove the pause at 12 seconds" / "cut after 45s": trim the timeline
    m = re.match(r"\s*(?:cut|delete|remove|trim)\s+(?:everything\s+)?(?:after|before)\s+(?:the\s+)?([0-9:.]+)\s*(?:s.*)?$", msg)
    if m:
        t = _parse_time(m.group(1))
        if t is not None:
            for cid in sel or []:
                op("trim", clip_id=cid,
                   edge="start" if "before" in msg else "end", time=round(t, 3))
            if sel:
                return ops

    # --- style overrides
    g = None
    for word in re.finditer(r"\b(cinematic|nostalgic|professional|warm|teal[-_ ]?orange|b&w|black[ -]?and[ -]?white|bw|clean|neutral)\b", msg):
        raw = word.group(1).lower()
        raw = {"teal orange": "teal_orange", "teal-orange": "teal_orange",
               "black and white": "b&w", "black-and-white": "b&w"}.get(raw, raw)
        if raw in ALLOWED_GRADES:
            g = raw
            break
    if g or re.search(r"\b(grade|look|color|colour)\b", msg):
        op("set_grade_all", value=g or "cinematic")
        # "make it cinematic" is a full edit intent: cinematic grade + 0.5 s
        # crossfades + slow push (deterministic command table).
        if re.search(r"\b(cinematic|filmic|movie)\b", msg) or msg in ("make it cinematic", "cinematic"):
            op("set_transition_all", value="crossfade_0.5s")
            op("set_motion_all", value="push_in")
        return ops
    if re.search(r"\b(?:transition|crossfade|fade|dissolve)[a-z]*\b", msg):
        m = re.search(_NUM + r"\s*(?:s|sec(?:ond)?s?)?", msg)
        val = "crossfade_1s" if (m and float(m.group(1)) >= 0.9) else (
            "crossfade_0.5s" if m and float(m.group(1)) >= 0.4 else "crossfade")
        if "hard" in msg or "cut" == msg.strip():
            val = "hard_cut"
        if "fade" in msg and "cross" not in msg:
            val = "fade"
        op("set_transition_all", value=val)
        return ops
    if re.search(r"\b(?:motion|ken ?burns|push[- ]?in|pull[- ]?out|pan)\b", msg):
        val = "ken_burns_slow_zoom"
        if "push" in msg:
            val = "push_in"
        elif "pull" in msg:
            val = "pull_out"
        elif "pan left" in msg:
            val = "pan_left"
        elif "pan right" in msg:
            val = "pan_right"
        op("set_motion_all", value=val)
        return ops

    # --- speed
    m = re.search(r"(?:speed|slow[\s-]*?motion?|half\s*speed)\b.*?(" + _NUM + r")?x?\s*(?:speed)?", msg)
    if re.search(r"\b(?:speed|slow[\s-]*motion|faster|slower)\b", msg):
        val = None
        m = re.search(r"(\d+(?:\.\d+)?)\s*x\b", msg)
        if m:
            val = float(m.group(1))
        elif re.search(r"half\s*speed", msg):
            val = 0.5
        elif re.search(r"double|twice", msg):
            val = 2.0
        elif re.search(r"slow", msg):
            val = 0.5
        elif re.search(r"fast(er)?", msg):
            val = 1.5
        if val is not None and 0.25 <= val <= 4.0:
            if sel:
                for c in sel or []:
                    op("set_speed", clip_id=c, value=val)
            return ops

    # --- profile
    m = re.search(r"\b(portrait|vertical|reels?|shorts|tiktok|square|landscape|16:9|9:16|1:1|1080p|720p)\b", msg)
    if m and re.search(r"\b(profile|format|make|change|export)\b", msg) or m and "format" in msg:
        alias = m.group(1).replace(" ", "_")
        prof = PROFILE_ALIASES.get(alias, None if alias in ALLOWED_PROFILE_RESOLUTIONS else None)
        if prof:
            op("set_profile", profile=prof)
            return ops

    # --- captions
    if re.search(r"\b(remove|kill|delete) (the )?(captions|subtitles)\b", msg):
        op("ensure_captions", mode="remove")
        return ops
    if re.search(r"\b(add|generate|ensure|turn on|enable|let.?s?)\b.*\b(captions|subtitles)\b", msg):
        op("ensure_captions")
        return ops

    # --- captions with text
    m = re.match(r"\s*captio?n\s+(?:\"|['])(.+?)(?:\"|['])\s*(?:at\s+([0-9:.]+(?:s)?))?\s*$", (message or "").strip(), re.IGNORECASE)
    if m:
        t = _parse_time(m.group(2)) if m.group(2) else playhead_s
        text = m.group(1)[:240].strip()
        if text:
            op("add_caption", start=round(t or 0.0, 3), duration=2.5, text=text)
            return ops

    # --- remove silence / dead air
    if re.search(r"\b(remove|trim|cut|kill)\b.*\b(silence|silences|exact\s*air|dead\s*air|pauses|paus[ez])\b", msg):
        m = re.search(_NUM + r"\s*(?:s|sec(?:ond)?s?)?\b.*(?:noise|db)\s*(-?\d+)", msg)
        args: Dict[str, Any] = {}
        if m:
            if m.group(1):
                args["min_duration"] = float(m.group(1))
            if m.group(2):
                args["noise_db"] = float(m.group(2))
        op("remove_silence", **args)
        return ops

    # --- music
    for kind in ("city", "rain", "drone", "ambient", " uplifting", "piano"):
        if kind.strip() in msg and re.search(r"\b(music|bed|ambien(t|ce))\b", msg):
            op("replace_music", source_id=f"ambient:{kind.strip()}")
            return ops
    if re.search(r"\b(?:replace|swap|change)\b.{0,30}\b(?:music|soundtrack|bed)\b", msg):
        wav = re.search(r"(?:source|from|to|into)\s+([A-Za-z0-9_.\-]+)", msg)
        if wav:
            op("replace_music", source_id=wav.group(1))
            return ops

    return ops


# ---------------------------------------------------------------------------
# LLM plan (Muse Spark, strict schema, same vocabulary)
# ---------------------------------------------------------------------------
PLAN_SCHEMA = {
    "name": "editor_plan",
    "schema": {
        "type": "object",
        "required": ["message", "operations", "requires_confirmation", "warnings"],
        "properties": {
            "message": {"type": "string", "maxLength": 600},
            "requires_confirmation": {"type": "boolean"},
            "warnings": {"type": "array", "items": {"type": "string", "maxLength": 200}},
            "operations": {
                "type": "array", "maxItems": 200,
                "items": {
                    "type": "object",
                    "required": ["op", "args"],
                    "properties": {
                        "op": {"type": "string", "enum": sorted(ALLOWED_OPS)},
                        "args": {"type": "object"},
                        "note": {"type": "string", "maxLength": 200},
                    },
                },
            },
            "clarifying_question": {"type": "string"},
        },
    },
}


def _snapshot_text(snapshot: Dict[str, Any]) -> str:
    import json
    return json.dumps(snapshot, ensure_ascii=False, default=str)


async def plan_from_message(
    *,
    job_id: str,
    message: str,
    edl: Dict[str, Any],
    base_revision: int,
    playhead_ms: int = 0,
    selection: Optional[List[str]] = None,
    transcript: Optional[List[Dict[str, Any]]] = None,
    use_llm: bool = True,
) -> Dict[str, Any]:
    """Plan-only agent turn. Returns {message, operations, requires_confirmation,
    warnings, base_revision}; never writes the EDL. Raises on stale revision."""
    revision = int((edl.get("revision") or 1))
    if base_revision is not None and int(base_revision) != revision:
        raise OperationValidationError([
            f"base_revision {base_revision} does not match current revision {revision}"])

    from app.agents.timeline_context import build_snapshot_from_edl
    snapshot = build_snapshot_from_edl(edl, job_id=job_id, playhead_ms=playhead_ms,
                                       selection=selection, transcript=transcript)

    ops = _deterministic_parse(message, edl, playhead_s=(playhead_ms or 0) / 1000.0, selection=selection)
    warnings: List[str] = []
    plan_kind = "deterministic"
    if ops:
        plan_id = 0
        for o in ops:
            plan_id += 1
            o.setdefault("op_id", f"d{plan_id}")
    elif use_llm:
        plan_kind = "llm"
        try:
            from app.tools.llm.call import scored_llm_json
            prompt = _llm_prompt(message, snapshot,
                                 _tool_context(edl, job_id, message))
            plan = await asyncio.wait_for(
                scored_llm_json(prompt, system=_LLM_SYSTEM, agent="editor", tool="agent_plan",
                                temperature=0.4, max_output_tokens=2048,
                                require_keys=["operations", "message"]),
                timeout=60,
            )
            ops = list(plan.get("operations") or [])
            message = str(plan.get("message") or message)[:600]
            warnings = [str(w)[:200] for w in (plan.get("warnings") or [])][:5]
            question = str(plan.get("clarifying_question") or "").strip()
            if not ops and question:
                return {"message": question, "operations": [],
                        "requires_confirmation": False, "warnings": [],
                        "base_revision": revision, "plan_kind": "clarify"}
        except Exception as e:
            logger.warning(f"LLM planner failed ({type(e).__name__}); empty plan: {e}")
            return {"message": "I couldn't plan this change; try a direct command like "
                               "\"cut here\" or \"make it cinematic\".",
                    "operations": [], "requires_confirmation": False,
                    "warnings": [f"planner unavailable: {type(e).__name__}"],
                    "base_revision": revision, "plan_kind": "error"}
    else:
        plan_kind = "none"

    # EDITOR family: engaged specialists contribute parent ops (validated below
    # with everything else). No style keywords -> zero model calls.
    subagent_plan: Dict[str, Any] = {"engaged": [], "degraded": []}
    if use_llm or ops:
        try:
            from app.agents.subagents import engage_editor_specialists
            engagement = await engage_editor_specialists(
                job_id, message, _snapshot_text(snapshot)[:1800])
            subagent_plan = {"engaged": engagement.get("engaged") or [],
                             "degraded": engagement.get("degraded") or []}
            if engagement.get("ops"):
                ops = list(ops or []) + list(engagement["ops"])
            warnings.extend([str(w)[:180] for w in engagement.get("warnings") or []][:5])
        except Exception as e:
            logger.warning("editor specialists skipped (%s): %s", type(e).__name__, e)

    # Validate by dry-running everything before returning the plan.
    normalized_ops: List[Dict[str, Any]] = []
    if ops:
        try:
            normalized_ops, info = plan_operations(edl, ops)
            results = list(info.get("results") or [])
            fails = [r for r in results if not r.get("ok")]
            if plan_kind == "deterministic":
                # deterministic commands are table-driven and must plan applyable
                # ops; drop any that would not dry-run clean (e.g. captions before ASR)
                normalized_ops = [o for o, r in zip(normalized_ops, results) if r.get("ok")]
                ops = normalized_ops
            for r in fails[:10]:
                warnings.append(f"op {r.get('op')} skipped (would not apply): {r.get('note') or r.get('error')}")
            if info.get("would_fail") == info.get("total_ops") and not fails:
                warnings.append("all planned operations would be no-ops")
        except OperationValidationError as e:
            return {"message": f"Plan rejected: {e}",
                    "operations": [], "requires_confirmation": False,
                    "warnings": [str(e)[:250]], "base_revision": revision, "plan_kind": plan_kind}

    requires_confirmation = _needs_confirmation(edl, normalized_ops)
    ops_payload: List[Dict[str, Any]] = []
    for o in normalized_ops:
        entry = {"op": o["op"], "args": o.get("args") or {}}
        if o.get("note"):
            entry["note"] = o.get("note")
        ops_payload.append(entry)
    return {
        "message": message,
        "operations": ops_payload,
        "requires_confirmation": requires_confirmation,
        "warnings": warnings,
        "base_revision": revision,
        "plan_kind": plan_kind,
        "subagents": subagent_plan,
    }


def _needs_confirmation(edl: Dict[str, Any], ops: List[Dict[str, Any]]) -> bool:
    """True when the plan deletes >3 clips / >25% duration, changes profile,
    replaces music, or removes captions."""
    if not ops:
        return False
    deletes = [o for o in ops if o["op"] == "delete"]
    video_clips = len((get_track(edl, TRACK_VIDEO) or {}).get("clips") or [])
    total = float((edl.get("project") or {}).get("duration") or 0.0)
    deleted_dur = 0.0
    for o in deletes:
        cid = (o.get("args") or {}).get("clip_id")
        for t in edl.get("tracks") or []:
            for c in t.get("clips") or []:
                if str(c.get("id")) == str(cid):
                    deleted_dur += float(c.get("duration") or 0.0)
    if len(deletes) > 3 or video_clips and deletes and deleted_dur > total * 0.25:
        return True
    for o in ops:
        n = o["op"]
        if n == "set_profile":
            return True
        if n == "replace_music":
            return True
        if n == "ensure_captions" and (o.get("args") or {}).get("mode") == "remove":
            return True
    return False


_LLM_SYSTEM = (
    "You are the ChronoCut timeline editing agent. You output JSON operations in the "
    "project's EDL vocabulary only. Choose op and args carefully so every planned op "
    "validates. One op may only reference clip ids you saw in the snapshot. When the "
    "request is ambiguous about a destructive target, ask exactly one clarifying "
    "question and return an empty operations array."
)


def _tool_context(edl: Dict[str, Any], job_id: str, message: str) -> Dict[str, Any]:
    """Read-tool results that sharpen the prompt (matches + render state)."""
    try:
        from app.agents import agent_tools as tools
        matches = tools.find_clips(edl, text="")
        # narrow to clips whose label/id/transcript mentions a token of the request
        words = [w for w in str(message or "").lower().replace("\"", " ").split() if len(w) > 3]
        named: List[Dict[str, Any]] = []
        for w in words[:6]:
            hit = tools.find_clips(edl, text=w)
            if hit.get("clips"):
                named.append({"term": w, "count": hit["count"],
                              "clips": hit["clips"][:5]})
        return {"clips_total": matches.get("count", 0),
                "matches": named[:3],
                "render": tools.get_render_status(edl, job_id)}
    except Exception as e:
        logger.debug("agent read tools unavailable: %s", e)
        return {}


def _llm_prompt(message: str, snapshot: Dict[str, Any],
                tool_context: Optional[Dict[str, Any]] = None) -> str:
    import json as _json
    vocab = {
        "split": {"clip_id": "v1-01", "at": 0.0},
        "split_every": {"seconds": 3.0},
        "trim": {"clip_id": "v1-01", "edge": "start|end", "time": 8.2},
        "delete": {"clip_id": "v1-01"},
        "move": {"clip_id": "v1-01", "to": 12.0},
        "set_effect": {"clip_id": "v1-01", "effect": "grade|motion", "value": "..."},
        "set_grade_all": {"value": "clean|nostalgic|professional|cinematic|warm|teal_orange|b&w"},
        "set_transition_all": {"value": "cut|crossfade|crossfade_0.5s|crossfade_1s|fade|dissolve|dip_black|hard_cut|match_cut"},
        "set_motion_all": {"value": "hold|push_in|pull_out|pan_left|pan_right|parallax|ken_burns_slow_zoom|slowmo_0.5|speed_ramp"},
        "set_speed": {"clip_id": "v1-01", "value": 0.5},
        "add_caption": {"start": 1.0, "duration": 2.5, "text": "caption"},
        "update_caption": {"clip_id": "c1-01", "text": "new text"},
        "replace_music": {"source_id": "..."},
        "ensure_captions": {},
        "remove_silence": {"min_duration": 0.4, "noise_db": -35},
        "set_profile": {"profile": "youtube_landscape|youtube_1080|instagram_portrait|instagram_square|preview_480"},
    }
    tools_text = ("\n\nRead-tool results:\n" + _json.dumps(tool_context, default=str)
                  if tool_context else "")
    return (
        "Project snapshot (ms times; op times are in seconds):\n"
        + _snapshot_text(snapshot)
        + tools_text
        + "\n\nUser request: " + message
        + "\n\nOperations vocabulary:\n" + _json.dumps(vocab, ensure_ascii=False)
        + "\n\nRespond with JSON: {message, operations, requires_confirmation, warnings, "
          "clarifying_question?} where operations[i] = {op, args, note?}. Times are "
          "seconds rounded to three decimals."
    )


# ------------------------------------------------------------------
# runs a plan and returns the new EDL (not saved here; the routes save)
# ------------------------------------------------------------------
async def plan_and_apply(
    edl: Dict[str, Any], plan: Dict[str, Any], *,
    context: Optional[Dict[str, Any]] = None,
    strict: bool = False,
) -> Tuple[Dict[str, Any], List[Dict[str, Any]]]:
    from app.edl.operations import apply_operations
    return apply_operations(edl, plan.get("operations") or [], context=context, strict=strict)
