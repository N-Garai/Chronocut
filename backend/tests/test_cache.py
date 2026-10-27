from app.tools.llm.cache import LLMCache


def test_put_then_get_roundtrip():
    k = LLMCache.key("sys", "prompt", 0.5, "gemini-flash")
    LLMCache.put(k, "hello-world", "gemini-flash", 1, 2, 0.0)
    assert LLMCache.get(k) == "hello-world"


def test_get_missing_returns_none():
    assert LLMCache.get("definitely-missing-key-12345") is None
