from app.config import settings
from app.tools.registry import registry


def test_discover_runs_and_exposes_capabilities():
    registry.discover()  # must not raise
    env = registry.support_envelope()
    assert isinstance(env, dict) and len(env) > 0
    # Key capabilities the UI/agents rely on are advertised live.
    for cap in ("text", "audio_transcribe", "image_tag", "footage_search", "script",
                "render", "review", "edl", "rag"):
        assert cap in env


def test_envelope_reports_the_configured_provider_and_model():
    registry.discover()
    env = registry.support_envelope()
    provider, model = settings.model_badge
    assert env["text"]["provider"] == provider
    assert env["text"]["model"] == model
    # The configured text/vision model is the one advertised for tagging.
    assert env["image_tag"]["model"] == model


def test_envelope_reports_the_declared_modalities():
    registry.discover()
    env = registry.support_envelope()
    providers = env["audio_transcribe"]["providers"]
    if provider_is_meta_with_key():
        assert providers == ["meta_asr"]
    else:
        assert providers == []
    # Only Meta models may be called at runtime — no local fallback ASR.
    assert env["video_understanding"]["enabled"] == bool(
        settings.LLM_PROVIDER == "meta" and settings.provider_api_key)
    assert env["image_gen"]["enabled"] == (settings.image_gen_provider != "off")


def test_envelope_lists_the_real_render_profiles():
    registry.discover()
    env = registry.support_envelope()
    from app.tools.render.profiles import PROFILES
    assert env["render"]["profiles"] == list(PROFILES.keys())
    assert "preview_480" in env["render"]["profiles"]


def test_provider_menu_is_list():
    registry.discover()
    assert isinstance(registry.provider_menu(), list)


def provider_is_meta_with_key() -> bool:
    return settings.LLM_PROVIDER == "meta" and bool(settings.provider_api_key)
