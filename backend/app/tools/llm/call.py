import asyncio
import logging
import time
import json
import re
from typing import Optional, List, Dict, Any

from app.config import settings
from app.tools.llm.scorer import score_provider
from app.tools.llm.cache import LLMCache
from app.tools.llm.governor import check_budget, record_call, estimate_cost_cents, BudgetExceededError
from app.utils.rate_limiter import get_rate_limiter

try:
    from google.api_core.exceptions import ResourceExhausted
    HAS_GOOGLE_EXCEPTIONS = True
except ImportError:
    HAS_GOOGLE_EXCEPTIONS = False

logger = logging.getLogger("chronocut.tools.llm.call")

_client = None

# B3: global concurrency semaphore so concurrent BackgroundTasks don't burst the
# free-tier Gemini RPM budget.
_gemini_semaphore: Optional[asyncio.Semaphore] = None


def _get_semaphore() -> asyncio.Semaphore:
    global _gemini_semaphore
    if _gemini_semaphore is None:
        _gemini_semaphore = asyncio.Semaphore(4)
    return _gemini_semaphore


def _is_quota_error(e: Exception) -> bool:
    """Version-agnostic 429 / quota detection (the exact class differs across
    google-genai SDK versions)."""
    if e is None:
        return False
    if HAS_GOOGLE_EXCEPTIONS and isinstance(e, ResourceExhausted):
        return True
    msg = " ".join(str(e).lower().split())
    return ("429" in msg or "resource_exhausted" in msg
            or "quota" in msg or "rate" in msg and "exceeded" in msg
            or "too many requests" in msg)


def _parse_retry_delay(e: Exception) -> Optional[float]:
    """Best-effort extraction of a Retry-After / RetryInfo delay (seconds)."""
    import re as _re
    msg = str(e)
    # google.genai often embeds "retry_delay { seconds: N }" or seconds=N
    m = _re.search(r"seconds\s*[:=]\s*(\d+)", msg)
    if m:
        try:
            return float(m.group(1))
        except ValueError:
            return None
    # HTTP Retry-After header style
    m = _re.search(r"retry[-_]?after[=:\s]+(\d+)", msg, _re.IGNORECASE)
    if m:
        try:
            return float(m.group(1))
        except ValueError:
            return None
    return None


def _sanity_check_json(obj: Dict[str, Any], *, require_keys: Optional[List[str]] = None) -> None:
    """Raise ValueError if the parsed JSON lacks obvious structure. Used to force
    a retry instead of caching an invalid blob (A4)."""
    if not isinstance(obj, dict):
        raise ValueError("LLM returned non-object JSON")
    if require_keys:
        missing = [k for k in require_keys if k not in obj]
        if missing:
            raise ValueError(f"LLM JSON missing keys: {missing}")


def _get_client():
    global _client
    if _client is None:
        try:
            from google import genai
            from google.genai import types  # noqa: F401
        except ImportError as e:
            raise RuntimeError("google-genai is required (provided by google-adk).") from e
        api_key = settings.GOOGLE_API_KEY
        if not api_key:
            raise RuntimeError("GOOGLE_API_KEY is not configured.")
        _client = genai.Client(api_key=api_key)
    return _client


def _media_hash(media: Optional[List[Dict[str, Any]]]) -> List[str]:
    from app.services.firestore_service import sha256_bytes
    out = []
    for m in (media or []):
        out.append(sha256_bytes(m["data"]))
    return out


def _build_contents(prompt: str, media: Optional[List[Dict[str, Any]]]):
    from google.genai import types
    parts = []
    for m in (media or []):
        parts.append(types.Part.from_bytes(data=m["data"], mime_type=m["mime_type"]))
    parts.append(types.Part.from_text(text=prompt))
    return parts


def _extract_text(response) -> str:
    try:
        if getattr(response, "text", None):
            return response.text
        if response.candidates and response.candidates[0].content.parts:
            return "".join(p.text or "" for p in response.candidates[0].content.parts)
    except Exception:
        pass
    return ""


async def _generate_content(client, model, contents, config):
    """Version-agnostic Gemini generation.

    ``google-genai`` < 2.x exposes ``generate_content_async``; >= 2.x removed
    it and made ``generate_content`` a blocking call. Support both runtimes so a
    single code path works on every deployed SDK version.
    """
    models = client.models
    if hasattr(models, "generate_content_async"):
        coro = models.generate_content_async(model=model, contents=contents, config=config)
        # B3: bound every real Gemini call with a per-call timeout.
        return await asyncio.wait_for(coro, timeout=settings.GEMINI_CALL_TIMEOUT)
    loop = asyncio.get_event_loop()
    # Sync path: wait_for cannot cancel the executor work, but it bounds our wait.
    return await asyncio.wait_for(
        loop.run_in_executor(
            None, lambda: models.generate_content(model=model, contents=contents, config=config)
        ),
        timeout=settings.GEMINI_CALL_TIMEOUT,
    )


# B4: in-flight dedupe. Concurrent identical prompts (same cache_key) share one
# in-flight request instead of bursting the RPM budget. Keyed by LLMCache key.
_in_flight: Dict[str, "asyncio.Future"] = {}


async def _coalesce(cache_key: str, coro_fn):
    loop = asyncio.get_event_loop()
    existing = _in_flight.get(cache_key)
    if existing is not None and not existing.done():
        return await asyncio.shield(existing)
    fut: "asyncio.Future" = loop.create_future()
    _in_flight[cache_key] = fut
    try:
        result = await coro_fn()
        if not fut.done():
            fut.set_result(result)
        return result
    except Exception as e:
        if not fut.done():
            fut.set_exception(e)
        raise
    finally:
        if _in_flight.get(cache_key) is fut:
            _in_flight.pop(cache_key, None)


async def scored_gemini_call(
    prompt: str,
    system: Optional[str] = None,
    *,
    job_id: Optional[str] = None,
    agent: str = "orchestrator",
    tool: str = "gemini",
    temperature: float = 0.7,
    max_output_tokens: int = 2048,
    media: Optional[List[Dict[str, Any]]] = None,
    json_mode: bool = False,
    use_cache: bool = True,
) -> str:
    """Single, governed, cached Gemini entrypoint used by every agent."""
    model = settings.GEMINI_MODEL
    media_hashes = _media_hash(media)
    cache_key = LLMCache.key(system or "", prompt, temperature, model, media_hashes)

    if use_cache:
        cached = LLMCache.get(cache_key)
        if cached is not None:
            record_call(job_id, agent=agent, tool=tool, model=model,
                        prompt_tokens=0, completion_tokens=0, cost_cents=0.0,
                        cached=True, duration_ms=0)
            logger.info(f"LLM cache HIT for {agent}/{tool}")
            return cached

    # Provider scoring (free-tier: Flash only).
    _ = score_provider(agent, len(prompt) // 4)

    # Estimate + budget guard (assume small call).
    est_tokens = max(200, len(prompt) // 3 + max_output_tokens)
    try:
        check_budget(job_id, estimate_cost_cents(est_tokens, max_output_tokens))
    except BudgetExceededError:
        raise

    client = _get_client()
    t0 = time.time()
    models_to_try = [model] + settings.gemini_fallback_models
    max_retries = max(1, settings.GEMINI_MAX_RETRIES)
    limiter = get_rate_limiter()
    sem = _get_semaphore()

    async def _do_generate() -> str:
        # Resilience: the configured GEMINI_MODEL may be unavailable/invalid
        # (e.g. a typo like "gemini-3.5-flash"). Try it, then configured fallbacks,
        # so a bad model name never silently degrades every agent to its template.
        last_err = None
        for attempt in range(max_retries):
            for attempt_model in models_to_try:
                try:
                    # B1: throttle every real Gemini call to the RPM budget.
                    await limiter.acquire(est_tokens)
                    from google.genai import types
                    config = types.GenerateContentConfig(
                        temperature=temperature,
                        max_output_tokens=max_output_tokens,
                    )
                    if system:
                        config.system_instruction = system
                    if json_mode:
                        config.response_mime_type = "application/json"

                    async with sem:
                        response = await _generate_content(
                            client, attempt_model, _build_contents(prompt, media), config
                        )
                    text = _extract_text(response)
                    if text:
                        return text
                except Exception as e:  # noqa: BLE001
                    last_err = e
                    if _is_quota_error(e):
                        # B2: 429-aware exponential backoff, honor Retry-After.
                        delay = _parse_retry_delay(e) or (2 ** attempt * 5)
                        logger.warning(
                            f"Gemini quota/429 ({agent}/{tool}, model={attempt_model}); "
                            f"backing off {delay:.1f}s"
                        )
                        await asyncio.sleep(min(delay, 60))
                        continue
                    logger.warning(f"Gemini model '{attempt_model}' failed ({agent}/{tool}): {e}")
            # All models failed this attempt; back off before the next bounded retry.
            if attempt < max_retries - 1:
                await asyncio.sleep(min(2 ** attempt * 3, 30))
        if last_err is not None:
            raise last_err
        raise RuntimeError("Gemini call failed with no models available")

    # B4: concurrent identical prompts coalesce into a single in-flight request.
    try:
        text = await _coalesce(cache_key, _do_generate)
    except Exception as e:
        logger.error(f"Gemini call failed ({agent}/{tool}): {e}")
        cached = LLMCache.get(cache_key)
        if cached is not None:
            return cached
        raise

    duration_ms = int((time.time() - t0) * 1000)
    # Rough token accounting.
    prompt_tokens = len(prompt) // 4 + sum(len(m["data"]) // 1000 for m in (media or []))
    completion_tokens = len(text) // 4
    cost_cents = estimate_cost_cents(prompt_tokens, completion_tokens)
    record_call(job_id, agent=agent, tool=tool, model=model,
                prompt_tokens=prompt_tokens, completion_tokens=completion_tokens,
                cost_cents=cost_cents, cached=False, duration_ms=duration_ms)
    if use_cache:
        LLMCache.put(cache_key, text, model, prompt_tokens, completion_tokens, cost_cents)
    return text


async def scored_gemini_json(
    prompt: str,
    system: Optional[str] = None,
    *,
    job_id: Optional[str] = None,
    agent: str = "orchestrator",
    tool: str = "gemini",
    temperature: float = 0.7,
    max_output_tokens: int = 2048,
    media: Optional[List[Dict[str, Any]]] = None,
    use_cache: bool = True,
    require_keys: Optional[List[str]] = None,
) -> Dict[str, Any]:
    raw = await scored_gemini_call(
        prompt, system, job_id=job_id, agent=agent, tool=tool,
        temperature=temperature, max_output_tokens=max_output_tokens,
        media=media, json_mode=True, use_cache=use_cache,
    )
    # A4: raise on invalid JSON so the caller (which already has a fallback
    # template) retries / degrades instead of caching a broken blob.
    obj = _parse_json(raw)
    if "raw" in obj:
        raise ValueError("LLM returned non-JSON content")
    _sanity_check_json(obj, require_keys=require_keys)
    return obj


def _parse_json(raw: str) -> Dict[str, Any]:
    if not raw:
        return {"raw": raw}
    # Models often wrap JSON in markdown fences (```json ... ```) or add prose.
    # Strip fences first, then try the raw text, then extract a {...} block.
    cleaned = re.sub(r"^```(?:json)?\s*|\s*```$", "", raw.strip(), flags=re.IGNORECASE)
    for candidate in (raw, cleaned):
        try:
            return json.loads(candidate)
        except json.JSONDecodeError:
            pass
    m = re.search(r"\{.*\}", raw, re.DOTALL)
    if m:
        try:
            return json.loads(m.group())
        except json.JSONDecodeError:
            pass
    return {"raw": raw}


async def validate_model() -> Dict[str, Any]:
    """Startup health check: fail fast if the model is unavailable."""
    try:
        client = _get_client()
        from google.genai import types
        resp = await _generate_content(
            client, settings.GEMINI_MODEL,
            [types.Part.from_text(text="ping")],
            types.GenerateContentConfig(max_output_tokens=8),
        )
        return {"ok": True, "model": settings.GEMINI_MODEL, "reply": (resp.text or "").strip()[:20]}
    except Exception as e:
        return {"ok": False, "model": settings.GEMINI_MODEL, "error": str(e)}
