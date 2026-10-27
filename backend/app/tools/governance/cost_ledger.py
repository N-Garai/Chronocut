import logging

logger = logging.getLogger("chronocut.tools.governance.cost_ledger")


def cost_ledger(job_id: str) -> list:
    from app.services.firestore_service import JobStateService

    try:
        return JobStateService.get_ledger(job_id)
    except Exception as e:
        logger.error(f"cost_ledger failed for job {job_id}: {e}")
        return []


def budget_guard(job_id: str, estimated_cents: float) -> None:
    from app.tools.llm.governor import check_budget

    try:
        check_budget(job_id, estimated_cents)
    except Exception as e:
        logger.error(f"budget_guard failed for job {job_id}: {e}")
        raise
