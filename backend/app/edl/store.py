"""EDL persistence.

Storage layout (Firestore or the local JSON fallback both work):

- The current EDL lives inside the job document: ``edl`` + ``edl_revision``.
- Revision history lives in a top-level ``edl_revisions`` collection with
  document ids ``{job_id}:{revision}``, which keeps the local JSON fallback
  working unchanged.
- The last ``MAX_REVISIONS`` revisions are kept; older entries are pruned on
  save (Firestore) and bounded by ``maintenance()`` locally.

Every revision records ``source`` (``pipeline`` | ``user`` | ``agent``), the
applied ``operations``, a human ``summary``, and ``created_at``.
"""
import json
import logging
from typing import Any, Dict, List, Optional, Tuple

from app.config import settings
from app.edl.schema import EDLValidationError, edl_summary, normalize_edl, validate_edl
from app.services.firestore_service import JobStateService, get_firestore_client

logger = logging.getLogger("chronocut.edl.store")

MAX_REVISIONS = 50
_REVISIONS_COLLECTION = "edl_revisions"
ALLOWED_SOURCES = {"pipeline", "user", "agent"}


def _revision_doc_id(job_id: str, revision: int) -> str:
    return f"{job_id}:{int(revision)}"


def _sanitize(value: Any) -> Any:
    """Reuse the Firestore sanitizer so mixed dicts/lists never 500."""
    try:
        from app.services.firestore_service import _sanitize_firestore_value
        return _sanitize_firestore_value(value)
    except Exception:
        return value


# --------------------------------------------------------------------------
# read
# --------------------------------------------------------------------------
def load_edl(job_id: Optional[str]) -> Tuple[Optional[Dict[str, Any]], int]:
    """Return (current_edl, revision). (None, 0) when the job has no EDL yet."""
    if not job_id:
        return None, 0
    job = JobStateService.get_job(str(job_id))
    if not job:
        return None, 0
    edl = job.get("edl")
    if not edl:
        return None, 0
    try:
        revision = int(job.get("edl_revision") or 0)
    except (TypeError, ValueError):
        revision = 0
    try:
        edl = normalize_edl(json.loads(json.dumps(edl)))
    except (EDLValidationError, ValueError, TypeError) as e:
        logger.error("Stored EDL for %s failed to normalize: %s", job_id, e)
        return edl, revision
    return edl, revision


def current_revision(job_id: Optional[str]) -> int:
    _, revision = load_edl(job_id)
    return revision


def get_revision(job_id: Optional[str], revision: int) -> Optional[Dict[str, Any]]:
    """Return the stored revision document (job_id, revision, edl, source, ...)."""
    if not job_id:
        return None
    doc_id = _revision_doc_id(str(job_id), int(revision))
    return JobStateService._get_doc(_REVISIONS_COLLECTION, doc_id)


def list_revisions(job_id: Optional[str], limit: int = MAX_REVISIONS) -> List[Dict[str, Any]]:
    """Revision summaries (newest first), without the heavy ``edl`` payload."""
    if not job_id:
        return []
    docs: List[Dict[str, Any]] = []
    client = get_firestore_client()
    if client is None:
        raw = JobStateService._list_collection(_REVISIONS_COLLECTION, limit=500) or []
        docs = [d for d in raw if d.get("job_id") == str(job_id)]
    else:  # pragma: no cover
        try:
            stream = (client.collection(_REVISIONS_COLLECTION)
                      .where("job_id", "==", str(job_id))
                      .order_by("revision")
                      .limit(200)
                      .stream())
            docs = [d.to_dict() for d in stream]
        except Exception as e:
            logger.error("list_revisions failed for %s: %s", job_id, e)
            return []

    def _revnum(d: Dict[str, Any]) -> int:
        try:
            return int(d.get("revision", 0))
        except (TypeError, ValueError):
            return 0

    docs = sorted(docs, key=lambda d: _revnum(d), reverse=True)
    out: List[Dict[str, Any]] = []
    for d in docs[:limit]:
        out.append({
            "job_id": d.get("job_id"),
            "revision": _revnum(d),
            "source": d.get("source") or "pipeline",
            "summary": d.get("summary") or {},
            "operations": d.get("operations") or [],
            "created_at": d.get("created_at"),
        })
    return out


# --------------------------------------------------------------------------
# write
# --------------------------------------------------------------------------
def save_edl(
    job_id: Optional[str],
    edl: Dict[str, Any],
    *,
    source: str = "pipeline",
    operations: Optional[List[Dict[str, Any]]] = None,
    summary: Optional[Dict[str, Any]] = None,
    base_revision: Optional[int] = None,
) -> Tuple[Dict[str, Any], int]:
    """Normalize, validate, and persist a new revision.

    Returns (stored_edl, new_revision). With ``base_revision`` set, a stale
    save raises :class:`RevisionConflict` (mapped to HTTP 409 by the route).
    """
    if not job_id:
        raise EDLValidationError(["save_edl: job_id is required"])
    if source not in ALLOWED_SOURCES:
        source = "pipeline"

    current, revision = load_edl(str(job_id))

    if base_revision is not None and base_revision != revision:
        raise RevisionConflict(revision)

    if current is None and base_revision is not None:
        revision = int(base_revision)  # first save after an explicit PUT

    stored = normalize_edl(json.loads(json.dumps(edl)))
    if not stored.get("revision"):
        stored["revision"] = revision
    stored = validate_edl(stored)

    new_revision = revision + 1
    stored["revision"] = new_revision
    if stored.get("project"):
        from app.edl.schema import EDL_VERSION  # noqa: F401

    _bump_timestamps(stored)

    doc = {
        "job_id": str(job_id),
        "revision": int(new_revision),
        "edl": stored,
        "source": source,
        "operations": operations or [],
        "summary": summary or edl_summary(stored),
        "created_at": _now_iso(),
    }

    JobStateService.update_job(str(job_id), {"edl": stored, "edl_revision": int(new_revision)})
    JobStateService._put_doc(_REVISIONS_COLLECTION, _revision_doc_id(str(job_id), int(new_revision)), _sanitize(doc))
    _prune_revisions(str(job_id), keep=MAX_REVISIONS)

    try:
        JobStateService.append_event(str(job_id), {
            "stage": "edl_updated",
            "progress_percent": _pipeline_progress_for(stage_of(job_id)),
            "message": f"EDL revision {new_revision} saved ({source}).",
            "edl_revision": int(new_revision),
            "source": source,
            "summary": doc["summary"],
        })
    except Exception as e:  # SSE is best-effort
        logger.warning("edl_updated event failed for %s: %s", job_id, e)

    return stored, int(new_revision)


def stage_of(job_id: str) -> str:
    try:
        job = JobStateService.get_job(job_id) or {}
        return str(job.get("stage") or "")
    except Exception:
        return ""


def _pipeline_progress_for(stage: str) -> int:
    """Keep the SSE progress graph moving when EDL revisions stream in."""
    defaults = {
        "ingest": 15, "archivist": 30, "screenwriter": 45, "director": 55,
        "editor": 65, "review": 80, "render": 90, "done": 100,
    }
    return defaults.get(stage, 10)


def _bump_timestamps(edl: Dict[str, Any]) -> None:
    project = edl.get("project") or {}
    project["updated_at"] = _now_iso()
    if not project.get("created_at"):
        project["created_at"] = project["updated_at"]


def _now_iso() -> str:
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).isoformat()


def _prune_revisions(job_id: str, keep: int = MAX_REVISIONS) -> None:
    """Delete the oldest revision docs past the cap (Firestore only; the local
    fallback store is regenerated by maintenance() and bounded by caps)."""
    client = get_firestore_client()
    if client is None:
        return
    docs: List[Tuple[int, str]] = []
    try:  # pragma: no cover
        stream = (client.collection(_REVISIONS_COLLECTION)
                  .where("job_id", "==", str(job_id))
                  .order_by("revision")
                  .limit(300)
                  .stream())
        for snap in stream:
            data = snap.to_dict() or {}
            try:
                docs.append((int(data.get("revision", 0)), snap.id))
            except (TypeError, ValueError):
                continue
    except Exception as e:
        logger.warning("revision prune query failed for %s: %s", job_id, e)
        return
    docs.sort()
    for _, doc_id in docs[: max(0, len(docs) - keep)]:
        try:
            client.collection(_REVISIONS_COLLECTION).document(doc_id).delete()
        except Exception as e:
            logger.warning("revision prune delete failed for %s: %s", doc_id, e)


class RevisionConflict(Exception):
    """Raised by save_edl when a stale base_revision is supplied."""

    def __init__(self, current_revision: int):
        self.current_revision = current_revision
        super().__init__(f"revision conflict: current revision is {current_revision}")
