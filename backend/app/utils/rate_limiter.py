import os
import time
import asyncio
import logging
from typing import Optional, Dict, Any, List
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type

logger = logging.getLogger("chronocut.utils.rate_limiter")


class RateLimiter:
    """Token-bucket style rate limiter for LLM API calls."""
    def __init__(self, rpm: int = 15, tpm: int = 1_000_000):
        self.rpm = rpm
        self.tpm = tpm
        self._request_times: List[float] = []
        self._token_usage: List[tuple[float, int]] = []

    def _cleanup_old_entries(self, now: float):
        cutoff_minute = now - 60
        cutoff_day = now - 86400

        self._request_times = [t for t in self._request_times if t > cutoff_minute]
        self._token_usage = [(t, tokens) for t, tokens in self._token_usage if t > cutoff_day]

    async def acquire(self, estimated_tokens: int = 1000) -> bool:
        now = time.time()
        self._cleanup_old_entries(now)

        if len(self._request_times) >= self.rpm:
            sleep_time = 60 - (now - self._request_times[0])
            if sleep_time > 0:
                logger.warning(f"Rate limit: sleeping {sleep_time:.1f}s (RPM limit {self.rpm})")
                await asyncio.sleep(sleep_time + 0.1)
                self._cleanup_old_entries(time.time())

        day_tokens = sum(tokens for _, tokens in self._token_usage)
        if day_tokens + estimated_tokens > self.tpm:
            logger.warning(f"Daily token limit approached: {day_tokens}/{self.tpm}")
            return False

        self._request_times.append(time.time())
        self._token_usage.append((time.time(), estimated_tokens))
        return True

    def get_stats(self) -> Dict[str, Any]:
        now = time.time()
        self._cleanup_old_entries(now)
        return {
            "requests_last_minute": len(self._request_times),
            "rpm_limit": self.rpm,
            "tokens_today": sum(t for _, t in self._token_usage),
            "tpm_limit": self.tpm,
        }


_rate_limiter: Optional[RateLimiter] = None


def get_rate_limiter() -> RateLimiter:
    global _rate_limiter
    if _rate_limiter is None:
        _rate_limiter = RateLimiter(rpm=15, tpm=1_000_000)
    return _rate_limiter


def with_rate_limit(estimated_tokens: int = 1000):
    """Decorator that adds rate limiting and exponential backoff for LLM API calls."""
    def decorator(func):
        @retry(
            stop=stop_after_attempt(5),
            wait=wait_exponential(multiplier=1, min=2, max=60),
            retry=retry_if_exception_type(Exception),
            before_sleep=lambda retry_state: logger.warning(
                f"Retry {retry_state.attempt_number}/5 after {retry_state.outcome.exception()}"
            ),
        )
        async def wrapper(*args, **kwargs):
            limiter = get_rate_limiter()
            success = await limiter.acquire(estimated_tokens)
            if not success:
                raise RuntimeError("Daily token limit exceeded")
            try:
                return await func(*args, **kwargs)
            except Exception:
                raise
        return wrapper
    return decorator
