"""DirectorAgent — the LLM "director".

Emits an edit-decision list per shot (filter_preset, camera_move, transition,
text_overlay, sound_bed, voiceover). The deterministic hardcoded mapping in
shot_composer remains the GUARANTEED fallback: every director value is validated
against an allow-list and dropped if invalid, so a bad/partial model response can
never break the render. The user prompt is treated as a brief the director must
respect, never rewrite (ChatCut-style assistant-editor rule).
"""
import os
import logging
from typing import Dict, Any, List, Optional

logger = logging.getLogger("chronocut.agents.director")

from app.tools.storyboard.shot_composer import (
    ALLOWED_CAMERA_MOVES,
    ALLOWED_TRANSITIONS,
    ALLOWED_FILTER_PRESETS,
)

_SKILLS_DIR = os.path.join(os.path.dirname(__file__), "..", "skills")

_SKILL_FILES = ("cuts.md", "grade.md", "motion.md", "sound.md")


def _load_skills() -> str:
    """G2: embed the skill text into the system prompt at runtime (no file reads in prod)."""
    chunks = []
    for name in _SKILL_FILES:
        p = os.path.join(_SKILLS_DIR, name)
        try:
            with open(p, "r", encoding="utf-8") as f:
                chunks.append(f"### {name}\n" + f.read())
        except Exception as e:
            logger.warning(f"director: skill {name} not loaded: {e}")
    return "\n\n".join(chunks)


class DirectorAgent:
    async def run(
        self,
        script_segments: List[Dict[str, Any]],
        job_id: Optional[str] = None,
        reference_brief: Optional[Dict[str, Any]] = None,
        user_prompt: str = "",
        tone: str = "cinematic",
    ) -> Optional[Dict[Any, Dict[str, Any]]]:
        from app.config import settings
        if not settings.ENABLE_DIRECTOR:
            return None
        from app.tools.llm.call import scored_llm_json
        from app.services.firestore_service import JobStateService

        skills = _load_skills()
        beats = []
        for seg in script_segments:
            beats.append({
                "segment_id": seg.get("segment_id", len(beats) + 1),
                "tone": seg.get("tone", "reflective"),
                "emotion": seg.get("emotion", "reflective"),
                "text": (seg.get("text") or "")[:120],
                "suggested_visuals": seg.get("suggested_visuals", []),
            })

        system = (
            "You are the EDITORIAL DIRECTOR of a documentary video engine. You decide HOW each "
            "beat is cut — look, camera move, transition, caption, and sound bed. You are an "
            "ASSISTANT EDITOR: perform only mechanical editing passes and NEVER rewrite or "
            "restate the user's message/brief. The user's brief is the tie-breaker.\n\n"
            "SKILLS (follow these rules):\n" + skills + "\n\n"
            "Return ONLY JSON: {\"plan\": [{\"segment_id\":int, \"filter_preset\":str, "
            "\"camera_move\":str, \"transition\":str, \"text_overlay\":str|null, "
            "\"sound_bed\":str|null, \"voiceover\":bool}]}. "
            "Allowed filter_preset: clean|nostalgic|professional|cinematic|b&w. "
            "Allowed camera_move: hold|push_in|pull_out|pan_left|pan_right|parallax|slowmo_0.5|speed_ramp. "
            "Allowed transition: cut|crossfade_0.5s|crossfade_1s|dissolve|dip_black|match_cut. "
            "text_overlay: a short caption (<=80 chars) or null. sound_bed: rain|city|drone|none|null. "
            "First beat transition must be 'cut'. Match camera_move to emotion "
            "(climax→push_in, tension→slowmo_0.5, release→pull_out, setup→pan_right)."
        )
        prompt = (
            f"USER BRIEF (respect it, do not rewrite): {user_prompt or '(none)'}\n"
            f"OVERALL TONE: {tone}\n"
            f"REFERENCE STRUCTURE: {reference_brief.get('structure') if reference_brief else '(none)'}\n\n"
            f"BEATS ({len(beats)}):\n" + "\n".join(
                f"- #{b['segment_id']} tone={b['tone']} emotion={b['emotion']} "
                f"visuals={b['suggested_visuals']}" for b in beats
            ) + "\n\nProduce the edit-decision plan."
        )
        try:
            result = await scored_llm_json(
                prompt, system=system, job_id=job_id, agent="director", tool="director_plan",
                temperature=0.5, max_output_tokens=4096, require_keys=["plan"],
            )
            plan_list = result.get("plan") or []
            plan: Dict[Any, Dict[str, Any]] = {}
            for item in plan_list:
                sid = item.get("segment_id")
                if sid is None:
                    continue
                # Validate every field against allow-lists; drop invalid entries so the
                # hardcoded mapping stays the fallback (fully deterministic).
                clean: Dict[str, Any] = {}
                if item.get("filter_preset") in ALLOWED_FILTER_PRESETS:
                    clean["filter_preset"] = item["filter_preset"]
                if item.get("camera_move") in ALLOWED_CAMERA_MOVES:
                    clean["camera_move"] = item["camera_move"]
                if item.get("transition") in ALLOWED_TRANSITIONS:
                    clean["transition"] = item["transition"]
                if isinstance(item.get("text_overlay"), str) and item["text_overlay"].strip():
                    clean["text_overlay"] = item["text_overlay"].strip()[:80]
                if isinstance(item.get("sound_bed"), str):
                    clean["sound_bed"] = item["sound_bed"]
                if isinstance(item.get("voiceover"), bool):
                    clean["voiceover"] = item["voiceover"]
                if clean:
                    plan[sid] = clean
            if plan:
                try:
                    JobStateService.append_event(job_id, {
                        "stage": "director", "progress_percent": 64,
                        "message": f"Director plan produced for {len(plan)} beat(s).",
                        "sub_agent": "DirectorAgent",
                    })
                except Exception:
                    pass
                return plan
        except Exception as e:
            logger.warning(f"DirectorAgent failed (using hardcoded mapping): {e}")
        return None
