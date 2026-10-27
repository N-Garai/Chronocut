from app.config import settings
from app.tools.render.profiles import get_profile, _clamp_resolution, PROFILES

CAP = settings.MAX_RENDER_RESOLUTION  # 720 on the free tier (512MB OOM guard)


def test_clamp_keeps_small_within_cap():
    assert _clamp_resolution(640, 360) == (640, 360)


def test_clamp_shrinks_4k():
    w, h = _clamp_resolution(3840, 2160)
    assert max(w, h) <= CAP


def test_known_profile_dims_and_fps():
    p = get_profile("youtube_landscape")
    assert p.name == "youtube_landscape"
    assert p.fps == 30
    # Dimensions are always clamped to the free-tier cap (OOM guard).
    assert max(p.width, p.height) <= CAP


def test_every_profile_within_render_cap():
    for p in PROFILES.values():
        assert max(p.width, p.height) <= CAP
