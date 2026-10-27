from app.tools.registry import registry


def test_discover_runs_and_exposes_capabilities():
    registry.discover()  # must not raise
    env = registry.support_envelope()
    assert isinstance(env, dict) and len(env) > 0
    # Key capabilities the UI/agents rely on are advertised live.
    for cap in ("footage_search", "script", "render", "review", "rag"):
        assert cap in env


def test_provider_menu_is_list():
    registry.discover()
    assert isinstance(registry.provider_menu(), list)
