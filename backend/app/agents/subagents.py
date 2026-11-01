"""Sub-agent registry: parents, choice keywords, prompt templates.

Each entry defines ``{id, parent, family, purpose, prompt_template, choices,
tools, output_schema, max_calls}``. Choice keywords ("off", "cut_only",
"center") engage zero model calls; when a sub-agent engages it receives all
candidates in one prompt and returns all fragments in one response. Hard cap:
≤8 sub-agent calls per apply, enforced in the governor. Parents substitute
their default recipe rows on any sub-agent failure — the apply never blocks.

Anti-duplication: where a pipeline worker already produces an artifact a
sub-agent needs, the parent passes it as a runtime key. Registry records
``kind`` ("pipeline_tool" for existing worker labels, "planner_specialist"
otherwise) so one telemetry schema covers both.
"""
import logging
import re
from typing import Any, Dict, List, Optional

from app.agents import telemetry as _tel

logger = logging.getLogger("chronocut.agents.subagents")

MAX_CALLS_PER_APPLY = 8

_FAMILY_ORDER = {
    "ARCHIVIST": ["excerpter", "scout", "tagger"],
    "SCREENWRITER": ["narrativist", "dialogist", "meter"],
    "DIRECTOR": ["scene_caster", "composer", "continuist"],
    "EDITOR": ["supervisor", "rhythmist", "motionist", "colorist", "transitionist", "audioist", "typographer"],
    "RENDER": ["sentinel", "framer", "packager"],
}

_OFF_KEYWORDS = {"off", "center", "cut_only"}


def _entry(sid: str, parent: str, purpose: str, keyword: str, choices: List[str],
           *, kind: str = "planner_specialist", tools: Optional[List[str]] = None,
           output_schema: Optional[str] = None, recipe_list: Optional[List[str]] = None,
           analyzer_list: Optional[List[str]] = None, max_calls: int = 1) -> Dict[str, Any]:
    return {
        "id": sid,
        "parent": parent,
        "family": parent.upper(),
        "kind": kind,
        "purpose": purpose,
        "prompt_template": (
            f"You are {sid.replace('_', ' ').title()}, a {parent.lower()} sub-agent employed by "
            f"{parent.upper()} in ChronoCut. You do not write code and never invent operations "
            f"outside the allowlist/schema. Context is capped; choices are pre-decided by the "
            f"parent; output JSON only, matching the schema; every choice justified in <= 12 words; "
            f"all-or-nothing; never emit an operation the parent's schema would reject."
        ),
        "choices": {c: choices for c in ([keyword] if isinstance(keyword, str) else list(keyword))},
        "keyword": keyword,
        "engagement_values": choices,
        "tools": tools or [],
        "output_schema": output_schema or "",
        "recipes": recipe_list or [],
        "analyzers": analyzer_list or [],
        "max_calls": max(int(max_calls), 1),
    }


EDIT_ROLE_CHOICES_OFF = "off"
EDIT_ROLES = ["off", "auto", "cinematic"]

REGISTRY: List[Dict[str, Any]] = [
    # ---- ARCHIVIST ----------------------------------------------------------
    _entry("excerpter", "archivist", "Transcript cleanup: filler removal, sentence segmentation, turn map.",
           "cleanup", ["off", "light", "deep"], output_schema='{"turns": [{start, end, text}]}',
           recipe_list=["remove_silence"], analyzer_list=["silencedetect"]),
    _entry("scout", "archivist", "Asset triage: best-frame picks, quality ranking, duplicate/blur removal.",
           "triage", ["off", "auto", "strict"], output_schema='{"ranked_assets": [{asset_id, score}]}',
           kind="pipeline_tool", analyzer_list=["blackdetect", "freezedetect"]),
    _entry("tagger", "archivist", "Semantic asset clustering + theme labels for retrieval.",
           "tags", ["off", "auto", "minimal"], output_schema='{"clusters": [{theme, asset_ids}]}',
           kind="pipeline_tool", recipe_list=["scale", "crop"]),
    # ---- SCREENWRITER -------------------------------------------------------
    _entry("narrativist", "screenwriter", "Turns into story beats with emotion labels and cue points.",
           "beats", ["off", "auto", "chronicle", "hero", "day_in_life"],
           output_schema='{"beats": [{beat_id, at_ms, logline, emotion}]}', kind="pipeline_tool",
           analyzer_list=["beat_track"]),
    _entry("dialogist", "screenwriter", "VO/interstitial lines, pull-quotes, on-title candidates.",
           "voice_style", ["off", "plain", "lyrical", "documentary"],
           output_schema='{"lines": [{beat_id, text}], "titles": [str]}', kind="pipeline_tool",
           recipe_list=["add_caption", "update_caption"]),
    _entry("meter", "screenwriter", "Beat-level pacing and duration plan (target runtime distribution).",
           "pacing_plan", ["off", "auto", "fixed"],
           output_schema='{"plan": [{beat_id, target_s}]}', kind="pipeline_tool",
           recipe_list=["set_speed"]),
    # ---- DIRECTOR -----------------------------------------------------------
    _entry("scene_caster", "director", "Picks beats that need B-roll; assigns source + motion direction.",
           "broll_policy", ["off", "auto", "sparse", "rich"],
           output_schema='[{"beat_id", "kind", "asset_id"|"prompt", "motion", "at_ms", "duration_s"}]',
           recipe_list=["insert_broll", "ken_burns_in", "ken_burns_out", "ken_burns_slow_zoom",
                        "push_in", "pan_left", "pan_right"], kind="pipeline_tool"),
    _entry("composer", "director", "Shot framing: crop points, headroom, safe-area per beat.",
           "composition", ["off", "auto", "tight"],
           output_schema='[{"beat_id", "crop", "headroom"}]', kind="pipeline_tool",
           recipe_list=["hold", "push_in", "pull_out", "pan_left", "pan_right"]),
    _entry("continuist", "director", "Coverage/continuity check: uncovered beats, jump-cut risks.",
           "continuity", ["off", "auto", "strict"],
           output_schema='{"flags": [{beat_id, risk}]}', kind="pipeline_tool",
           analyzer_list=["scdet", "blackdetect"]),
    # ---- EDITOR (supervisor + 6) -------------------------------------------
    _entry("supervisor", "editor",
           "The EDITOR pass orchestrator: dispatches sub-agents, validates all fragments "
           "deterministically before merge, never raises.",
           "editor_pass", ["off", "auto", "supervised"], max_calls=1,
           analyzer_list=["scdet", "blackdetect", "freezedetect", "ebur128", "silencedetect"]),
    _entry("rhythmist", "editor", "Micro-trims: dead-air removal, word/turn-boundary cuts, padding.",
           "tighten", ["off", "auto", "aggressive"],
           output_schema='{"cut_points": [{"clip_id": str, "edge": "start|end", "time": num}]}',
           recipe_list=["split", "trim", "remove_silence"],
           analyzer_list=["silencedetect", "scdet", "beat_track"]),
    _entry("motionist", "editor", "Per-shot camera motion from the recipe library (setpts/zoompan).",
           "motion_pass", ["off", "auto", "cinematic"],
           output_schema='[{"clip_id", "motion", "speed"?}]',
           recipe_list=["hold", "push_in", "pull_out", "pan_left", "pan_right", "parallax",
                        "ken_burns_slow_zoom", "slowmo_0.5", "speed_ramp"]),
    _entry("colorist", "editor", "Per-shot + global grade from preset packs with scene matching.",
           "grade_arc", ["off", "cinematic", "gentle"],
           output_schema='[{"clip_id"?, "value"}]',
           recipe_list=["clean", "neutral", "nostalgic", "professional", "cinematic", "warm",
                        "teal_orange", "b&w"]),
    _entry("transitionist", "editor", "Per-shot transitions (xfade family) only at final cut points.",
           "transition_policy", ["off", "cut_only", "auto", "custom"],
           output_schema='[{"clip_a", "clip_b", "recipe", "params"}]',
           recipe_list=["cut", "crossfade", "crossfade_0.5s", "crossfade_1s", "fade",
                        "dissolve", "dip_black", "hard_cut", "match_cut"],
           analyzer_list=["beat_track", "onset_detect"]),
    _entry("audioist", "editor", "Ducking curves, ambient bed levels, SFX placement, music mix.",
           "audio_sink", ["off", "auto", "cinematic"],
           output_schema='[{"at_s", "kind", "value"}]',
           recipe_list=["replace_music", "remove_silence"],
           analyzer_list=["ebur128", "beat_track", "onset_detect"]),
    _entry("typographer", "editor", "Captions, lower thirds, chapter titles, kinetic type.",
           "caption_style", ["off", "plain", "bold", "kinetic"],
           output_schema='[{"start", "duration", "text", "style"}]',
           recipe_list=["add_caption", "update_caption", "ensure_captions"]),
    # ---- RENDER -------------------------------------------------------------
    _entry("sentinel", "render", "Render QA preflight: profile fit, duration caps, RAM gates.",
           "qa", ["off", "lint", "strict"],
           output_schema='{"warnings": [str], "ok": bool}', kind="pipeline_tool",
           analyzer_list=["blackdetect", "freezedetect", "ebur128"]),
    _entry("framer", "render", "Subject-aware reframe windows per time range for 9:16/other profiles.",
           "reframe", ["off", "center", "auto"],
           output_schema='[{"window": [start, end], "crop": {...}}]', kind="pipeline_tool",
           recipe_list=["crop", "pad", "scale"]),
    _entry("packager", "render", "Export profile ladder and per-platform packaging decisions.",
           "packages", ["off", "preview", "full_ladder"],
           output_schema='{"ladder": [str]}', kind="pipeline_tool",
           recipe_list=["scale", "pad"]),
]

REGISTRY_BY_ID: Dict[str, Dict[str, Any]] = {e["id"]: e for e in REGISTRY}


def registry_summary() -> Dict[str, Any]:
    return {
        "count": len(REGISTRY),
        "by_parent": {
            parent: [REGISTRY_BY_ID[i]["id"] for i in order]
            for (parent, order) in _FAMILY_ORDER.items()
        },
        "max_calls_per_apply": MAX_CALLS_PER_APPLY,
    }


def entry(sid: str) -> Optional[Dict[str, Any]]:
    return REGISTRY_BY_ID.get(sid or "")


def engages(sid: str, choice: Optional[str]) -> bool:
    """False for "off"/"cut_only"/"center" and for unknown/absent choices: no calls."""
    if not choice:
        return False
    c = str(choice).strip().lower()
    if c in _OFF_KEYWORDS:
        return False
    e = entry(sid)
    if not e:
        return False
    return c in [str(v).lower() for v in e["engagement_values"]]


def engaged_for(apply_choices: Dict[str, Optional[str]]) -> List[str]:
    """Sub-agent ids engaged by a parent's choice keyword map (order: family order)."""
    out: List[str] = []
    for parent, order in _FAMILY_ORDER.items():
        for sid in order:
            kw = apply_choices.get(sid)
            if engages(sid, kw):
                out.append(sid)
    return out


def fragment_is_valid(sid: str, fragment: Any) -> bool:
    """Deterministic fragment validation at merge time: registry recipes and EDL
    field allow-lists (grades/motions are validated the same way parents do)."""
    e = entry(sid)
    if not e or fragment is None:
        return False
    if e["recipes"]:
        vals = []
        if isinstance(fragment, list):
            vals = fragment
        elif isinstance(fragment, dict):
            vals = fragment.values()
        for item in vals:
            rv = str(item.get("recipe") or item.get("value") or item.get("motion") or "") if isinstance(item, dict) else ""
            if rv and rv not in e["recipes"]:
                return False
    if isinstance(fragment, list):
        return all(isinstance(x, dict) for x in fragment) or not fragment
    return isinstance(fragment, (dict, list))


class SubAgentRunner:
    """Batches one prompt per engaged sub-agent; enforces the ≤8 calls cap."""

    def __init__(self, parent_agent: str, job_id: Optional[str] = None):
        self.parent_agent = parent_agent
        self.job_id = job_id
        self.calls = 0

    async def invoke(self, sid: str, *, context_snippet: str,
                     choices: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        if self.calls >= MAX_CALLS_PER_APPLY:
            return {"sid": sid, "status": "degraded", "fragments": [],
                    "detail": "sub-agent call cap reached (<=8 per apply)"}
        self.calls += 1
        # Batch: all candidates in one prompt, all fragments in one response.
        prompt = "\n".join([
            entry(sid)["prompt_template"] if entry(sid) else f"You are {sid}.",
            f"choices: {choices}",
            f"context: {context_snippet}",
            "Output JSON only.",
        ])
        try:
            from app.tools.llm.call import scored_llm_json
            fed = await scored_llm_json(prompt, system="Sub-agent JSON responder.",
                                        agent=sid, tool="subagent_fragments",
                                        temperature=0.4, max_output_tokens=1024)
            if not fragment_is_valid(sid, fed.get("fragments") or fed):
                raise ValueError("fragment failed schema/recipe validation")
            fragments = fed.get("fragments") if isinstance(fed, dict) else []
            _tel.record_activity(self.job_id, agent=sid, action="fragments",
                                 status=_tel.STATUS_SUCCEEDED,
                                 parent_agent=self.parent_agent,
                                 detail=f"{sid} returned fragments")
            return {"sid": sid, "status": "ok", "fragments": fragments or []}
        except Exception as e:
            _tel.record_activity(self.job_id, agent=sid, action="fragments",
                                 status=_tel.STATUS_FAILED, parent_agent=self.parent_agent,
                                 detail=f"{sid} degraded: {type(e).__name__}")
            return {"sid": sid, "status": "degraded", "fragments": [],
                    "detail": str(e)[:200]}


# ---------------------------------------------------------------------------
# Runtime engagement
# ---------------------------------------------------------------------------
#: Keywords the parent can decide from the request text without a model call.
_MESSAGE_KEYWORDS = [
    (("cinematic", "filmic", "movie look", "dramatic"), {
        "motionist": "cinematic", "colorist": "cinematic", "transitionist": "auto"}),
    (("warmer", "warm", "nostalgic", "grade", "colour", "color"), {
        "colorist": "gentle"}),
    (("transition", "crossfade", "dissolve", "fade"), {"transitionist": "auto"}),
    (("caption", "subtitle", "kinetic", "title"), {"typographer": "plain"}),
    (("tighten", "tight", "pause", "dead air", "silence"), {"rhythmist": "auto"}),
    (("slow motion", "slowmo", "speed ramp", "speed", "motion", "ken burns"),
     {"motionist": "auto"}),
    (("music", "score", "soundtrack"), {"audioist": "auto"}),
]

#: Pipeline stages whose specialist consumes an existing artifact (zero model
#: calls). Each stage records one entry so the feed shows the parent/sub-agent
#: pair and later stages can read it.
PIPELINE_STAGES = [
    ("archivist", "excerpter", "cleanup"),
    ("screenwriter", "narrativist", "beats"),
    ("director", "scene_caster", "broll_policy"),
    ("editor", "supervisor", "editor_pass"),
    ("render", "sentinel", "qa"),
]


def choices_from_message(message: str) -> Dict[str, str]:
    """Deterministic per-specialist keyword map from the request text.

    Unmatched specialists stay absent, and absent/off keywords engage nothing.
    """
    text = str(message or "").lower()
    choices: Dict[str, str] = {}
    for needles, mapping in _MESSAGE_KEYWORDS:
        if any(n in text for n in needles):
            for sid, kw in mapping.items():
                choices.setdefault(sid, kw)
    return choices


def record_pipeline_stage(job_id: Optional[str], parent: str, subagent: str,
                          *, data: Optional[Dict[str, Any]] = None,
                          keyword: Optional[str] = None,
                          status: str = "succeeded", note: str = "") -> Optional[Dict[str, Any]]:
    """Record a pipeline specialist's artifact in agent_context + telemetry.

    Pipeline specialists are deterministic: they consume what the stage worker
    already produced, so this makes no model call. It exists so the parent's
    decision is visible in the feed and reusable by later stages.
    """
    e = entry(subagent)
    if e and str(e.get("parent")) != str(parent).lower():
        logger.warning("sub-agent %s is not owned by %s", subagent, parent)
        return None
    kw = keyword or (e.get("keyword") if e else None)
    try:
        from app.agents import agent_context as ctx
        row = ctx.record(str(job_id or ""), parent, subagent, keyword=kw,
                         status=status, data=data or {}, note=note, call=False)
    except Exception as exc:  # context is best-effort
        logger.warning("agent_context record failed: %s", exc)
        row = None
    _tel.record_activity(job_id, agent=subagent, action="context",
                         status=status, parent_agent=parent,
                         detail=note or f"{parent} stage context recorded")
    return row


#: What each EDITOR specialist's fragments may become (parent op + allow-list).
_EDITOR_OP_MAP = {
    "colorist": ("set_grade_all", "value", "ALLOWED_GRADES"),
    "motionist": ("set_motion_all", "value", "ALLOWED_MOTIONS"),
    "transitionist": ("set_transition_all", "value", "ALLOWED_TRANSITIONS"),
}


def fragments_to_ops(subagent: str, fragments: Any) -> List[Dict[str, Any]]:
    """Map validated fragments to parent operations (allow-list enforced)."""
    from app.edl import schema as _schema

    def _pick(item: Dict[str, Any]) -> Optional[str]:
        for k in ("value", "recipe", "motion", "grade", "transition"):
            v = item.get(k)
            if v:
                return str(v)
        return None

    items = fragments if isinstance(fragments, list) else (
        [fragments] if isinstance(fragments, dict) else [])

    if subagent in _EDITOR_OP_MAP:
        opname, _, allow_attr = _EDITOR_OP_MAP[subagent]
        allowed = getattr(_schema, allow_attr, set())
        for item in items:
            if not isinstance(item, dict):
                continue
            val = _pick(item)
            if val and val in allowed:
                return [{"op": opname, "args": {"value": val}}]
        return []

    if subagent == "rhythmist":
        cuts: List[Dict[str, Any]] = []
        raw = fragments.get("cut_points") if isinstance(fragments, dict) else fragments
        for item in (raw if isinstance(raw, list) else []):
            if not isinstance(item, dict) or not item.get("clip_id"):
                continue
            edge = str(item.get("edge") or "end")
            time = item.get("time")
            if edge not in ("start", "end") or time is None:
                continue
            cuts.append({"op": "trim", "args": {"clip_id": str(item["clip_id"]),
                                                 "edge": edge, "time": float(time)}})
            if len(cuts) >= 6:
                break
        return cuts

    if subagent == "typographer":
        return [{"op": "ensure_captions", "args": {}}] if items else []

    return []


async def engage_editor_specialists(job_id: Optional[str], message: str,
                                    context_snippet: str) -> Dict[str, Any]:
    """Run the EDITOR family specialists engaged by this request.

    Returns ``{ops, engaged, degraded, warnings}``; never raises. An unengaged
    request (no style keywords) makes zero model calls.
    """
    choices = choices_from_message(message)
    editor_choices = {sid: kw for sid, kw in choices.items()
                      if (entry(sid) or {}).get("parent") == "editor"
                      and sid != "supervisor"}
    engaged = engaged_for(editor_choices)
    out: Dict[str, Any] = {"ops": [], "engaged": engaged, "degraded": [], "warnings": []}
    if not engaged:
        return out

    from app.agents import agent_context as ctx
    runner = SubAgentRunner("editor", job_id=job_id)
    for sid in engaged:
        res = await runner.invoke(sid, context_snippet=context_snippet,
                                  choices={"keyword": editor_choices.get(sid)})
        ok = res.get("status") == "ok"
        ops = fragments_to_ops(sid, res.get("fragments") or []) if ok else []
        out["ops"].extend(ops)
        if not ok:
            out["degraded"].append(sid)
            out["warnings"].append(f"{sid} degraded: {res.get('detail') or 'no fragments'}"[:180])
        ctx.record(str(job_id or ""), "editor", sid,
                   keyword=editor_choices.get(sid), status="succeeded" if ok else "degraded",
                   data={"ops": len(ops)}, note=f"editor specialist -> {len(ops)} op(s)", call=True)
    return out


_PAT_NOISE = re.compile(r"\s+")


def redact_for_feed(text: str) -> str:
    return _PAT_NOISE.sub(" ", str(text or "")).strip()[:240]
