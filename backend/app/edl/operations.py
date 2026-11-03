"""EDL operations: the single command vocabulary.

Every user edit and every agent plan is expressed as one of these validated
operations. Operations are applied to a normalized EDL and return a NEW
document; the store bumps ``revision`` and appends a changelog entry.

Two ops are *macros* that expand server-side when the caller supplies context:

- ``remove_silence``  context: ``silence_ranges`` (from audio analysis),
- ``ensure_captions`` context: ``asr_segments`` (from ASR turns).

Unknown operations are rejected (never silently ignored). An invalid op raises
:class:`OperationValidationError`; batch application collects per-op results
instead of aborting the whole plan.
"""
import copy
import logging
from typing import Any, Dict, List, Optional, Tuple

from app.edl.schema import (
    ALLOWED_GRADES,
    ALLOWED_MOTIONS,
    ALLOWED_TRANSITIONS,
    CAPTION_TEXT_MAX,
    EDLValidationError,
    find_clip,
    new_clip_id,
    round3,
    SPEED_MAX,
    SPEED_MIN,
    TRACK_CAPTION,
    TRACK_MUSIC,
    TRACK_ORDER,
    TRACK_SFX,
    TRACK_VIDEO,
)

logger = logging.getLogger("chronocut.edl.operations")

TRACK_IDS = set(TRACK_ORDER)
MAX_OPS = 200
MIN_CLIP_DURATION = 0.05
SPLIT_EVERY_MIN = 0.5
SPLIT_EVERY_MAX = 30.0
CAPTION_PIECE_MAX = 80       # ensure_captions splits turns longer than this
CAPTION_PIECE_MAX_SECONDS = 8.0

ALLOWED_OPS = {
    "split", "split_every", "trim", "delete", "move",
    "set_effect", "set_grade_all", "set_transition_all", "set_motion_all",
    "set_speed", "add_caption", "update_caption", "replace_music",
    "ensure_captions", "remove_silence", "set_profile", "insert_broll",
}

REQUIRED_ARGS = {
    "split": ("clip_id",),
    "split_every": ("seconds",),
    "trim": ("clip_id", "edge", "time"),
    "delete": ("clip_id",),
    "move": ("clip_id", "to"),
    "set_effect": ("clip_id", "effect", "value"),
    "set_grade_all": ("value",),
    "set_transition_all": ("value",),
    "set_motion_all": ("value",),
    "set_speed": ("clip_id", "value"),
    "add_caption": ("start", "duration", "text"),
    "update_caption": ("clip_id", "text"),
    "replace_music": ("source_id",),
    "ensure_captions": (),
    "remove_silence": (),
    "set_profile": ("profile",),
    "insert_broll": ("at_ms",),  # source_id: required for stock b-roll, auto-derived for generated
}


class OperationValidationError(ValueError):
    """Raised when an operation is malformed or references missing entities."""

    def __init__(self, errors: List[str]):
        first = errors[0] if errors else "invalid operation"
        self.errors = errors
        super().__init__(first)


# --------------------------------------------------------------------------
# normalization / validation of an operation batch
# --------------------------------------------------------------------------
def normalize_operation(raw: Any, index: int = 0) -> Dict[str, Any]:
    if not isinstance(raw, dict):
        raise OperationValidationError([f"op {index}: must be a JSON object"])
    op = str(raw.get("op") or "").strip()
    if op not in ALLOWED_OPS:
        raise OperationValidationError([f"op {index}: unknown op '{op or '(empty)'}'"])
    args = raw.get("args") if isinstance(raw.get("args"), dict) else raw
    for key in REQUIRED_ARGS[op]:
        if key not in args:
            raise OperationValidationError([f"op {index}: '{op}' missing arg '{key}'"])
    out: Dict[str, Any] = {
        "op": op,
        "args": copy.deepcopy({k: v for k, v in args.items() if k != "args"}),
    }
    if raw.get("op_id"):
        out["op_id"] = str(raw["op_id"])[:64]
    if raw.get("note"):
        out["note"] = str(raw["note"])[:200]
    return out


def validate_operations(ops: Any, *, max_ops: int = MAX_OPS) -> List[Dict[str, Any]]:
    """Validate a batch and return the normalized list. Raises on the first bad op."""
    ops_list = _coerce_batch(ops)
    if len(ops_list) > max_ops:
        raise OperationValidationError([f"batch exceeds {max_ops} operations"])
    for i, op in enumerate(ops_list):
        normalize_operation(op, index=i)
    return ops_list


def _coerce_batch(ops: Any) -> List[Dict[str, Any]]:
    """Accepts a bare list, {"ops": [...]}, or a single op object."""
    if isinstance(ops, dict):
        if isinstance(ops.get("ops"), list):
            return ops["ops"]
        return [ops]
    if isinstance(ops, list):
        return ops
    raise OperationValidationError(["operation batch must be a list or {'ops': [...]}"])


# --------------------------------------------------------------------------
# application
# --------------------------------------------------------------------------
def apply_operations(
    edl: Dict[str, Any],
    batch: Any,
    *,
    context: Optional[Dict[str, Any]] = None,
    strict: bool = False,
) -> Tuple[Dict[str, Any], List[Dict[str, Any]]]:
    """Apply a batch, returning (new_edl, per-op results).

    With ``strict=False`` (the default) invalid ops are skipped and reported in
    ``results``; with ``strict=True`` any invalid op raises. ``context`` carries
    macro data: ``silence_ranges``, ``asr_segments``.
    """
    ops_list = _coerce_batch(batch)
    normalized = [normalize_operation(o, index=i) for i, o in enumerate(ops_list)]
    edl = copy.deepcopy(edl)
    state = _EDLState(edl, context or {})
    results = state.apply(normalized, strict=strict)
    _recompute_duration(edl)
    return edl, results


def apply_operation(edl: Dict[str, Any], op: Dict[str, Any], *, context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Apply one operation. Raises on an invalid op (never silent)."""
    new_edl, _ = apply_operations(edl, [op], context=context, strict=True)
    return new_edl


def plan_operations(
    edl: Dict[str, Any],
    batch: Any,
    *,
    context: Optional[Dict[str, Any]] = None,
) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    """Dry-run a batch against an EDL without committing it.

    Agents use this before committing so the proposed plan is known-safe.
    Returns (normalized_ops, plan_info).
    """
    ops_list = validate_operations(batch)
    new_edl, results = apply_operations(edl, ops_list, context=context)
    ok = sum(1 for r in results if r.get("ok"))
    info = {
        "total_ops": len(ops_list),
        "would_succeed": ok,
        "would_fail": len(ops_list) - ok,
        "clips_after": sum(len(t.get("clips") or []) for t in (new_edl.get("tracks") or [])),
        "duration_after": round3(float(new_edl.get("project", {}).get("duration", 0.0))),
        "results": results,
    }
    return ops_list, info


def _recompute_duration(edl: Dict[str, Any]) -> None:
    end = 0.0
    for t in edl.get("tracks", []):
        for c in t.get("clips") or []:
            try:
                end = max(end, float(c.get("start", 0)) + float(c.get("duration", 0)))
            except (TypeError, ValueError):
                continue
    project = edl.setdefault("project", {})
    try:
        declared = float(project.get("duration", 0.0) or 0.0)
    except (TypeError, ValueError):
        declared = 0.0
    project["duration"] = round3(max(end, declared))


# --------------------------------------------------------------------------
# internal mutation engine (never exported)
# --------------------------------------------------------------------------
class _EDLState:
    """Validated mutation engine for one EDL document (mutates in place)."""

    def __init__(self, edl: Dict[str, Any], context: Dict[str, Any]):
        self.edl = edl
        self.ctx = context

    def apply(self, ops: List[Dict[str, Any]], *, strict: bool = False) -> List[Dict[str, Any]]:
        results: List[Dict[str, Any]] = []
        for op in ops:
            name = op["op"]
            args = op.get("args") or {}
            try:
                affected = self._apply_op(name, args)
                results.append({"op": name, "op_id": op.get("op_id"), "ok": True,
                                "note": op.get("note"), "affected": affected})
            except (OperationValidationError, EDLValidationError, KeyError, ValueError, TypeError) as e:
                if strict:
                    raise
                msg = _err_message(e)
                logger.warning("EDL op %s failed: %s", name, msg)
                results.append({"op": name, "op_id": op.get("op_id"), "ok": False, "error": msg})
        return results

    # ------------------------------------------------------------- dispatch
    def _apply_op(self, name: str, a: Dict[str, Any]) -> List[str]:
        if name == "split":
            first, second = self.op_split(a)
            return [first, second]
        if name == "split_every":
            return self.op_split_every(a)
        if name == "trim":
            return [self.op_trim(a)]
        if name == "delete":
            return self.op_delete(a)
        if name == "move":
            return [self.op_move(a)]
        if name == "set_effect":
            return [self.op_set_effect(a)]
        if name == "set_grade_all":
            return self.op_all_effect("grade", a, ALLOWED_GRADES)
        if name == "set_motion_all":
            return self.op_all_effect("motion", a, ALLOWED_MOTIONS)
        if name == "set_transition_all":
            return self.op_set_transition_all(a)
        if name == "set_speed":
            return [self.op_set_speed(a)]
        if name == "add_caption":
            return [self.op_add_caption(a)]
        if name == "update_caption":
            return [self.op_update_caption(a)]
        if name == "replace_music":
            return self.op_replace_music(a)
        if name == "ensure_captions":
            return self.op_ensure_captions(a)
        if name == "remove_silence":
            return self.op_remove_silence(a)
        if name == "set_profile":
            self.op_set_profile(a)
            return []
        if name == "insert_broll":
            first = self.op_insert_broll(a)
            return [first]
        raise OperationValidationError([f"unknown op '{name}'"])  # pragma: no cover

    # ------------------------------------------------------------ media ops
    def op_split(self, a: Dict[str, Any]) -> Tuple[str, str]:
        clip_id = str(a.get("clip_id") or "")
        track, clip = self._find(clip_id)
        if not clip:
            raise OperationValidationError([f"split: clip not found '{clip_id}'"])
        dur = float(clip["duration"])
        at = a.get("at")
        at = float(at) if at is not None else float(clip["start"]) + dur / 2.0
        cut = at - float(clip["start"])  # 'at' is absolute project time (9.4)
        cut = min(max(cut, 0.06), dur - 0.06)
        right = copy.deepcopy(clip)
        right["id"] = new_clip_id(track["id"], [c.get("id") for c in track["clips"]])
        right["start"] = round3(float(clip["start"]) + cut)
        right["duration"] = round3(dur - cut)
        right["transition_in"] = None  # split distributes the transition
        if "in" in clip:
            right["in"] = round3(float(clip.get("in", 0.0)) + cut * float(clip.get("speed", 1.0)))
        clip["duration"] = round3(cut)
        clip["transition_out"] = None
        track["clips"].insert(track["clips"].index(clip) + 1, right)
        return clip["id"], right["id"]

    def op_split_every(self, a: Dict[str, Any]) -> List[str]:
        seconds = _num(a.get("seconds"), "seconds")
        if not (SPLIT_EVERY_MIN <= seconds <= SPLIT_EVERY_MAX):
            raise OperationValidationError(
                [f"split_every: seconds must be in [{SPLIT_EVERY_MIN}, {SPLIT_EVERY_MAX}]"])
        video = self._track(TRACK_VIDEO)
        cuts: List[float] = []
        for c in video.get("clips") or []:
            k = 1
            while float(c["start"]) + k * seconds < float(c["start"]) + float(c["duration"]) - 0.06:
                cuts.append(float(c["start"]) + k * seconds)
                k += 1
        result_ids: List[str] = []
        for at in cuts:
            targets = [c for c in video["clips"]
                       if float(c["start"]) + 0.06 < at < float(c["start"]) + float(c["duration"]) - 0.06]
            if not targets:
                continue
            first, second = self.op_split({"clip_id": targets[0]["id"], "at": round3(at)})
            result_ids.extend([first, second])
        if not result_ids:
            raise OperationValidationError(["split_every: no clip long enough to split"])
        return result_ids

    def op_trim(self, a: Dict[str, Any]) -> str:
        clip_id = str(a.get("clip_id") or "")
        track, clip = self._find(clip_id)
        if not clip:
            raise OperationValidationError([f"trim: clip not found '{clip_id}'"])
        edge = a.get("edge")
        if edge not in ("start", "end"):
            raise OperationValidationError(["trim: edge must be 'start' or 'end'"])
        time = _num(a.get("time"), "time")
        speed = float(clip.get("speed", 1.0)) if "in" in clip else 1.0
        src = self._source(clip.get("source_id"))
        prev_end = self._prev_end(track, clip)
        next_start = self._next_start(track, clip)
        if edge == "start":
            # trim head: start moves right, in moves right, duration shrinks.
            new_start = min(max(time, prev_end),
                            float(clip["start"]) + float(clip["duration"]) - MIN_CLIP_DURATION)
            new_start = min(max(new_start, 0.0), prev_end if new_start < prev_end else new_start)
            if new_start <= float(clip["start"]) + 1e-3:
                raise OperationValidationError(["trim: no head room left"])
            delta = new_start - float(clip["start"])
            if "in" in clip:
                old_in = float(clip.get("in", 0.0))
                new_in = old_in + delta * speed
                if src is not None and new_in < 0.0:
                    new_in = 0.0
                    delta = (new_in - old_in) / speed
                    if delta <= 1e-3:
                        raise OperationValidationError(["trim: no head room left (source at 0)"])
            clip["start"] = round3(new_start)
            if "in" in clip:
                clip["in"] = round3(float(clip.get("in", 0.0)) + delta * speed)
            clip["duration"] = round3(float(clip["duration"]) - delta)
        else:
            # trim tail: only the out-point moves.
            new_end = max(time, float(clip["start"]) + MIN_CLIP_DURATION)
            if next_start is not None:
                new_end = min(new_end, next_start)
            if src is not None and src.get("duration"):
                # available source seconds from `in`, expressed in project time
                remaining = (float(src["duration"]) - float(clip.get("in", 0.0))) / speed
                new_end = min(new_end, float(clip["start"]) + remaining)
            new_dur = round3(new_end - float(clip["start"]))
            if new_dur < MIN_CLIP_DURATION:
                raise OperationValidationError(["trim: no tail room left"])
            if abs(new_dur - float(clip["duration"])) <= 1e-3:
                raise OperationValidationError(["trim: no tail room left"])
            clip["duration"] = new_dur
        _recompute_duration(self.edl)
        return clip["id"]

    def op_delete(self, a: Dict[str, Any]) -> List[str]:
        clip_id = str(a.get("clip_id") or "")
        track, clip = self._find(clip_id)
        if not clip:
            raise OperationValidationError([f"delete: clip not found '{clip_id}'"])
        ripple = a.get("ripple")
        ripple = True if ripple is None else bool(ripple)
        removed_dur = float(clip["duration"])
        removed_start = float(clip["start"])
        track["clips"] = [c for c in track["clips"] if c.get("id") != clip_id]
        if ripple:
            for c in track["clips"]:
                if float(c["start"]) >= removed_start:
                    c["start"] = round3(float(c["start"]) - removed_dur)
        _recompute_duration(self.edl)
        return [clip_id]

    def op_move(self, a: Dict[str, Any]) -> str:
        clip_id = str(a.get("clip_id") or "")
        track, clip = self._find(clip_id)
        if not clip:
            raise OperationValidationError([f"move: clip not found '{clip_id}'"])
        to = _num(a.get("to"), "to")
        if to < 0:
            to = 0.0
        project_dur = float(self.edl.get("project", {}).get("duration", 10.0) or 10.0)
        clip["start"] = round3(min(to, max(project_dur, 0.0)))
        track["clips"].sort(key=lambda c: (float(c["start"]), str(c.get("id", ""))))
        return clip["id"]

    # ------------------------------------------------------------- style ops
    def op_set_effect(self, a: Dict[str, Any]) -> str:
        clip_id = str(a.get("clip_id") or "")
        track, clip = self._find(clip_id)
        if not clip:
            raise OperationValidationError([f"set_effect: clip not found '{clip_id}'"])
        if track["id"] != TRACK_VIDEO:
            raise OperationValidationError([f"set_effect: '{clip_id}' is not on the video track"])
        effect_type = str(a.get("effect") or "")
        value = str(a.get("value") or "").strip()
        members = {"grade": ALLOWED_GRADES, "motion": ALLOWED_MOTIONS}.get(effect_type)
        if members is None:
            raise OperationValidationError(["set_effect: effect must be 'grade' or 'motion'"])
        if value not in members:
            raise OperationValidationError([f"set_effect: unknown {effect_type} '{value}'"])
        effects = [e for e in clip.get("effects", []) if e.get("type") != effect_type]
        effects.append({"type": effect_type, "value": value})
        clip["effects"] = effects
        return clip["id"]

    def op_all_effect(self, effect_type: str, a: Dict[str, Any], members: set) -> List[str]:
        value = str(a.get("value") or "")
        if value not in members:
            raise OperationValidationError([f"set_{effect_type}_all: unknown {effect_type} '{value}'"])
        clips = self._track(TRACK_VIDEO).get("clips") or []
        if not clips:
            raise OperationValidationError([f"set_{effect_type}_all: no video clips"])
        ids: List[str] = []
        for c in clips:
            effects = [e for e in c.get("effects", []) if e.get("type") != effect_type]
            effects.append({"type": effect_type, "value": value})
            c["effects"] = effects
            ids.append(c["id"])
        return ids

    def op_set_transition_all(self, a: Dict[str, Any]) -> List[str]:
        value = str(a.get("value") or "")
        if value not in ALLOWED_TRANSITIONS:
            raise OperationValidationError([f"set_transition_all: unknown transition '{value}'"])
        clips = self._track(TRACK_VIDEO).get("clips") or []
        if not clips:
            raise OperationValidationError(["set_transition_all: no video clips"])
        ids: List[str] = []
        for i, c in enumerate(clips):
            # the last clip has nothing to transition into
            c["transition_out"] = None if i == len(clips) - 1 else value
            ids.append(c["id"])
        return ids

    def op_set_speed(self, a: Dict[str, Any]) -> str:
        clip_id = str(a.get("clip_id") or "")
        track, clip = self._find(clip_id)
        if not clip:
            raise OperationValidationError([f"set_speed: clip not found '{clip_id}'"])
        if "speed" not in clip:
            raise OperationValidationError(["set_speed: clip does not support speed"])
        speed = _num(a.get("value"), "value")
        if not (SPEED_MIN <= speed <= SPEED_MAX):
            raise OperationValidationError([f"set_speed: speed must be in [{SPEED_MIN}, {SPEED_MAX}]"])
        old_speed = float(clip.get("speed", 1.0))
        new_dur = round3(float(clip["duration"]) * old_speed / speed)
        if new_dur < MIN_CLIP_DURATION:
            raise OperationValidationError(["set_speed: result too short"])
        clip["speed"] = round3(speed)
        clip["duration"] = new_dur
        _recompute_duration(self.edl)
        return clip["id"]

    # ------------------------------------------------------------ caption ops
    def op_add_caption(self, a: Dict[str, Any]) -> str:
        text = str(a.get("text") or "").strip()
        if not text:
            raise OperationValidationError(["add_caption: text is required"])
        if len(text) > CAPTION_TEXT_MAX:
            text = text[:CAPTION_TEXT_MAX]
        start = max(0.0, _num(a.get("start"), "start"))
        duration = _num(a.get("duration"), "duration")
        duration = max(0.3, min(duration, 60.0))
        style_in = a.get("style") if isinstance(a.get("style"), dict) else {}
        track = self._track(TRACK_CAPTION)
        clip = {
            "id": new_clip_id(TRACK_CAPTION, [c.get("id") for c in track["clips"]]),
            "start": round3(start),
            "duration": round3(duration),
            "text": text,
            "style": {
                "position": "top" if style_in.get("position") == "top" else "bottom",
                "size": _int_in(style_in.get("size", 42), 12, 120),
                "color": str(style_in.get("color", "#ffffff") or "#ffffff")[:9],
                "fade": bool(style_in.get("fade", True)),
            },
        }
        track["clips"].append(clip)
        track["clips"].sort(key=lambda c: (float(c["start"]), str(c.get("id", ""))))
        _recompute_duration(self.edl)
        return clip["id"]

    def op_update_caption(self, a: Dict[str, Any]) -> str:
        clip_id = str(a.get("clip_id") or "")
        track, clip = self._find(clip_id)
        if not clip:
            raise OperationValidationError([f"update_caption: clip not found '{clip_id}'"])
        if track["id"] != TRACK_CAPTION:
            raise OperationValidationError([f"update_caption: '{clip_id}' is not a caption"])
        text = str(a.get("text") or "").strip()
        if not text:
            raise OperationValidationError(["update_caption: text cannot be empty"])
        clip["text"] = text[:CAPTION_TEXT_MAX]
        if isinstance(a.get("style"), dict):
            st = a["style"]
            style = clip.setdefault("style", {})
            if "position" in st:
                style["position"] = "top" if st.get("position") == "top" else "bottom"
            if "size" in st:
                style["size"] = _int_in(st.get("size"), 12, 120)
            if "color" in st and st.get("color"):
                style["color"] = str(st.get("color"))[:9]
            if "fade" in st:
                style["fade"] = bool(st.get("fade"))
        return clip["id"]

    # ------------------------------------------------------------ video ops
    def op_insert_broll(self, a: Dict[str, Any]) -> str:
        """Insert a B-roll clip on v1 at ``at_ms`` and ripple the rest of the
        video track right by the inserted duration. Used by agent plans (the
        scene_caster specialist) and the generated-still path.

        Generated mode: ``kind: "generated"`` + ``prompt`` — the still does not
        exist yet, so the op registers a *pending* image source (stable id
        derived from the prompt hash for reuse across revisions, empty path)
        and the carrier materializes it after the apply; provider off or
        failure degrades the beat to an uploaded still (see
        ``tools/imagegen/muse.ensure_generated_assets``). The op itself
        never waits on the network, so applies stay fast."""
        kind = str(a.get("kind") or "").strip().lower()
        prompt = str(a.get("prompt") or "").strip()
        source_id = str(a.get("source_id") or "")
        if kind == "generated":
            if not prompt:
                raise OperationValidationError(["insert_broll: generated source requires a prompt"])
            if source_id in ("", "none", "generated"):
                from app.tools.imagegen.muse import generated_source_id
                source_id = generated_source_id(prompt)
            if self._source(source_id) is None:
                self.edl.setdefault("sources", []).append({
                    "id": source_id, "type": "image", "path": "",
                    "generated": True, "prompt": prompt[:400],
                })
            a = dict(a)
            a["source_id"] = source_id
            src = self._source(source_id)
        else:
            src = self._source(source_id)
            if src is None:
                raise OperationValidationError([f"insert_broll: unknown source '{source_id}'"])
            kind = str(src.get("type") or "footage").strip().lower()
        if src.get("type") not in (None, "image", "video"):
            raise OperationValidationError(["insert_broll: source must be an image or video"])
        at = _num(a.get("at_ms"), "at_ms") / 1000.0
        if at < 0:
            raise OperationValidationError(["insert_broll: at_ms must be >= 0"])
        total = _num(self.edl.get("project", {}).get("duration", 10.0), "project.duration")
        at = round3(min(at, total))
        src_dur = src.get("duration")
        if a.get("duration_s") in (None, ""):
            duration = 3.0 if src_dur in (None, "") else min(float(src_dur), 12.0)
        else:
            duration = _num(a.get("duration_s"), "duration_s")
        duration = round3(min(max(0.3, duration), 60.0))
        kind = str(a.get("kind") or src.get("type") or "footage").strip().lower()
        motion = str(a.get("motion") or "").strip().lower()
        if motion and motion not in ALLOWED_MOTIONS:
            raise OperationValidationError([f"insert_broll: unknown motion '{motion}'"])
        if not motion:
            motion = "ken_burns_slow_zoom" if kind in ("still", "generated") or src.get("type") == "image" else "hold"
        track = self._track(TRACK_VIDEO)
        existing_ids = [c.get("id") for c in track["clips"]]
        clip = {
            "id": new_clip_id(TRACK_VIDEO, existing_ids),
            "source_id": source_id,
            "start": at,
            "duration": duration,
            "in": 0.0,
            "speed": 1.0,
            "transform": {"scale": 1.0, "x": 0.0, "y": 0.0, "crop": None},
            "effects": [{"type": "motion", "value": motion}],
            "transition_in": None,
            "transition_out": None,
            "name": f"B-roll ({kind})",
        }
        if isinstance(a.get("transition_in"), str) and a["transition_in"] in ALLOWED_TRANSITIONS:
            clip["transition_in"] = a["transition_in"]
        # ripple: downstream v1 clips (and their cut facts) move right as one
        for c in track["clips"]:
            if float(c["start"]) >= at - 1e-9:
                c["start"] = round3(float(c["start"]) + duration)
        track["clips"].append(clip)
        track["clips"].sort(key=lambda c: (float(c["start"]), str(c.get("id", ""))))
        _recompute_duration(self.edl)
        return clip["id"]

    # ------------------------------------------------------------ audio ops
    def op_replace_music(self, a: Dict[str, Any]) -> List[str]:
        source_id = str(a.get("source_id") or "")
        src = self._source(source_id)
        if src is None:
            raise OperationValidationError([f"replace_music: unknown source '{source_id}'"])
        if src.get("type") not in (None, "audio"):
            raise OperationValidationError(["replace_music: source must be audio"])
        gain = _num(a.get("gain", 0.22), "gain")
        gain = round3(max(0.0, min(2.0, gain)))
        track = self._track(TRACK_MUSIC)
        old_ids = [c["id"] for c in track["clips"]]
        src_dur = src.get("duration")
        total = float(self.edl.get("project", {}).get("duration", 10.0) or 10.0)
        if src_dur:
            total = min(total, float(src_dur))
        if total <= 0.05:
            raise OperationValidationError(["replace_music: no fitting music length"])
        track["clips"] = [{
            "id": new_clip_id(TRACK_MUSIC, []),
            "source_id": source_id,
            "start": 0.0,
            "duration": round3(total),
            "in": 0.0,
            "speed": 1.0,
            "gain": gain,
            "duck_under": "a1",
        }]
        _recompute_duration(self.edl)
        return old_ids + [track["clips"][0]["id"]]

    def op_ensure_captions(self, a: Dict[str, Any]) -> List[str]:
        segments = self.ctx.get("asr_segments")
        if not segments:
            raise OperationValidationError(["ensure_captions: no ASR segments available for this job"])
        track = self._track(TRACK_CAPTION)
        replaced = [c["id"] for c in track["clips"]]
        track["clips"] = []
        created: List[str] = []
        for turn in segments:
            start = _turn_num(turn, "start")
            end = _turn_num(turn, "end")
            text = str(turn.get("text") or "").strip()
            dur = end - start if end > start else _turn_num(turn, "duration")
            if not text or dur <= 0:
                continue
            pieces = _split_caption_text(text, CAPTION_PIECE_MAX)
            piece_dur = min(dur / max(1, len(pieces)), CAPTION_PIECE_MAX_SECONDS)
            offset = 0.0
            for piece in pieces:
                if piece_dur < 0.3:
                    piece_dur = min(dur - offset, 5.0)
                if piece_dur < 0.3:
                    break
                clip = {
                    "id": new_clip_id(TRACK_CAPTION, [c.get("id") for c in track["clips"]]),
                    "start": round3(start + offset),
                    "duration": round3(piece_dur),
                    "text": piece,
                    "style": {"position": "bottom", "size": 42, "color": "#ffffff", "fade": True},
                }
                track["clips"].append(clip)
                created.append(clip["id"])
                offset += piece_dur
        track["clips"].sort(key=lambda c: (float(c["start"]), str(c.get("id", ""))))
        _recompute_duration(self.edl)
        return replaced + created

    def op_remove_silence(self, a: Dict[str, Any]) -> List[str]:
        ranges = self.ctx.get("silence_ranges")
        if not ranges:
            raise OperationValidationError(
                ["remove_silence: no silence ranges available (audio analysis missing)"])
        cleaned = []
        for r in ranges:
            try:
                s, e = float(r.get("start", 0)), float(r.get("end", 0))
            except (TypeError, ValueError, AttributeError):
                continue
            if e - s >= _num(a.get("min_duration", 0.2), "min_duration") and e > s:
                cleaned.append((s, e))
        if not cleaned:
            raise OperationValidationError(["remove_silence: no qualifying silence ranges"])
        removed: List[str] = []
        for s, e in cleaned:
            for t in self.edl["tracks"]:
                # sfx stays put (natural walla during gaps is fine) — cut the rest
                if t["id"] == TRACK_SFX:
                    continue
                self._cut_range(t, s, e, removed)
        _recompute_duration(self.edl)
        if not removed:
            raise OperationValidationError(["remove_silence: nothing was cut"])
        # A global cut shortens the timeline: drop the declared duration down to
        # the last remaining content end (grow is never allowed here).
        ends = [float(c["start"]) + float(c["duration"])
                for t in self.edl["tracks"] for c in (t.get("clips") or [])]
        declared = float(self.edl.get("project", {}).get("duration", 10.0) or 10.0)
        content_end = max(ends) if ends else 0.04
        self.edl["project"]["duration"] = round3(min(declared, max(content_end, 0.04)))
        return removed

    # ------------------------------------------------------------ profile ops
    def op_set_profile(self, a: Dict[str, Any]) -> None:
        from app.edl.schema import ALLOWED_PROFILE_RESOLUTIONS
        profile = str(a.get("profile") or "")
        if profile not in ALLOWED_PROFILE_RESOLUTIONS:
            raise OperationValidationError([f"set_profile: unknown profile '{profile}'"])
        w, h, fps = ALLOWED_PROFILE_RESOLUTIONS[profile]
        self.edl["project"]["profile"] = profile
        self.edl["project"]["resolution"] = {"width": w, "height": h}
        self.edl["project"]["fps"] = fps

    # ------------------------------------------------------------- internals
    def _cut_range(self, track: Dict[str, Any], s: float, e: float, removed: List[str]) -> None:
        """Remove [s, e) from one track: trim/shell overlapping clips, then pull
        everything to the right of `e` left by (e - s). Used only by
        remove_silence (the one global-ripple command)."""
        keep: List[Dict[str, Any]] = []
        shift = e - s
        for c in track["clips"]:
            cs, cd = float(c["start"]), float(c["duration"])
            ce = cs + cd
            if ce <= s:
                keep.append(c)
            elif cs >= e:
                c["start"] = round3(cs - shift)
                keep.append(c)
            else:
                head = s - cs
                tail = ce - e
                if head > MIN_CLIP_DURATION:
                    head_clip = copy.deepcopy(c)
                    head_clip["duration"] = round3(head)
                    head_clip["start"] = round3(cs)
                    keep.append(head_clip)
                    removed.append(head_clip["id"])
                if tail > MIN_CLIP_DURATION:
                    tail_clip = copy.deepcopy(c)
                    tail_clip["id"] = new_clip_id(track["id"], [x.get("id") for x in track["clips"]])
                    tail_clip["start"] = round3(s)
                    tail_clip["duration"] = round3(tail)
                    if "in" in c:
                        speed = float(c.get("speed", 1.0)) or 1.0
                        tail_clip["in"] = round3(float(c.get("in", 0.0)) + head * speed)
                    keep.append(tail_clip)
                    removed.append(tail_clip["id"])
        keep.sort(key=lambda c: (float(c["start"]), str(c.get("id", ""))))
        track["clips"] = keep

    def _prev_end(self, track: Dict[str, Any], clip: Dict[str, Any]) -> float:
        starts = [float(c["start"]) + float(c["duration"]) for c in track["clips"]
                  if c is not clip and float(c["start"]) <= float(clip["start"])]
        return max(starts) if starts else 0.0

    def _next_start(self, track: Dict[str, Any], clip: Dict[str, Any]) -> Optional[float]:
        starts = [float(c["start"]) for c in track["clips"]
                  if c is not clip and float(c["start"]) >= float(clip["start"])]
        return min(starts) if starts else None

    def _find(self, clip_id: str) -> Tuple[Optional[Dict[str, Any]], Optional[Dict[str, Any]]]:
        return find_clip(self.edl, clip_id)

    def _track(self, track_id: str) -> Dict[str, Any]:
        for t in self.edl["tracks"]:
            if t["id"] == track_id:
                return t
        raise OperationValidationError([f"unknown track '{track_id}'"])

    def _source(self, source_id: Optional[str]) -> Optional[Dict[str, Any]]:
        if not source_id:
            return None
        for s in self.edl.get("sources", []):
            if s.get("id") == source_id:
                return s
        return None


# --------------------------------------------------------------------------
# free helpers
# --------------------------------------------------------------------------
def _split_caption_text(text: str, max_chars: int) -> List[str]:
    """Split a narration turn into screenable pieces (word-safe)."""
    text = text.strip()
    if len(text) <= max_chars:
        return [text]
    pieces, current = [], ""
    for word in text.split():
        candidate = f"{current} {word}".strip()
        if len(candidate) > max_chars and current:
            pieces.append(current)
            current = word
        else:
            current = candidate
    if current:
        pieces.append(current)
    return pieces


def _turn_num(turn: Any, key: str) -> float:
    try:
        return float(turn.get(key, 0.0) or 0.0)
    except (TypeError, ValueError, AttributeError):
        return 0.0


def _num(value: Any, field: str) -> float:
    try:
        v = float(value)
    except (TypeError, ValueError):
        raise OperationValidationError([f"{field} must be a number"])
    if v != v or v in (float("inf"), float("-inf")):
        raise OperationValidationError([f"{field} must be finite"])
    return v


def _int_in(value: Any, lo: int, hi: int) -> int:
    try:
        v = int(value)
    except (TypeError, ValueError):
        return lo
    return max(lo, min(hi, v))


def _err_message(e: Exception) -> str:
    if isinstance(e, (OperationValidationError, EDLValidationError)):
        errors = getattr(e, "errors", None)
        return (errors or [str(e)])[0]
    return str(e) or e.__class__.__name__


# --------------------------------------------------------------------------
# direct-manipulation helpers (server-side tools; not part of the op API)
# --------------------------------------------------------------------------
def set_clip_transform(edl: Dict[str, Any], clip_id: str, *, scale: Optional[float] = None,
                       x: Optional[float] = None, y: Optional[float] = None,
                       crop: Optional[Dict[str, Any]] = None,
                       focus: Optional[Dict[str, Any]] = None) -> bool:
    """Direct transform write — used by the SAM smart-crop pass, not via ops."""
    track, clip = find_clip(edl, clip_id)
    if not clip or track is None or track["id"] != TRACK_VIDEO:
        return False
    tr = clip.setdefault("transform", {"scale": 1.0, "x": 0.0, "y": 0.0, "crop": None})
    changed = False
    if scale is not None:
        tr["scale"] = round3(max(0.05, min(8.0, float(scale))))
        changed = True
    if x is not None:
        tr["x"] = round3(max(-1.0, min(1.0, float(x))))
        changed = True
    if y is not None:
        tr["y"] = round3(max(-1.0, min(1.0, float(y))))
        changed = True
    if crop is not None:
        out = {}
        for k in ("left", "top", "right", "bottom"):
            if k in crop:
                out[k] = round3(max(0.0, min(0.95, float(crop[k]))))
        if len(out) == 4:
            tr["crop"] = out
            changed = True
    if focus is not None:
        tr["focus"] = {"x": max(0.0, min(1.0, float(focus.get("x", 0.5)))),
                       "y": max(0.0, min(1.0, float(focus.get("y", 0.5))))}
        changed = True
    return changed
  
