import logging
from typing import Optional, Dict, Any, List

logger = logging.getLogger("chronocut.tools.script")

__all__ = ["script_from_transcript", "script_from_prompt", "script_from_reference"]


def _default_script(theme: str, length_seconds: int, tone: str) -> Dict[str, Any]:
    n = max(3, length_seconds // 5)
    seg_dur = length_seconds / n
    script = []
    # Even the deterministic fallback emits specific, searchable phrases
    # and a sound-bed cue so footage search + ambient bed still work without an LLM.
    visual_pool = [
        f"{theme} cinematic wide shot",
        f"{theme} close up detail",
        f"{theme} aerial slow motion",
    ]
    for i in range(n):
        script.append({
            "segment_id": i + 1,
            "text": f"{theme} — part {i + 1}." if i else f"{theme}.",
            "audio_start": round(i * seg_dur, 1),
            "audio_end": round((i + 1) * seg_dur, 1),
            "tone": tone,
            "emotion": "reflective" if i % 2 else "setup",
            "suggested_visuals": [visual_pool[i % len(visual_pool)], theme],
            "voiceover": True,
            "sfx": ["ambient"] if i == 0 else None,
            "voiceover_direction": "steady, warm",
        })
    return {"script": script, "total_duration_seconds": length_seconds,
            "voiceover_notes": "Generated fallback narration.", "narrative_arc": ["hook", "setup", "payoff"]}


async def script_from_transcript(transcript: str, segments: List[Dict[str, Any]], user_prompt: str = "", job_id: Optional[str] = None, similar_context: str = "") -> Dict[str, Any]:
    """Mode A: write a documentary script from a transcribed interview."""
    from app.tools.llm.call import scored_llm_json

    if not transcript.strip():
        return _default_script(user_prompt or "Untitled story", 60, "reflective")

    system = (
        "You are a documentary screenwriter. Given a raw interview transcript, produce a tight "
        "narration script. Remove filler. Return ONLY JSON: "
        "{\"script\": [{\"segment_id\":int, \"text\":str, \"audio_start\":float, \"audio_end\":float, "
        "\"tone\":str, \"emotion\":str, \"suggested_visuals\":[str], \"voiceover\":bool, \"sfx\":[str], \"voiceover_direction\":str}], "
        "\"total_duration_seconds\":float, \"voiceover_notes\":str, \"narrative_arc\":[str]}. "
        "Keep timestamps in seconds. "
        "VISUALS: for each segment emit 2-3 CONCRETE, searchable visual phrases (e.g. "
        "'rainy neon city aerial night', 'close up hands weaving') — these drive stock footage "
        "search, so be specific and avoid single generic words. "
        "SFX: emit 0-2 sound-effect cues per segment from {rain, city, wind, crowd, water, drone, "
        "machine, chime, click, none}. "
        "VOICEOVER RULES: never repeat the input prompt and never describe what is "
        "visibly on screen; write original emotional/contextual narration (memory, "
        "reflection, fact). Set voiceover:false for purely atmospheric or transitional "
        "beats so the visuals can breathe."
    )
    similar_block = (
        f"\n\nSIMILAR PAST PROJECTS (reuse their narrative voice, pacing and structure where "
        f"appropriate, but write NEW content — do not copy verbatim):\n{similar_context}\n"
        if similar_context else ""
    )
    prompt = (
        f"RAW TRANSCRIPT:\n{transcript[:8000]}\n\n"
        f"Creative direction: {user_prompt or 'None'}\n\n"
        f"{similar_block}"
        "Write the narration script."
    )
    try:
        result = await scored_llm_json(prompt, system=system, job_id=job_id, agent="screenwriter",
                                          tool="script_writer", temperature=0.6, max_output_tokens=4096)
        if not result.get("script"):
            raise ValueError("empty script")
        return result
    except Exception as e:
        logger.error(f"script_from_transcript failed: {e}")
        return _default_script(user_prompt or "Untitled story", 60, "reflective")


async def script_from_prompt(theme: str, tone: str, length_seconds: int, target_audience: str, job_id: Optional[str] = None, seed_words: str = "", similar_context: str = "") -> Dict[str, Any]:
    """Mode C: write a documentary script from a single prompt (no source media)."""
    from app.tools.llm.call import scored_llm_json

    system = (
        "You are a documentary screenwriter. Write a narration script from a single creative brief. "
        "Return ONLY JSON: {\"script\": [{\"segment_id\":int, \"text\":str, \"audio_start\":float, "
        "\"audio_end\":float, \"tone\":str, \"emotion\":str, \"suggested_visuals\":[str], "
        "\"voiceover\":bool, \"sfx\":[str], \"voiceover_direction\":str}], \"total_duration_seconds\":float, \"voiceover_notes\":str, "
        "\"narrative_arc\":[str]}. First 3s is the hook. Last 5s lands the thesis. "
        "VISUALS: for each segment emit 2-3 CONCRETE, searchable visual phrases (specific places, "
        "actions, weather, mood) — these drive footage search. "
        "SFX: emit 0-2 cues per segment from {rain, city, wind, crowd, water, drone, machine, chime, click, none}. "
        "VOICEOVER RULES: never repeat the creative brief/theme verbatim and never describe on-screen "
        "text; write original narration. Set voiceover:false for atmospheric/transitional beats."
    )
    similar_block = (
        f"\n\nSIMILAR PAST PROJECTS (reuse their narrative voice, pacing and structure where "
        f"appropriate, but write NEW content — do not copy verbatim):\n{similar_context}\n"
        if similar_context else ""
    )
    prompt = (
        f"Theme: {theme}\nTone: {tone}\nLength: {length_seconds} seconds\n"
        f"Audience: {target_audience}\nSeed words: {seed_words or 'none'}\n\n"
        f"{similar_block}"
        f"Structure into ~{max(3, length_seconds // 5)} segments of ~5s each."
    )
    try:
        result = await scored_llm_json(prompt, system=system, job_id=job_id, agent="screenwriter",
                                          tool="script_from_prompt", temperature=0.8, max_output_tokens=4096)
        if not result.get("script"):
            raise ValueError("empty script")
        return result
    except Exception as e:
        logger.error(f"script_from_prompt failed: {e}")
        return _default_script(theme, length_seconds, tone)


async def script_from_reference(reference_brief: Dict[str, Any], topic: str, length_seconds: int, target_audience: str, job_id: Optional[str] = None, similar_context: str = "") -> Dict[str, Any]:
    """Mode B: write a script that matches the pacing/structure of a reference cut."""
    from app.tools.llm.call import scored_llm_json

    rb = reference_brief or {}
    system = (
        "You are a documentary screenwriter. Mimic the STRUCTURE of a reference video while writing "
        "about a NEW topic. Return ONLY JSON: {\"script\": [{\"segment_id\":int, \"text\":str, "
        "\"audio_start\":float, \"audio_end\":float, \"tone\":str, \"emotion\":str, "
        "\"suggested_visuals\":[str], \"voiceover\":bool, \"sfx\":[str], \"voiceover_direction\":str}], \"total_duration_seconds\":float, "
        "\"voiceover_notes\":str, \"narrative_arc\":[str]}. "
        "VISUALS: for each segment emit 2-3 CONCRETE, searchable visual phrases (specific places, "
        "actions, weather, mood) — these drive footage search, so be specific. "
        "SFX: emit 0-2 sound-effect cues per segment from {rain, city, wind, crowd, water, drone, "
        "machine, chime, click, none}. "
        "VOICEOVER RULES: never repeat the input brief/theme verbatim and never describe on-screen "
        "text; write original narration (memory, reflection, fact). Set voiceover:false for "
        "atmospheric/transitional beats so the visuals can breathe."
    )
    similar_block = (
        f"\n\nSIMILAR PAST PROJECTS (reuse their narrative voice, pacing and structure where "
        f"appropriate, but write NEW content — do not copy verbatim):\n{similar_context}\n"
        if similar_context else ""
    )
    prompt = (
        f"Reference structure: hook={rb.get('hook_seconds')}s, pacing={rb.get('pacing_seconds_per_shot')}s/shot, "
        f"tone_keywords={rb.get('tone_keywords')}, arc={rb.get('structure')}.\n"
        f"NEW topic: {topic}\nLength: {length_seconds}s\nAudience: {target_audience}\n"
        f"{similar_block}"
        "Write a script matching that structure on the new topic."
    )
    try:
        result = await scored_llm_json(prompt, system=system, job_id=job_id, agent="screenwriter",
                                          tool="script_from_reference", temperature=0.7, max_output_tokens=4096)
        if not result.get("script"):
            raise ValueError("empty script")
        return result
    except Exception as e:
        logger.error(f"script_from_reference failed: {e}")
        return await script_from_prompt(topic, "cinematic", length_seconds, target_audience, job_id=job_id)
