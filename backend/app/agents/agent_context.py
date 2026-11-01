"""Per-job agent context: what each parent stage decided, for later stages.

The five parent stages (archivist, screenwriter, director, editor, render) each
own specialist sub-agents. A stage writes a compact entry when it finishes, and
later stages (plus the timeline planner) read what came before them **under the
same parent**. Entries are small by design: counts, ids, keywords and short
notes — never transcripts, prompts or media bytes.

Storage is one field on the job document (``agent_context``), so a cold load,
a restarted container, or a failed apply can recover the stage memory.
"""
import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

logger = logging.getLogger("chronocut.agents.agent_context")

FIELD = "agent_context"
STAGE_ORDER = ["archivist", "screenwriter", "director", "editor", "render"]
MAX_ENTRIES = 40
MAX_DATA_CHARS = 700
MAX_NOTE = 200


def empty() -> Dict[str, Any]:
    return {"version": 1, "entries": []}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _compact(data: Any) -> Any:
    """Keep only small scalar/list/short-dict payloads for the context document."""
    if data is None:
        return None
    if isinstance(data, (int, float, bool)):
        return data
    if isinstance(data, str):
        return data[:240]
    if isinstance(data, dict):
        out = {}
        for k, v in list(data.items())[:12]:
            out[str(k)[:40]] = _compact(v)
        return out
    if isinstance(data, (list, tuple)):
        return [_compact(v) for v in list(data)[:20]]
    return str(data)[:120]


def _truncate_payload(entry: Dict[str, Any]) -> Dict[str, Any]:
    import json
    blob = json.dumps(entry.get("data") or {}, default=str)
    if len(blob) > MAX_DATA_CHARS:
        entry["data"] = {"truncated": True, "chars": len(blob)}
    return entry


def load(job_id: Optional[str]) -> Dict[str, Any]:
    """Read the stored context; always returns a usable document."""
    if not job_id:
        return empty()
    try:
        from app.services.firestore_service import JobStateService
        doc = JobStateService.get_job(str(job_id), field=FIELD)
    except Exception as e:  # context is best-effort, never fatal
        logger.warning("agent_context load failed for %s: %s", job_id, e)
        return empty()
    if not isinstance(doc, dict):
        return empty()
    doc.setdefault("version", 1)
    doc.setdefault("entries", [])
    if not isinstance(doc["entries"], list):
        doc["entries"] = []
    return doc


def save(job_id: Optional[str], context: Dict[str, Any]) -> None:
    if not job_id:
        return
    try:
        from app.services.firestore_service import JobStateService
        entries = list(context.get("entries") or [])[-MAX_ENTRIES:]
        JobStateService.update_job(str(job_id), {FIELD: {"version": 1, "entries": entries}})
    except Exception as e:
        logger.warning("agent_context save failed for %s: %s", job_id, e)


def record(job_id: Optional[str], parent: str, subagent: str, *,
           keyword: Optional[str] = None, status: str = "succeeded",
           data: Optional[Dict[str, Any]] = None, note: str = "",
           call: bool = False) -> Dict[str, Any]:
    """Append one stage entry and return the entry (also persisted)."""
    entry = _truncate_payload({
        "parent": str(parent or "").lower(),
        "subagent": str(subagent or ""),
        "keyword": str(keyword or "") or None,
        "status": str(status or "succeeded"),
        "call": bool(call),
        "note": str(note or "")[:MAX_NOTE],
        "data": _compact(data) or {},
        "at": _now(),
    })
    ctx = load(job_id)
    ctx["entries"].append(entry)
    ctx["entries"] = ctx["entries"][-MAX_ENTRIES:]
    save(job_id, ctx)
    return entry


def entries_for(job_id: Optional[str], parent: Optional[str] = None) -> List[Dict[str, Any]]:
    entries = load(job_id).get("entries") or []
    if parent is None:
        return list(entries)
    p = str(parent).lower()
    return [e for e in entries if str(e.get("parent")) == p]


def latest(job_id: Optional[str], subagent: str) -> Optional[Dict[str, Any]]:
    for e in reversed(load(job_id).get("entries") or []):
        if str(e.get("subagent")) == str(subagent):
            return e
    return None


def summary(job_id: Optional[str], limit_chars: int = 1200) -> Dict[str, Any]:
    """Compact per-parent view handed to the planner snapshot."""
    out: Dict[str, Any] = {}
    for parent in STAGE_ORDER:
        rows = entries_for(job_id, parent)
        if not rows:
            continue
        out[parent] = [
            {"subagent": e.get("subagent"), "keyword": e.get("keyword"),
             "status": e.get("status"), "data": e.get("data")}
            for e in rows[-4:]
        ]
    import json
    while len(json.dumps(out, default=str)) > limit_chars and out:
        # drop the oldest parent block first
        out.pop(list(out.keys())[0], None)
    return out
