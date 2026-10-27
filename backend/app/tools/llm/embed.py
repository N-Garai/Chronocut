import asyncio
import logging
from typing import List, Optional

logger = logging.getLogger("chronocut.tools.llm.embed")

_EMBED_MODEL = "gemini-embedding-001"


async def _embed(client, model: str, texts: List[str]):
    """Version-agnostic embedding call.

    In google-genai, ``client.models.embed_content`` is a BLOCKING call (the async
    variant, when present, is ``embed_content_async``). Awaiting the sync result
    raises ``object EmbedContentResponse can't be used in 'await' expression``, so
    we mirror the generate_content pattern from call.py: prefer the async entry
    point, otherwise run the sync call in an executor.
    """
    from app.config import settings
    models = client.models
    if hasattr(models, "embed_content_async"):
        return await asyncio.wait_for(
            models.embed_content_async(model=model, contents=list(texts)),
            timeout=getattr(settings, "GEMINI_CALL_TIMEOUT", 60),
        )
    loop = asyncio.get_event_loop()
    return await asyncio.wait_for(
        loop.run_in_executor(
            None, lambda: models.embed_content(model=model, contents=list(texts))
        ),
        timeout=getattr(settings, "GEMINI_CALL_TIMEOUT", 60),
    )


async def embed_texts(texts: List[str], model: str = _EMBED_MODEL) -> List[List[float]]:
    """Embed texts with Gemini embeddings (free-tier, same API key as generation).

    Returns a list of float vectors aligned with `texts`. Returns [] on any
    failure (e.g. no API key) so callers can degrade gracefully.
    """
    if not texts:
        return []
    try:
        from app.tools.llm.call import _get_client
        client = _get_client()
    except Exception as e:
        logger.warning(f"embed_texts: client unavailable ({e})")
        return []

    try:
        resp = await _embed(client, model, texts)
        embeddings = getattr(resp, "embeddings", None)
        if not embeddings:
            return []
        return [list(getattr(e, "values", []) or []) for e in embeddings]
    except Exception as e:
        logger.warning(f"embed_texts failed: {e}")
        return []


def embed_texts_sync(texts: List[str], model: str = _EMBED_MODEL) -> List[List[float]]:
    """Synchronous twin of :func:`embed_texts` for use inside sync tool code.

    Gemini's SDK exposes both sync and async embed entrypoints, so this stays
    free of any running event loop. Returns [] on failure.
    """
    if not texts:
        return []
    try:
        from app.tools.llm.call import _get_client
        client = _get_client()
    except Exception as e:
        logger.warning(f"embed_texts_sync: client unavailable ({e})")
        return []

    try:
        resp = client.models.embed_content(model=model, contents=list(texts))
        embeddings = getattr(resp, "embeddings", None)
        if not embeddings:
            return []
        return [list(getattr(e, "values", []) or []) for e in embeddings]
    except Exception as e:
        logger.warning(f"embed_texts_sync failed: {e}")
        return []
