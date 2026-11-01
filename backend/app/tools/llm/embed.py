import logging
import hashlib
from typing import List

logger = logging.getLogger("chronocut.tools.llm.embed")

_EMBED_DIM = 256


def _embed_text(text: str) -> List[float]:
    """Deterministic hashing-trick embedding (no external model, no API key).

    Stable across processes and degrades gracefully, keeping corpus/RAG recall
    working without any provider credentials or model downloads.
    """
    vec = [0.0] * _EMBED_DIM
    for token in (text or "").lower().split():
        h = int(hashlib.sha256(token.encode("utf-8")).hexdigest(), 16)
        vec[h % _EMBED_DIM] += 1.0
    norm = sum(v * v for v in vec) ** 0.5 or 1.0
    return [v / norm for v in vec]


async def embed_texts(texts: List[str], model: str = "local-hashing") -> List[List[float]]:
    """Embed texts with a local deterministic hashing embedding.

    Returns a list of float vectors aligned with `texts`. Returns [] on any
    failure so callers can degrade gracefully. No provider credentials or
    external model downloads are required.
    """
    if not texts:
        return []
    try:
        return [_embed_text(t) for t in texts]
    except Exception as e:
        logger.warning(f"embed_texts failed: {e}")
        return []


def embed_texts_sync(texts: List[str], model: str = "local-hashing") -> List[List[float]]:
    """Synchronous twin of :func:`embed_texts` for use inside sync tool code.

    Returns a list of float vectors aligned with `texts`. Returns [] on failure.
    """
    if not texts:
        return []
    try:
        return [_embed_text(t) for t in texts]
    except Exception as e:
        logger.warning(f"embed_texts_sync failed: {e}")
        return []
