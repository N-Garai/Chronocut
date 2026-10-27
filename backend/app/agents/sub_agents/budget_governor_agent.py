"""BudgetGovernorAgent  — reports per-job spend against the free-tier cap.

Thin agent: reads the cost ledger written by the BudgetGovernor decorator and
reports whether the job is within its per-job cap. No model calls.
"""
from typing import Dict, Any


class BudgetGovernorAgent:
    async def run(self, job_id: str) -> Dict[str, Any]:
        from app.config import settings
        from app.services.firestore_service import JobStateService
        try:
            ledger = JobStateService.get_ledger(job_id) or []
        except Exception:
            ledger = []
        total_cents = sum(float(c.get("cost_cents", 0) or 0) for c in ledger)
        return {
            "calls": len(ledger),
            "total_cents": round(total_cents, 4),
            "cap_cents": settings.PER_JOB_COST_CAP_CENTS,
            "within_cap": total_cents <= settings.PER_JOB_COST_CAP_CENTS,
        }
