import logging
from datetime import datetime, timezone, timedelta
from typing import Optional

from app.services.firestore_service import JobStateService, sha256_text

logger = logging.getLogger("chronocut.tools.llm.cache")


class LLMCache:
    """SHA256-keyed response cache backed by Firestore /corpus/llm_cache."""

    COLLECTION = "llm_cache"

    @staticmethod
    def key(system: str, prompt: str, temperature: float, model: str, media_hashes: Optional[list] = None) -> str:
        payload = "|".join([
            system or "", prompt, str(temperature), model,
            ",".join(media_hashes or []),
        ])
        return sha256_text(payload)

    @classmethod
    def get(cls, cache_key: str) -> Optional[str]:
        try:
            doc = JobStateService.corpus_get(cls.COLLECTION, cache_key)
            if not doc:
                return None
            expires = doc.get("expires_at")
            if expires:
                if isinstance(expires, str):
                    expires = datetime.fromisoformat(expires)
                if expires < datetime.now(timezone.utc):
                    return None
            return doc.get("response")
        except Exception as e:
            logger.error(f"LLM cache get failed: {e}")
            return None

    @classmethod
    def put(cls, cache_key: str, response: str, model: str, prompt_tokens: int, completion_tokens: int, cost_cents: float) -> None:
        try:
            from app.config import settings
            ttl_days = settings.LLM_CACHE_TTL_DAYS
            expires = datetime.now(timezone.utc) + timedelta(days=ttl_days)
            JobStateService.corpus_set(cls.COLLECTION, cache_key, {
                "response": response,
                "model": model,
                "prompt_tokens": prompt_tokens,
                "completion_tokens": completion_tokens,
                "cost_cents": cost_cents,
                "created_at": datetime.now(timezone.utc),
                "expires_at": expires,
            })
        except Exception as e:
            logger.error(f"LLM cache put failed: {e}")
