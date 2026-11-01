"""Per-profile framing: aspect math, EDL crop insertion, compiler hand-off.

A 16:9 cut exported to 9:16 / 1:1 / 21:9 must get a real crop window per clip;
explicit crops are never overwritten and matching aspects are left untouched.
"""
import pytest

from app.edl.compiler import clip_vf_chain
from app.tools.media.reframe import (
    apply_reframe_to_edl, aspect_crop, aspect_of_profile, focus_from_context,
)
from tests.edl_fixtures import make_edl


def _edl_with(aspects):
    """Fixture EDL whose sources carry an explicit aspect (no ffprobe needed)."""
    edl = make_edl()
    for src, aspect in zip(edl["sources"], aspects):
        src["aspect"] = aspect
    return edl


def test_aspect_of_profile():
    assert aspect_of_profile(1080, 1920) == pytest.approx(0.5625)
    assert aspect_of_profile(0, 0) == pytest.approx(16 / 9)


def test_matching_aspects_need_no_crop():
    assert aspect_crop(16 / 9, 16 / 9) is None
    assert aspect_crop(16 / 9, 16 / 9 + 0.005) is None   # inside the 0.01 tolerance


def test_landscape_to_portrait_trims_the_sides():
    crop = aspect_crop(16 / 9, 9 / 16)
    assert crop["left"] == pytest.approx(crop["right"])   # centred
    assert crop["left"] + crop["right"] == pytest.approx(1 - (9 / 16) / (16 / 9), abs=1e-3)
    assert crop["top"] == 0 and crop["bottom"] == 0


def test_focus_point_shifts_the_window_but_stays_in_frame():
    left = aspect_crop(16 / 9, 9 / 16, focus_x=0.15)
    right = aspect_crop(16 / 9, 9 / 16, focus_x=0.9)
    assert left["left"] < right["left"]
    for crop in (left, right):
        assert 0 <= crop["left"] < 1 and 0 <= crop["right"] < 1
        assert crop["left"] + crop["right"] <= 1.0001


def test_portrait_source_trimmed_for_landscape_target():
    crop = aspect_crop(9 / 16, 16 / 9)
    assert crop["left"] == 0 and crop["right"] == 0
    assert crop["top"] > 0 and crop["bottom"] > 0


def test_apply_reframe_sets_crop_only_where_needed():
    edl = _edl_with([16 / 9, 9 / 16, None])
    edl["sources"][1]["path"] = ""
    changed = apply_reframe_to_edl(edl, 1080, 1920)
    clips = {c["id"]: c for c in edl["tracks"][0]["clips"]}
    # v1-01 (16:9) and v1-03 (unknown -> 16:9) need a crop; v1-02 already 9:16
    assert changed == 2
    assert clips["v1-01"]["transform"]["crop"]["left"] > 0
    assert clips["v1-03"]["transform"]["crop"]["left"] > 0
    assert not (clips["v1-02"]["transform"] or {}).get("crop")


def test_apply_reframe_never_overwrites_an_explicit_crop():
    edl = _edl_with([16 / 9, 16 / 9, 16 / 9])
    explicit = {"left": 0.11, "top": 0.0, "right": 0.11, "bottom": 0.0}
    edl["tracks"][0]["clips"][0]["transform"] = {"crop": explicit}
    changed = apply_reframe_to_edl(edl, 1080, 1080)
    assert changed == 2
    assert edl["tracks"][0]["clips"][0]["transform"]["crop"] == explicit


def test_landscape_target_leaves_landscape_sources_alone():
    edl = _edl_with([16 / 9, 16 / 9, 16 / 9])
    assert apply_reframe_to_edl(edl, 1280, 720) == 0
    assert all(c["transform"].get("crop") is None for c in edl["tracks"][0]["clips"])


def test_compiler_chain_consumes_the_crop_window():
    edl = _edl_with([16 / 9, 16 / 9, 16 / 9])
    apply_reframe_to_edl(edl, 1080, 1920, focus={"img-a": {"x": 0.3, "y": 0.5}})
    clip = edl["tracks"][0]["clips"][0]
    vf, overlay = clip_vf_chain(clip, profile_w=1080, profile_h=1920, fps=30,
                                duration=5.0, is_image=True)
    assert isinstance(vf, str)
    # the aspect crop is narrower than the frame before it is re-scaled back
    assert "crop=" in vf
    assert overlay is None or isinstance(overlay, str)


def test_focus_from_context_reads_the_framer_row():
    from app.agents.subagents import record_pipeline_stage
    job = "j-reframe-focus"
    record_pipeline_stage(job, "render", "framer", data={"focus": {"img-a": {"x": 0.4, "y": 0.55}}})
    focus = focus_from_context(job)
    assert focus["img-a"] == {"x": 0.4, "y": 0.55}
    assert focus_from_context("no-such-job") == {}
