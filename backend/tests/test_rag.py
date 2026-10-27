import asyncio

from app.services import rag as ragsvc
import app.tools.llm.embed as emb


def test_store_and_recall_similar():
    async def fake_embed(texts):
        return [[float(len(t)), 1.0, 0.0] for t in texts]

    original = emb.embed_texts
    emb.embed_texts = fake_embed
    try:
        asyncio.run(
            ragsvc.store_job_memory("ragA", "a dog story", {}, {"script": [{"text": "dogs"}]})
        )
        res = asyncio.run(ragsvc.find_similar("ragB", "a dog story", top_k=5))
    finally:
        emb.embed_texts = original

    assert any(r["job_id"] == "ragA" for r in res)
