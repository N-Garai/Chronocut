"""Pure-logic smoke checks for the storyboard/render compo
"""
import os
import sys

import pytest

# Ensure the backend package is importable when run from the backend dir.
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.tools.storyboard.shot_composer import (
    compose_shots,
    _scale_to_length,
    _apply_director_override,
    _build_query,
    _effect_for_tone,
    ALLOWED_CAMERA_MOVES,
)
from app.tools.render.ffmpeg_assembler import _image_zoompan, _color_grade_filter, _build_vf
from app.tools.render.profiles import get_profile


def _fake_segments(n, length):
    seg_dur = length / n
    return [
        {
            "segment_id": i + 1,
            "text": f"beat {i + 1}",
            "audio_start": round(i * seg_dur, 1),
            "audio_end": round((i + 1) * seg_dur, 1),
            "tone": "reflective",
            "emotion": "reflective",
            "suggested_visuals": ["rainy neon city", "aerial night"],
        }
        for i in range(n)
    ]


def test_scale_to_length_honors_requested_length():
    sb = [{"duration_seconds": 5.0} for _ in range(6)]
    _scale_to_length(sb, 30.0)
    total = round(sum(s["duration_seconds"] for s in sb), 1)
    assert total == 30.0
    assert all(s["duration_seconds"] >= 2.0 for s in sb)


def test_scale_single_shot():
    sb = [{"duration_seconds": 5.0}]
    _scale_to_length(sb, 30.0)
    assert sb[0]["duration_seconds"] == 30.0


def test_director_override_invalid_dropped():
    shot = {"motion": None, "transition": "cut", "color_grade": None,
            "overlay_text": None, "voiceover": True}
    # Invalid camera_move + invalid transition must be ignored.
    _apply_director_override(shot, {"camera_move": "fly_through_space", "transition": "explode",
                                    "filter_preset": "cinematic", "voiceover": False})
    assert shot["motion"] is None
    assert shot["transition"] == "cut"
    assert shot["color_grade"] == "cinematic"  # valid
    assert shot["voiceover"] is False


def test_director_override_all_valid():
    shot = {"motion": None, "transition": "cut", "color_grade": None,
            "overlay_text": None, "voiceover": True}
    _apply_director_override(shot, {"camera_move": "push_in", "transition": "crossfade_0.5s",
                                    "filter_preset": "b&w", "text_overlay": "Hello"})
    assert shot["motion"] == "push_in"
    assert shot["transition"] == "crossfade_0.5s"
    assert shot["color_grade"] == "bw"
    assert shot["overlay_text"] == "Hello"


def test_build_query_specific():
    q = _build_query({"suggested_visuals": ["rainy neon city", "aerial night"], "text": "x"}, "cinematic", [], "")
    assert "rainy neon city" in q
    assert "aerial night" in q


def test_effect_for_tone_neutral_is_real_effect():
    # E2: neutral must not map to a transition masquerading as an effect.
    assert _effect_for_tone("neutral") == "ken_burns_slow_zoom"
    assert "crossfade" not in _effect_for_tone("neutral")


def test_image_zoompan_recipes_substitute_nf():
    for move in ("push_in", "pull_out", "pan_left", "pan_right", "parallax"):
        s = _image_zoompan(move, 1920, 1080, 30, 150)
        assert "zoompan=" in s
        assert "NF" not in s  # NF must be substituted in Python before ffmpeg sees it
        assert "s=1920x1080" in s


def test_color_grade_cinematic_and_bw():
    assert _color_grade_filter("cinematic") and "vignette" in _color_grade_filter("cinematic")
    assert _color_grade_filter("bw") and "hue=s=0" in _color_grade_filter("bw")
    assert _color_grade_filter("none") is None


def test_build_vf_emits_motion_and_grade():
    prof = get_profile("youtube_landscape")
    vf, _ = _build_vf(prof, is_image=True, effect="ken_burns_slow_zoom",
                      color_grade="cinematic", motion="push_in", overlay_text=None, duration=5.0)
    assert "zoompan=" in vf
    assert "vignette" in vf


def test_allow_lists_consistent():
    # Any motion the renderer knows must be in the allow-list.
    for m in ("hold", "push_in", "pull_out", "pan_left", "pan_right", "parallax", "slowmo_0.5", "speed_ramp", None):
        assert m in ALLOWED_CAMERA_MOVES


def test_compose_shots_scales_and_applies_director():
    import asyncio
    from app.agents.sub_agents.broll_sourcing_specialist import BRollSourcingSpecialist

    # Keep the test offline/fast: stub B-roll resolution (no network).
    async def _fake_resolve(self, query, duration=5.0, job_id=None, profile="youtube_landscape", avoid_urls=None):
        return {"type": "color_matte", "url": None, "file": None,
                "source": "generated", "effect": "none"}

    BRollSourcingSpecialist.resolve = _fake_resolve

    segs = _fake_segments(6, 30)
    plan = {1: {"camera_move": "push_in", "filter_preset": "cinematic", "transition": "cut"}}

    async def _run():
        return await compose_shots(segs, [], profile="youtube_landscape", job_id=None,
                                   director_plan=plan, length_seconds=30.0)

    sb = asyncio.run(_run())
    total = round(sum(s["duration_seconds"] for s in sb), 1)
    assert total == 30.0
    assert sb[0]["motion"] == "push_in"
    assert sb[0]["color_grade"] == "cinematic"
