import logging
from typing import Optional

from app.services.firestore_service import JobStateService
from app.config import settings

logger = logging.getLogger("chronocut.tools.llm.governor")


class BudgetExceededError(RuntimeError):
    pass


# Per-model pricing ($ per 1M tokens). Meta Model API (Muse Spark Open):
# $1.25 input / $4.25 output. Local Open-weight endpoints are treated at the
# same Muse rate for budget purposes (no provider charge).
_PRICING = {
    "input_usd_per_m": {"muse": 1.25, "default": 1.25},
    "output_usd_per_m": {"muse": 4.25, "default": 4.25},
}

# Speech-to-text: $0.18 per audio-hour.
_USD_PER_AUDIO_HOUR = 0.18

# Image segmentation: $2.50 per 1k images.
_USD_PER_1K_SEGMENTATIONS = 2.50


def _is_muse(model: Optional[str]) -> bool:
    return bool(model) and "muse" in str(model).lower()


def estimate_cost_cents(prompt_tokens: int, completion_tokens: int, model: Optional[str] = None) -> float:
    """Provider-aware cost estimate converted to cents."""
    if _is_muse(model):
        in_usd = (prompt_tokens / 1_000_000.0) * _PRICING["input_usd_per_m"]["muse"]
        out_usd = (completion_tokens / 1_000_000.0) * _PRICING["output_usd_per_m"]["muse"]
    else:
        in_usd = (prompt_tokens / 1_000_000.0) * _PRICING["input_usd_per_m"]["default"]
        out_usd = (completion_tokens / 1_000_000.0) * _PRICING["output_usd_per_m"]["default"]
    return round(in_usd * 100.0 + out_usd * 100.0, 4)


def asr_cost_cents(audio_seconds: float) -> float:
    """Cost of transcription seconds at the documented per-hour rate."""
    return round((max(audio_seconds, 0.0) / 3600.0) * _USD_PER_AUDIO_HOUR * 100.0, 4)


def segmentation_cost_cents(images: int) -> float:
    return round((max(images, 0) / 1000.0) * _USD_PER_1K_SEGMENTATIONS * 100.0, 4)


def check_budget(job_id: Optional[str], estimated_cents: float) -> None:
    """Raise BudgetExceededError if the per-job cap would be exceeded."""
    if not job_id:
        return
    job = JobStateService.get_job(job_id) or {}
    spent = float(job.get("cost_cents", 0.0))
    cap = float(settings.PER_JOB_COST_CAP_CENTS)
    if spent + estimated_cents > cap:
        logger.warning(f"Budget cap hit for job {job_id}: {spent}+{estimated_cents} > {cap}")
        raise BudgetExceededError(
            f"Per-job cost cap of {cap} cents exceeded (spent {spent}, needed {estimated_cents})."
        )


def record_call(
    job_id: Optional[str],
    *,
    agent: str,
    tool: str,
    model: str,
    prompt_tokens: int,
    completion_tokens: int,
    cost_cents: float,
    cached: bool,
    duration_ms: int,
) -> None:
    if not job_id:
        return
    JobStateService.ledger_write(job_id, {
        "agent": agent,
        "tool": tool,
        "model": model,
        "provider": "meta",
        "prompt_tokens": prompt_tokens,
        "completion_tokens": completion_tokens,
        "cost_cents": cost_cents,
        "cached": cached,
        "duration_ms": duration_ms,
    })
    JobStateService.add_cost(job_id, 0.0 if cached else cost_cents)
