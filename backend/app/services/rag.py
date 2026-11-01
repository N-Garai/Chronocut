import logging
import math
import re
from typing import Optional, Dict, Any, List

logger = logging.getLogger("chronocut.services.rag")

__all__ = ["store_job_memory", "find_similar", "store_successful_script"]


def _tokens(text: str) -> set:
    return set(re.findall(r"[a-z0-9]+", (text or "").lower()))


def _cosine(a: List[float], b: List[float]) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(x * x for x in b))
    return dot / (na * nb) if na and nb else 0.0


def _build_text(transcript: str, image_tags: Dict[str, Any], script: Dict[str, Any]) -> str:
    parts = [(transcript or "")]
    for v in (image_tags or {}).values():
        if isinstance(v, dict):
            parts.append(v.get("description", ""))
            parts.extend(v.get("objects", []) or [])
    for seg in (script or {}).get("script", []):
        parts.append(seg.get("text", ""))
    return " ".join(p for p in parts if p)[:6000]


async def store_job_memory(job_id: str, transcript: str, image_tags: Dict[str, Any],
                           script: Dict[str, Any]) -> None:
    """Persist a semantic memory of this job: embed + store the vector."""
    from app.services.firestore_service import JobStateService
    try:
        text = _build_text(transcript, image_tags, script)
        embedding: List[float] = []
        try:
            from app.tools.llm.embed import embed_texts
            emb = await embed_texts([text])
            embedding = emb[0] if emb else []
        except Exception as e:
            logger.warning(f"embedding failed for memory {job_id}: {e}")

        memory = {
            "job_id": job_id,
            "text": text[:4000],
            "embedding": embedding,
            "total_duration": script.get("total_duration_seconds"),
            "created_at": __import__("datetime").datetime.now(__import__("datetime").timezone.utc),
        }
        JobStateService.corpus_set("memory", job_id, memory)
    except Exception as e:
        logger.error(f"store_job_memory failed: {e}")


async def store_successful_script(script_hash: str, script: Dict[str, Any], job_id: str, profile: str) -> None:
    from app.services.firestore_service import JobStateService
    try:
        JobStateService.corpus_set("scripts", str(script_hash), {
            "script": script, "job_id": job_id, "video_profile": profile,
            "created_at": __import__("datetime").datetime.now(__import__("datetime").timezone.utc),
        })
    except Exception as e:
        logger.error(f"store_successful_script failed: {e}")


async def find_similar(job_id: str, query_text: str, top_k: int = 3) -> List[Dict[str, Any]]:
    """Recall past similar projects via cosine similarity over stored embeddings.

    Falls back to token-overlap similarity when embeddings are unavailable
    (e.g. no API key configured). Free-tier: embeddings use local hashing
    text-embedding model; vectors are stored in Firestore or the local JSON store.
    """
    from app.services.firestore_service import JobStateService
    try:
        items = JobStateService.corpus_list("memory", limit=200)
    except Exception as e:
        logger.error(f"corpus_list failed: {e}")
        items = []

    if not items:
        return []

    q_tokens = _tokens(query_text)
    try:
        from app.tools.llm.embed import embed_texts
        q_emb = await embed_texts([query_text])
        q_emb = q_emb[0] if q_emb else []
    except Exception:
        q_emb = []

    results = []
    for mem in items:
        if mem.get("job_id") == job_id:
            continue
        emb = mem.get("embedding") or []
        if q_emb and emb and len(q_emb) == len(emb):
            score = _cosine(q_emb, emb)
        else:
            # Token-overlap fallback.
            mem_tokens = _tokens(mem.get("text", ""))
            union = q_tokens | mem_tokens
            score = len(q_tokens & mem_tokens) / len(union) if union else 0.0
        if score > 0.02:
            results.append({
                "job_id": mem.get("job_id"),
                "similarity": round(score, 3),
                "snippet": (mem.get("text") or "")[:160],
            })
    results.sort(key=lambda r: r["similarity"], reverse=True)
    return results[:top_k]
