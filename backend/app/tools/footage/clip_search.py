import logging
import math
from typing import List, Dict, Any, Optional

logger = logging.getLogger("chronocut.tools.footage.clip_search")

# Collection used by the searchable footage corpus (M6). Stored in Firestore
# (free tier) or the local JSON store via JobStateService.
_COLLECTION = "footage_cache"
_THRESHOLD = 0.74


def _cosine(a: List[float], b: List[float]) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    return dot / (na * nb) if na and nb else 0.0


def corpus_search(query: str, top_k: int = 5, modality: str = None) -> List[Dict[str, Any]]:
    """Semantic search over the footage corpus using Gemini text embeddings.

    Returns the best matching cached visuals (URLs). Falls back to a token
    overlap score when embeddings are unavailable (e.g. no API key).
    """
    from app.services.firestore_service import JobStateService
    try:
        items = JobStateService.corpus_list(_COLLECTION, limit=500)
    except Exception as e:
        logger.warning(f"corpus_search: list failed: {e}")
        items = []
    if not items:
        return []

    q_tokens = set(query.lower().split())
    try:
        from app.tools.llm.embed import embed_texts_sync
        q_emb = embed_texts_sync([query])
        q_emb = q_emb[0] if q_emb else []
    except Exception:
        q_emb = []

    scored = []
    for it in items:
        if modality and it.get("modality") and it.get("modality") != modality:
            continue
        emb = it.get("embedding") or []
        if q_emb and emb and len(q_emb) == len(emb):
            score = _cosine(q_emb, emb)
        else:
            tt = set((it.get("query") or "").lower().split())
            union = q_tokens | tt
            score = len(q_tokens & tt) / len(union) if union else 0.0
        if score >= _THRESHOLD:
            scored.append((score, it))
    scored.sort(key=lambda x: x[0], reverse=True)

    out = []
    for score, it in scored[:top_k]:
        out.append({
            "id": it.get("_doc_id"),
            "url": it.get("url"),
            "file": None,
            "score": float(score),
            "source": it.get("source"),
            "title": it.get("query"),
        })
    return out


def store_footage(query: str, url: str, source: str, modality: str, local_path: str = None) -> None:
    """Persist a resolved visual into the semantic footage corpus (M6)."""
    from app.services.firestore_service import JobStateService, sha256_text
    try:
        from app.tools.llm.embed import embed_texts_sync
        emb = embed_texts_sync([query])
        embedding = emb[0] if emb else []
    except Exception as e:
        logger.warning(f"store_footage: embed failed: {e}")
        embedding = []

    try:
        JobStateService.corpus_set("footage_cache", sha256_text(url), {
            "query": query,
            "url": url,
            "source": source,
            "modality": modality,
            "local_path": local_path,
            "embedding": embedding,
        })
    except Exception as e:
        logger.warning(f"store_footage failed: {e}")
