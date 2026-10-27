import logging
from typing import Optional

from app.services.firestore_service import JobStateService
from app.config import settings

logger = logging.getLogger("chronocut.tools.llm.governor")


class BudgetExceededError(RuntimeError):
    pass


def estimate_cost_cents(prompt_tokens: int, completion_tokens: int) -> float:
    """Rough free-tier cost estimate for Gemini Flash.

    Flash pricing is approximated at $0.10 / 1M input tokens and
    $0.40 / 1M output tokens. Converted to cents.
    """
    in_cents = (prompt_tokens / 1_000_000.0) * 0.10 * 100.0
    out_cents = (completion_tokens / 1_000_000.0) * 0.40 * 100.0
    return round(in_cents + out_cents, 4)


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
        "prompt_tokens": prompt_tokens,
        "completion_tokens": completion_tokens,
        "cost_cents": cost_cents,
        "cached": cached,
        "duration_ms": duration_ms,
    })
    JobStateService.add_cost(job_id, 0.0 if cached else cost_cents)
