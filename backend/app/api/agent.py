"""Agent command API.

POST /jobs/{id}/agent          — natural-language edit request → operation plan (plan-only)
GET  /jobs/{id}/agent/activity — telemetry ring-buffer replay for cold-load; SSE appends live
"""
import logging
import time
from typing import Any, Dict, Optional

from fastapi import APIRouter, HTTPException

from app.agents.telemetry import activity_of, new_action_id, record_activity
from app.edl.schema import EDLValidationError, edl_summary
from app.edl.store import RevisionConflict, load_edl
from app.services.firestore_service import JobStateService

logger = logging.getLogger("chronocut.api.agent")
router = APIRouter(prefix="/api/v1/jobs/{job_id}")


@router.post("/agent")
async def plan_agent_command(job_id: str, body: Dict[str, Any]):
    """Natural-language edit request → validated operation plan (plan-only)."""
    job = JobStateService.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    message = str(body.get("message") or "").strip()
    if not message:
        raise HTTPException(status_code=400, detail="message is required")

    edl, revision = load_edl(job_id)
    if not edl:
        raise HTTPException(status_code=404, detail="EDL not ready for this job yet")

    base = body.get("base_revision")
    if base is not None and int(base) != int(revision):
        raise HTTPException(status_code=409, detail={"stale_revision": revision})

    action_id = new_action_id()
    started = time.time()
    try:
        from app.agents.planner import plan_from_message
        ctx = body.get("context") or {}
        plan = await plan_from_message(
            job_id=job_id, message=message, edl=edl,
            base_revision=revision,
            playhead_ms=int(ctx.get("playhead_ms") or 0),
            selection=[str(s) for s in (ctx.get("selection") or [])][:20],
        )
    except EDLValidationError as e:
        record_activity(job_id, "timeline_agent", "plan", status="failed",
                        detail=str(e)[:240], duration_ms=int((time.time() - started) * 1000))
        raise HTTPException(status_code=422, detail=str(e))
    except Exception as e:
        logger.exception("agent plan failed for %s", job_id)
        record_activity(job_id, "timeline_agent", "plan", status="failed",
                        detail=str(e)[:240], duration_ms=int((time.time() - started) * 1000))
        raise HTTPException(status_code=503, detail=f"planner unavailable: {e}")

    duration_ms = int((time.time() - started) * 1000)
    record_activity(job_id, "timeline_agent", "plan", status="succeeded",
                    detail=f"plan: {len(plan.get('operations') or [])} op(s) ({plan.get('plan_kind', 'llm')})",
                    duration_ms=duration_ms,
                    operations=plan.get("operations"),
                    revision_before=revision, revision_after=revision)
    return {
        "action_id": action_id,
        "message": plan.get("message"),
        "operations": plan.get("operations") or [],
        "requires_confirmation": plan.get("requires_confirmation", False),
        "warnings": plan.get("warnings") or [],
        "base_revision": plan.get("base_revision", revision),
        "plan_kind": plan.get("plan_kind"),
        "subagents": plan.get("subagents") or {"engaged": [], "degraded": []},
        "duration_ms": duration_ms,
        "summary": edl_summary(edl),
    }


@router.get("/agent/activity")
async def agent_activity(job_id: str, agent: Optional[str] = None,
                         action: Optional[str] = None, limit: int = 50):
    job = JobStateService.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    rows = activity_of(job_id, agent=agent, action=action, limit=min(int(limit), 50))
    return {"job_id": job_id, "activity": rows}
