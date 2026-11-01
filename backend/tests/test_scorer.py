from app.tools.llm.scorer import score_provider, provider_menu


def test_score_shape():
    r = score_provider("write documentary script", 1000)
    assert r["provider"] == "meta"
    assert "score" in r and "cost_cents" in r and "fallback" in r
    assert r["cost_cents"] == 0.0


def test_fallback_is_cache_when_pro_disabled():
    r = score_provider("anything", 1)
    assert r["fallback"] == "cache_or_error"


def test_provider_menu_is_list():
    assert isinstance(provider_menu(), list)
