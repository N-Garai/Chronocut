from app.tools.footage.clip_search import store_footage, corpus_search


def test_store_and_token_search():
    store_footage(
        "stormy ocean waves at dusk",
        "http://example.com/stormy.mp4",
        "pexels",
        "video",
        "/tmp/stormy.png",
    )
    res = corpus_search("stormy ocean waves at dusk", top_k=3)
    assert isinstance(res, list)
    assert any(r.get("url") == "http://example.com/stormy.mp4" for r in res)
