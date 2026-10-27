import asyncio

from app.tools.script import screenwriter_tools as sw
import app.tools.llm.call as callmod


def test_default_script_fallback():
    s = sw._default_script("Heroes", 60, "cinematic")
    assert s["total_duration_seconds"] == 60
    assert len(s["script"]) >= 3


def test_prompt_mode_injects_rag_context():
    captured = {}

    async def fake(prompt, **kw):
        captured["prompt"] = prompt
        return {
            "script": [{
                "segment_id": 1, "text": "t", "audio_start": 0.0, "audio_end": 5.0,
                "tone": "x", "emotion": "x", "suggested_visuals": ["v"],
                "voiceover_direction": "d",
            }],
            "total_duration_seconds": 60, "voiceover_notes": "n", "narrative_arc": ["hook"],
        }

    original = callmod.scored_gemini_json
    callmod.scored_gemini_json = fake
    try:
        out = asyncio.run(
            sw.script_from_prompt(
                "ocean life", "cinematic", 60, "general",
                job_id="jx", similar_context="Past project: sea turtles",
            )
        )
    finally:
        callmod.scored_gemini_json = original

    assert "Past project" in captured["prompt"]
    assert out["script"][0]["text"] == "t"
