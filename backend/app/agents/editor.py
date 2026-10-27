"""Editor supervisor agent (pro edit pass).

This is a SUPERVISOR, not a second render engine. It reviews the composed
storyboard (plus the user's intent) and emits an *edit-decision list*:

  - drop dead-air / off-brief shots
  - regrade / re-motion / re-transition per shot
  - set global style + pacing from the user's brief and tone

The decisions are applied back onto the storyboard; the real cutting is still
done by ``app.tools.render`` (ffmpeg). This keeps ONE render path (no duplicate
engine, no divergence) and degrades safely: on any LLM failure, timeout, or
invalid output it returns a deterministic fallback plan instead of raising.

Robustness rules:
  * Never raises into the pipeline. Every failure -> deterministic fallback.
  * All LLM values are validated against allow-lists before being applied.
  * At least one shot is always kept (never emits an empty storyboard).
"""

import json
import logging
from typing import Dict, Any, List, Optional

logger = logging.getLogger("chronocut.agents.editor")

# Allow-lists mirror shot_composer so applied overrides are always renderable.
COLOR_GRADES = {
    "clean", "nostalgic", "professional", "cinematic", "b&w",
    "teal_orange", "warm", "neutral",
}
MOTIONS = {
    "hold", "push_in", "pull_out", "pan_left", "pan_right",
    "parallax", "ken_burns_slow_zoom",
}
TRANSITIONS = {"crossfade", "dip_black", "hard_cut", "match_cut"}

# Tone -> default style used by the deterministic fallback (and as a hint to LLM).
TONE_STYLE = {
    "cinematic": ("cinematic", "balanced"),
    "documentary": ("clean", "balanced"),
    "promo": ("cinematic", "energetic"),
    "news": ("clean", "energetic"),
    "calm": ("warm", "calm"),
    "uplifting": ("warm", "balanced"),
    "dark": ("b&w", "calm"),
    "corporate": ("professional", "balanced"),
}


class EditorAgent:
    """LLM-driven editing supervisor with a hardcoded fallback."""

    SYSTEM_PROMPT = (
        "You are a senior video EDITOR supervising an autonomous documentary pipeline. "
        "You receive a drafted storyboard and the USER'S BRIEF. Your job is to refine the "
        "edit so it honors the brief and feels professional.\n"
        "ASSISTANT-EDITOR RULES (ChatCut-style):\n"
        "  - Honor the brief: its hook, thesis, exclusions and CTA are the tie-breaker. "
        "Do NOT invent facts or rewrite the message.\n"
        "  - Mechanical passes only: drop dead-air / off-brief shots, fix pacing, choose "
        "tasteful grades and transitions. Never alter the narration text.\n"
        "  - Be conservative: keep a shot unless it is clearly weak (very short, or footage "
        "that contradicts the brief). Always keep at least one shot.\n"
        "Return ONLY JSON (no prose) with this shape:\n"
        "{\n"
        '  "global": {"style": str, "pacing": "calm|balanced|energetic", '
        '"remove_dead_air": bool, "ensure_transitions": bool},\n'
        '  "shots": [{"shot_id": str, "action": "keep|drop", "color_grade": str, '
        '"motion": str, "transition": str, "overlay_text": null|str, "voiceover": bool}],\n'
        '  "notes": str\n'
        "}\n"
        "Allowed values only - color_grade in {clean, nostalgic, professional, cinematic, "
        "b&w, teal_orange, warm, neutral}; motion in {hold, push_in, pull_out, pan_left, "
        "pan_right, parallax, ken_burns_slow_zoom}; transition in {crossfade, dip_black, "
        "hard_cut, match_cut}. action 'drop' only for clearly weak shots."
    )

    # ------------------------------------------------------------------ #
    @staticmethod
    def _summarize_storyboard(storyboard: List[Dict]) -> str:
        lines = []
        for s in storyboard:
            vs = (s.get("visual_source") or {})
            src = vs.get("type") or vs.get("source") or "unknown"
            lines.append(
                f"- id={s.get('shot_id')} dur={float(s.get('duration_seconds', 0)):.1f} "
                f"grade={s.get('color_grade')} motion={s.get('motion')} "
                f"trans={s.get('transition')} src={src} vo={s.get('voiceover')} "
                f"txt={(s.get('audio_text') or '')[:40]!r}"
            )
        return "\n".join(lines)

    @staticmethod
    def _safe_json(text: str) -> Optional[dict]:
        if not text:
            return None
        try:
            data = json.loads(text)
            return data if isinstance(data, dict) else None
        except Exception:
            # Try to extract the first {...} block (LLMs sometimes wrap JSON).
            try:
                start = text.index("{")
                end = text.rindex("}") + 1
                return json.loads(text[start:end])
            except Exception:
                return None

    # ------------------------------------------------------------------ #
    async def run(
        self,
        script_segments: List[Dict],
        storyboard: List[Dict],
        user_prompt: str = "",
        reference_brief: Optional[Dict] = None,
        tone: str = "cinematic",
        profile: Any = None,
        llm_available: bool = True,
    ) -> Dict[str, Any]:
        """Return an editor plan (LLM-driven, else deterministic fallback)."""
        if not storyboard:
            return self._fallback(storyboard, tone, reason="empty storyboard")

        if llm_available:
            try:
                from app.tools.llm.call import scored_gemini_call
                brief_txt = ""
                if reference_brief:
                    brief_txt = json.dumps(reference_brief, ensure_ascii=False)[:600]
                user_intent = (
                    user_prompt
                    or (reference_brief.get("brief") if isinstance(reference_brief, dict) else None)
                    or ""
                )
                prompt = (
                    f"USER BRIEF / INTENT:\n{user_intent[:800]}\n\n"
                    f"TONE: {tone}\n\n"
                    f"DRAFT STORYBOARD ({len(storyboard)} shots):\n"
                    f"{self._summarize_storyboard(storyboard)}\n\n"
                    "Refine this edit. Drop only clearly weak/off-brief shots. Respond with JSON."
                )
                result = await scored_gemini_call(
                    prompt, system=self.SYSTEM_PROMPT, json_mode=True
                )
                raw = result.get("text") if isinstance(result, dict) else str(result)
                data = self._safe_json(raw)
                if data and isinstance(data.get("shots"), list) and data["shots"]:
                    plan = self._normalize(data, storyboard, tone)
                    plan["fallback_used"] = False
                    logger.info("EditorAgent: LLM plan applied.")
                    return plan
                logger.warning("EditorAgent: LLM returned no usable plan; using fallback.")
            except Exception as e:
                logger.warning(f"EditorAgent LLM failed ({e}); using deterministic fallback.")

        return self._fallback(storyboard, tone, reason="llm_unavailable_or_invalid")

    # ------------------------------------------------------------------ #
    def _normalize(self, data: Dict, storyboard: List[Dict], tone: str) -> Dict[str, Any]:
        """Validate LLM output against allow-lists; drop invalid fields."""
        by_id = {s.get("shot_id"): s for s in storyboard}
        shots = []
        for item in data.get("shots", []):
            sid = item.get("shot_id")
            if sid not in by_id:
                continue
            norm: Dict[str, Any] = {"shot_id": sid}
            if item.get("action") == "drop":
                norm["action"] = "drop"
            else:
                norm["action"] = "keep"
            cg = item.get("color_grade")
            if cg in COLOR_GRADES:
                norm["color_grade"] = cg
            mo = item.get("motion")
            if mo in MOTIONS:
                norm["motion"] = mo
            tr = item.get("transition")
            if tr in TRANSITIONS:
                norm["transition"] = tr
            ot = item.get("overlay_text")
            if isinstance(ot, str) and ot.strip():
                norm["overlay_text"] = ot.strip()[:120]
            if isinstance(item.get("voiceover"), bool):
                norm["voiceover"] = item["voiceover"]
            shots.append(norm)
        g = data.get("global") or {}
        style, pacing = TONE_STYLE.get(tone, ("cinematic", "balanced"))
        plan = {
            "global": {
                "style": g.get("style", style),
                "pacing": g.get("pacing", pacing),
                "remove_dead_air": bool(g.get("remove_dead_air", True)),
                "ensure_transitions": bool(g.get("ensure_transitions", True)),
            },
            "shots": shots,
            "notes": str(data.get("notes", ""))[:300],
        }
        return plan

    def _fallback(self, storyboard: List[Dict], tone: str, reason: str) -> Dict[str, Any]:
        """Deterministic pro-editor rules when the LLM is unavailable."""
        style, pacing = TONE_STYLE.get(tone, ("cinematic", "balanced"))
        shots = []
        n = len(storyboard)
        for s in storyboard:
            dur = float(s.get("duration_seconds", 3.0))
            item: Dict[str, Any] = {"shot_id": s.get("shot_id"), "action": "keep"}
            # Remove clear dead-air: very short shots only when we have enough.
            if n > 3 and dur < 1.2:
                item["action"] = "drop"
            # Ensure a tasteful grade consistent with tone if none set.
            if not s.get("color_grade"):
                item["color_grade"] = style
            # Avoid hard cuts between identical sources (jarring).
            if s.get("transition") == "hard_cut":
                item["transition"] = "crossfade"
            shots.append(item)
        return {
            "global": {
                "style": style, "pacing": pacing,
                "remove_dead_air": True, "ensure_transitions": True,
            },
            "shots": shots,
            "notes": f"deterministic fallback ({reason})",
            "fallback_used": True,
        }

    # ------------------------------------------------------------------ #
    @staticmethod
    def apply_editor_plan(storyboard: List[Dict], plan: Dict[str, Any]) -> List[Dict]:
        """Return a refined storyboard from an editor plan. Never raises; never empty."""
        if not plan or not storyboard:
            return storyboard
        overrides = {o.get("shot_id"): o for o in plan.get("shots", []) if o.get("shot_id")}
        out: List[Dict] = []
        for s in storyboard:
            ov = overrides.get(s.get("shot_id"))
            if ov and ov.get("action") == "drop":
                continue  # drop weak/off-brief shot
            shot = dict(s)  # shallow copy so we never mutate the caller's dict
            if ov:
                if "color_grade" in ov:
                    shot["color_grade"] = ov["color_grade"]
                if "motion" in ov:
                    shot["motion"] = ov["motion"]
                if "transition" in ov:
                    shot["transition"] = ov["transition"]
                if "overlay_text" in ov:
                    shot["overlay_text"] = ov["overlay_text"]
                if "voiceover" in ov:
                    shot["voiceover"] = ov["voiceover"]
            out.append(shot)
        # Never emit an empty storyboard.
        return out if out else storyboard
