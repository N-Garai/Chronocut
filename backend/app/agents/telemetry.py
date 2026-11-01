"""Agent telemetry: agent_activity emitter + per-job ring buffer.

Three producers share one event bus:
1. Pipeline agents — orchestrator stage start/finish rows.
2. Timeline agent — every command parse/plan/apply/reject/conflict row.
3. Render — preview/final render start/finish/error rows.

Rows are capped at 50 per job (ring buffer) and replay on cold load through
``GET /jobs/{id}/agent/activity``; SSE then appends live rows. The feed is
redacted: no prompts, no transcript text, no raw model output.
"""
import logging
import threading
import time
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from app.services.firestore_service import JobStateService

logger = logging.getLogger("chronocut.agents.telemetry")

RING_LEN = 50

_memory_lock = threading.Lock()
_memory_ring: Dict[str, List[Dict[str, Any]]] = {}

STATUS_QUEUED = "queued"
STATUS_RUNNING = "running"
STATUS_SUCCEEDED = "succeeded"
STATUS_FAILED = "failed"
STATUS_REJECTED = "rejected"
STATUS_STALE = "stale"


def new_action_id() -> str:
    return f"act_{uuid.uuid4().hex[:8]}"


def _configured_badge() -> Tuple[Optional[str], Optional[str]]:
    """The provider/model actually in use, read lazily so test overrides apply."""
    try:
        from app.config import settings
        provider, model = settings.model_badge
        return str(provider), str(model)
    except Exception:  # telemetry must never depend on config booting
        return None, None


def record_activity(job_id: Optional[str], agent: str, action: str, status: str = STATUS_SUCCEEDED,
                    *, detail: str = "", clip_ids: Optional[List[str]] = None,
                    time_range: Optional[List[float]] = None,
                    revision_before: Optional[int] = None,
                    revision_after: Optional[int] = None,
                    duration_ms: Optional[int] = None,
                    parent_agent: Optional[str] = None,
                    operations: Optional[List[Dict[str, Any]]] = None,
                    provider: Optional[str] = None,
                    model: Optional[str] = None,
                    emit_sse: bool = True) -> Optional[Dict[str, Any]]:
    """Record one agent_activity row for a job (bounded ring buffer).

    ``provider``/``model`` default to the configured model badge so every row
    can show which model produced the work; a caller that used a specific
    modality (ASR, vision, image generation) passes its own values.
    """
    if not job_id:
        return None
    conf_provider, conf_model = _configured_badge()
    row: Dict[str, Any] = {
        "action_id": new_action_id(),
        "agent": str(agent or "timeline_agent"),
        "action": str(action or "unknown"),
        "status": status,
        "detail": _redact(str(detail or ""))[:240],
        "clip_ids": [str(c) for c in (clip_ids or [])][:20],
        "time_range": [round(float(time_range[0]), 3), round(float(time_range[1]), 3)]
        if time_range and len(time_range) >= 2 else None,
        "revision_before": int(revision_before) if revision_before is not None else None,
        "revision_after": int(revision_after) if revision_after is not None else None,
        "duration_ms": int(duration_ms) if duration_ms is not None else None,
        "provider": str(provider or conf_provider or ""),
        "model": str(model or conf_model or ""),
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    if parent_agent:
        row["parent_agent"] = str(parent_agent)
    ops = _op_entries(operations)
    if ops:
        # Operation names + clip/profile targets only: never caption or prompt
        # text, so the expanded feed row cannot leak content.
        row["operations"] = ops

    with _memory_lock:
        ring = _memory_ring.setdefault(job_id, [])
        row["seq"] = (ring[-1]["seq"] + 1) if ring else 0
        ring.append(row)
        if len(ring) > RING_LEN:
            del ring[: len(ring) - RING_LEN]

    try:
        JobStateService.append_event(job_id, {**row, "stage": "agent_activity",
                                              "progress_percent": None,
                                              "message": row["detail"] or f"{row['agent']}: {row['action']}"})
    except Exception as e:  # the feed must never break the pipeline
        logger.warning(f"agent_activity append failed: {e}")
    return row


class ActivityContext:
    """Timing helper for a stage: emits running then terminal rows."""

    def __init__(self, job_id: Optional[str], agent: str, action: str, **kwargs):
        self.job_id = job_id
        self.agent = agent
        self.action = action
        self.kwargs = kwargs
        self.row: Optional[Dict[str, Any]] = None
        self.t0 = time.time()

    def __enter__(self):
        self.row = record_activity(self.job_id, self.agent, self.action,
                                   STATUS_RUNNING, **self.kwargs)
        return self

    def __exit__(self, exc_type, exc, tb):
        status = STATUS_FAILED if exc_type else STATUS_SUCCEEDED
        detail = str(exc)[:200] if exc else ""
        record_activity(self.job_id, self.agent, self.action, status,
                        detail=detail,
                        duration_ms=int((time.time() - self.t0) * 1000),
                        **{k: v for k, v in self.kwargs.items() if k not in ("detail",)})
        return False


def activity_of(job_id: str, agent: Optional[str] = None, action: Optional[str] = None,
                status: Optional[str] = None, limit: int = 50) -> List[Dict[str, Any]]:
    """Return rows from the retention ring buffer (most recent last)."""
    with _memory_lock:
        ring = list(_memory_ring.get(job_id, []))
    def _match(r: Dict[str, Any]) -> bool:
        return ((agent is None or r.get("agent") == agent)
                and (action is None or r.get("action") == action)
                and (status is None or r.get("status") == status))
    rows = [r for r in ring if _match(r)]
    return rows[-limit:] if limit else rows


def _redact(text: str) -> str:
    """Drop prompt bodies and transcript text from feed detail strings."""
    if not text:
        return ""
    for marker in ("prompt=", "transcript", "```"):
        if marker in text:
            text = text.split(marker)[0].strip()
    return text


def _op_entries(operations: Optional[List[Dict[str, Any]]]) -> List[Dict[str, str]]:
    """Allow-listed operation summary for the expandable feed row."""
    out: List[Dict[str, str]] = []
    for raw in (operations or [])[:20]:
        if not isinstance(raw, dict):
            continue
        name = str(raw.get("op") or "").strip()[:32]
        if not name:
            continue
        entry: Dict[str, str] = {"op": name}
        args = raw.get("args") if isinstance(raw.get("args"), dict) else {}
        target = args.get("clip_id") or args.get("source_id") or args.get("profile")
        if target:
            entry["target"] = str(target)[:48]
        out.append(entry)
    return out
