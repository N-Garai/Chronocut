import logging

logger = logging.getLogger("chronocut.tools.frontend")


def sse_emit(job_id: str, event: dict) -> None:
    """Append an SSE event to the job's event stream."""
    if not job_id or not event:
        return
    try:
        from app.services.firestore_service import JobStateService

        JobStateService.append_event(job_id, event)
    except Exception as e:
        logger.warning(f"sse_emit failed for job {job_id}: {e}")
