from app.tools.llm.cache import LLMCache


def test_put_then_get_roundtrip():
    k = LLMCache.key("sys", "prompt", 0.5, "muse-spark-1.3")
    LLMCache.put(k, "hello-world", "muse-spark-1.3", 1, 2, 0.0)
    assert LLMCache.get(k) == "hello-world"


def test_get_missing_returns_none():
    assert LLMCache.get("definitely-missing-key-12345") is None
