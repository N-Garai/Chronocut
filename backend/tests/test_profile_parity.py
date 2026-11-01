"""Profile parity: the names the frontend exposes must exist (and render) on
the backend. Guard against the class of drift where a UI adds a profile the
schema/compiler doesn't know.
"""
import re
from pathlib import Path

import pytest

from app.edl.schema import ALLOWED_PROFILE_RESOLUTIONS
from app.tools.render.profiles import PROFILES, get_profile

FRONTEND_STUDIO = Path(__file__).resolve().parents[2] / (
    "frontend/src/components/Studio.jsx")


def _frontend_profile_names():
    if not FRONTEND_STUDIO.exists():        # never skip silently in CI
        pytest.fail(f"frontend Studio page missing: {FRONTEND_STUDIO}")
    src = FRONTEND_STUDIO.read_text(encoding="utf-8")
    found = set(re.findall(r"'((?:youtube|instagram|reels|shorts|square|preview)"
                           r"[_a-z0-9]*)'", src))
    names = {REVERSE.get(n, n) for n in found}
    return names


REVERSE = {
    # copy shown in the UI ("Reels 9:16", "IG Square 1:1") vs the schema keys
    "reels": "instagram_portrait",
    "shorts": "instagram_portrait",
    "square": "instagram_square",
}


def test_every_frontend_profile_exists_in_the_backend_schema():
    names = _frontend_profile_names()
    assert names, "no profile names discovered in the frontend"
    missing = names - set(ALLOWED_PROFILE_RESOLUTIONS)
    assert not missing, f"frontend exposes profiles the EDL schema lacks: {missing}"


def test_every_frontend_profile_compiles_for_render():
    for p in _frontend_profile_names():
        prof = get_profile(p)               # raises if the render registry lacks it
        assert prof.name == p
        assert prof.width > 0 and prof.height > 0 and prof.fps > 0


def test_render_registry_supersets_the_schema_profiles():
    # the render ladder may offer extra host-grade profiles (4K, TikTok, ...)
    # but can never lack one the EDL schema can express
    missing = set(ALLOWED_PROFILE_RESOLUTIONS) - set(PROFILES)
    assert not missing, f"render registry lacks schema profiles: {missing}"
    # profile lookup degrades to the default for unknown names, never KeyError
    assert get_profile("not_a_profile").name == "youtube_landscape"


def test_common_apis_agree_on_the_profile_set():
    # the planner's schema enum and materialize pipes share ALLOWED_PROFILE_RESOLUTIONS
    from app.agents.planner import _LLM_SYSTEM, _llm_prompt
    from app.edl.schema import normalize_edl
    prof = "youtube_1080"
    edl = {
        "version": "1.0", "revision": 1,
        "project": {"job_id": "j-parity-1", "profile": prof, "duration": 1.0},
        "sources": [], "tracks": [],
    }
    normalized = normalize_edl(edl)
    assert normalized["project"]["profile"] == prof
    assert prof in _llm_prompt("switch to 1080p", {})
