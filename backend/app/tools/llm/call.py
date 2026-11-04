import asyncio
import json
import logging
import time
import re
from typing import Optional, List, Dict, Any

from app.config import settings, text_model_for
from app.tools.llm.scorer import score_provider
from app.tools.llm.cache import LLMCache
from app.tools.llm.governor import check_budget, record_call, estimate_cost_cents, BudgetExceededError
from app.utils.rate_limiter import get_rate_limiter

logger = logging.getLogger("chronocut.tools.llm.call")

# Global concurrency semaphore so concurrent BackgroundTasks don't burst the
# provider rate budget.
_gen_semaphore: Optional[asyncio.Semaphore] = None


def _get_semaphore() -> asyncio.Semaphore:
    global _gen_semaphore
    if _gen_semaphore is None:
        _gen_semaphore = asyncio.Semaphore(4)
    return _gen_semaphore


def _is_quota_error(e: Exception) -> bool:
    """Version-agnostic 429 / quota detection."""
    if e is None:
        return False
    msg = " ".join(str(e).lower().split())
    return ("429" in msg or "resource_exhausted" in msg
            or "quota" in msg or "rate" in msg and "exceeded" in msg
            or "too many requests" in msg)


def _parse_retry_delay(e: Exception) -> Optional[float]:
    """Best-effort extraction of a Retry-After / RetryInfo delay (seconds)."""
    import re as _re
    msg = str(e)
    m = _re.search(r"seconds\s*[:=]\s*(\d+)", msg)
    if m:
        try:
            return float(m.group(1))
        except ValueError:
            return None
    m = _re.search(r"retry[-_]?after[=:\s]+(\d+)", msg, _re.IGNORECASE)
    if m:
        try:
            return float(m.group(1))
        except ValueError:
            return None
    return None


def _sanity_check_json(obj: Dict[str, Any], *, require_keys: Optional[List[str]] = None) -> None:
    """Raise ValueError if the parsed JSON lacks obvious structure. Used to force
    a retry instead of caching an invalid blob."""
    if not isinstance(obj, dict):
        raise ValueError("LLM returned non-object JSON")
    if require_keys:
        missing = [k for k in require_keys if k not in obj]
        if missing:
            raise ValueError(f"LLM JSON missing keys: {missing}")


def _media_hash(media: Optional[List[Dict[str, Any]]]) -> List[str]:
    from app.services.firestore_service import sha256_bytes
    out = []
    for m in (media or []):
        out.append(sha256_bytes(m["data"]))
    return out


# In-flight dedupe. Concurrent identical prompts (same cache_key) share one
# in-flight request instead of bursting the rate budget. Keyed by LLMCache key.
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


async def _provider_network_call(
    provider_name: str,
    prompt: str,
    system: Optional[str],
    *,
    agent: str,
    tool: str,
    temperature: float,
    max_output_tokens: int,
    media: Optional[List[Dict[str, Any]]],
    json_mode: bool,
) -> str:
    """Configured-provider network path (structured output on json_mode;
    retries inside the provider)."""
    from app.tools.llm.provider import get_provider  # lightweight import guard

    provider = get_provider(provider_name)
    schema = {"name": "chronocut_response", "schema": {"type": "object"}} if json_mode else None
    sem = _get_semaphore()
    limiter = get_rate_limiter()
    est_tokens = max(200, len(prompt) // 3 + max_output_tokens)
    await limiter.acquire(est_tokens)

    async def _run():
        async with sem:
            return await provider.generate(
                prompt=prompt,
                system=system,
                schema=schema,
                media=media,
                temperature=temperature,
                max_tokens=max_output_tokens,
            )

    text = await _run()
    if not text:
        raise RuntimeError("provider call returned empty completion")
    return text


def _provider_ready(provider_name: str) -> bool:
    """True when a provider slot has the credentials it needs.

    The first-party Meta provider requires MODEL_API_KEY/META_API_KEY;
    OpenRouter requires OPENROUTER_API_KEY; Baseten requires BASETEN_API_KEY;
    a local OpenAI-compatible endpoint is keyless by design.
    """
    name = (provider_name or "").strip().lower()
    if name == "local":
        return True
    if name == "baseten":
        return bool((settings.BASETEN_API_KEY or "").strip())
    if name == "openrouter":
        return bool((settings.OPENROUTER_API_KEY or "").strip())
    return bool((settings.provider_api_key or "").strip())


async def scored_llm_call(
    prompt: str,
    system: Optional[str] = None,
    *,
    job_id: Optional[str] = None,
    agent: str = "orchestrator",
    tool: str = "llm",
    temperature: float = 0.7,
    max_output_tokens: int = 2048,
    media: Optional[List[Dict[str, Any]]] = None,
    json_mode: bool = False,
    use_cache: bool = True,
    provider: Optional[str] = None,
) -> str:
    """Single, governed, cached provider entrypoint used by every agent.

    Primary: the configured provider (Meta Model API, muse-spark-1.3).
    On failure, falls through ``LLM_FALLBACK_PROVIDERS`` (default: OpenRouter
    serving meta/muse-spark-open) — every slot serves a Meta model; Llama is
    never used. Slots without credentials are skipped at runtime.

    Keeps the existing cache, budget guard, in-flight coalescing, and cost
    ledger behavior identical across providers.
    """
    provider_name = (provider or settings.LLM_PROVIDER or "meta").strip().lower()
    model_field = text_model_for(provider_name)
    model = getattr(settings, model_field) if model_field else settings.META_TEXT_MODEL

    # Resilience: when the configured provider has no credentials, never
    # silently fall back to another model — degrade to deterministic templates
    # instead (the planner/director already handle that path).
    if not _provider_ready(provider_name):
        raise RuntimeError(
            f"LLM provider '{provider_name}' is not configured; deterministic fallback engaged"
        )

    media_hashes = _media_hash(media)
    cache_key = LLMCache.key(f"{provider_name}:{system or ''}", prompt, temperature, model, media_hashes)

    if use_cache:
        cached = LLMCache.get(cache_key)
        if cached is not None:
            record_call(job_id, agent=agent, tool=tool, model=model,
                        prompt_tokens=0, completion_tokens=0, cost_cents=0.0,
                        cached=True, duration_ms=0)
            logger.info(f"LLM cache HIT for {agent}/{tool}")
            return cached

    # Provider scoring (lightweight classification only).
    _ = score_provider(agent, len(prompt) // 4)

    # Estimate + budget guard.
    est_tokens = max(200, len(prompt) // 3 + max_output_tokens)
    est_cost = _meta_estimated_cost(est_tokens, max_output_tokens)
    try:
        check_budget(job_id, est_cost)
    except BudgetExceededError:
        raise

    t0 = time.time()
    used_provider, used_model = provider_name, model

    async def _primary():
        return await _provider_network_call(
            provider_name, prompt, system,
            agent=agent, tool=tool, temperature=temperature,
            max_output_tokens=max_output_tokens, media=media, json_mode=json_mode,
        )

    try:
        text = await _coalesce(cache_key, _primary)
    except Exception as primary_error:
        logger.error(f"provider call failed ({agent}/{tool}, provider={provider_name}): {primary_error}")
        if use_cache:
            cached = LLMCache.get(cache_key)
            if cached is not None:
                return cached

        # Automatic failover chain (disabled entirely with
        # ENABLE_LLM_FAILOVER=false): when the primary provider errors, retry
        # the same call through the configured slots in order
        # (OpenRouter → Baseten → local — every slot serves a Meta Muse model).
        # json_mode and media are dropped for the hops: the OpenAI-compatible
        # hosts have no structured-output guarantee, and a retry must not
        # depend on re-uploading attachments; caller-side parsing already
        # tolerates narrative text. Slots without credentials (or equal to the
        # failing primary) are skipped.
        text = None
        raised = primary_error
        for fb in settings.llm_fallback_providers:
            if fb == provider_name or not _provider_ready(fb):
                continue
            try:
                fb_model = getattr(settings, text_model_for(fb)) if text_model_for(fb) else settings.META_TEXT_MODEL
                logger.warning(
                    f"{provider_name} provider unavailable ({agent}/{tool}); "
                    f"failing over to {fb} ({fb_model})"
                )
                text = await _provider_network_call(
                    fb, prompt, system,
                    agent=agent, tool=tool, temperature=temperature,
                    max_output_tokens=max_output_tokens, media=None,
                    json_mode=False,
                )
                used_provider, used_model = fb, fb_model
                break
            except Exception as fb_error:
                logger.error(f"{fb} failover also failed ({agent}/{tool}): {fb_error}")
                raised = fb_error
        if text is None:
            raise primary_error from raised

    duration_ms = int((time.time() - t0) * 1000)
    prompt_tokens = len(prompt) // 4 + sum(len(m["data"]) // 1000 for m in (media or []))
    completion_tokens = len(text) // 4
    # OpenRouter (muse-spark-open) and Meta Model API (muse-spark-1.3) are both
    # priced $1.25/M input, $4.25/M output; local inference costs nothing.
    is_free_host = used_provider in ("local",)
    cost_cents = 0.0 if is_free_host else _meta_estimated_cost(prompt_tokens, completion_tokens)
    record_call(job_id, agent=agent, tool=tool, model=used_model,
                prompt_tokens=prompt_tokens, completion_tokens=completion_tokens,
                cost_cents=cost_cents, cached=False, duration_ms=duration_ms)
    if use_cache:
        LLMCache.put(cache_key, text, used_model, prompt_tokens, completion_tokens, cost_cents)
    return text


def _meta_estimated_cost(prompt_tokens: int, completion_tokens: int) -> float:
    """Muse Spark pricing: $1.25 / 1M input, $4.25 / 1M output (to cents)."""
    in_cents = (prompt_tokens / 1_000_000.0) * 1.25 * 100.0
    out_cents = (completion_tokens / 1_000_000.0) * 4.25 * 100.0
    return round(in_cents + out_cents, 4)


async def scored_llm_json(
    prompt: str,
    system: Optional[str] = None,
    *,
    job_id: Optional[str] = None,
    agent: str = "orchestrator",
    tool: str = "llm",
    temperature: float = 0.7,
    max_output_tokens: int = 2048,
    media: Optional[List[Dict[str, Any]]] = None,
    use_cache: bool = True,
    require_keys: Optional[List[str]] = None,
    provider: Optional[str] = None,
) -> Dict[str, Any]:
    raw = await scored_llm_call(
        prompt, system, job_id=job_id, agent=agent, tool=tool,
        temperature=temperature, max_output_tokens=max_output_tokens,
        media=media, json_mode=True, use_cache=use_cache, provider=provider,
    )
    # Raise on invalid JSON so the caller (which already has a fallback
    # template) retries / degrades instead of caching a broken blob.
    obj = _parse_json(raw)
    if "raw" in obj:
        raise ValueError("LLM returned non-JSON content")
    _sanity_check_json(obj, require_keys=require_keys)
    return obj


async def scored_provider_json(provider: str, *args, **kwargs) -> Dict[str, Any]:
    """Explicit-provider JSON call (named alias for clarity at call sites)."""
    return await scored_llm_json(*args, provider=provider, **kwargs)


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
    """Startup health check: fail fast if the configured provider is unavailable.

    Probes the primary slot through the provider factory; every slot serves
    an OpenAI-compatible chat endpoint, so the ping is identical. A slot
    without credentials reports ok: True with a note (calls degrade to the
    failover chain / deterministic fallbacks) rather than failing startup.
    """
    provider_name = (settings.LLM_PROVIDER or "meta").strip().lower()
    from app.tools.llm.provider import get_provider
    import asyncio as _asyncio
    try:
        provider = get_provider(provider_name)
    except RuntimeError as e:
        return {"ok": True, "provider": provider_name,
                "model": settings.model_badge[1],
                "note": f"not configured ({e}); failover chain / deterministic fallbacks will be used"}
    try:
        text = await _asyncio.to_thread(
            lambda: provider._client.chat.completions.create(
                model=provider.default_model,
                messages=[{"role": "user", "content": "ping"}],
                max_tokens=8, temperature=0.0,
            )
        )
        return {"ok": True, "provider": provider_name,
                "model": provider.default_model,
                "reply": ((text.choices[0].message.content or "") or "").strip()[:20]}
    except Exception as e:
        return {"ok": False, "provider": provider_name,
                "model": provider.default_model, "error": str(e)}
