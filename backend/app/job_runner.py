"""Process-isolated, Firestore-backed job execution.

Why this exists
---------------
The original API ran the entire production pipeline inside the web-server
process via ``BackgroundTasks``. A heavy job (large ZIP buffered in memory,
ffmpeg building many segments, a Chromium-based overlay renderer, Gemini
calls) could balloon the process's RAM and the whole uvicorn worker got OOM-
killed — which is exactly what was observed in the logs (the server "restarted"
mid-job). Because the pipeline also held the only copy of job state in that
process, an OOM lost the job entirely.

Fix
---
* The API only *enqueues* a job id to Firestore (status ``QUEUED``) and returns.
* A lightweight supervisor (in the API process) pulls ``QUEUED`` jobs and runs
  each one in a **separate child process** (spawn). Heavy memory lives in that
  short-lived child; when it exits, the OS reclaims everything.
* Concurrency is bounded by a semaphore (default 1) so N uploads can never pile
  up and multiply memory.
* The child sets a hard address-space cap (``RLIMIT_AS`` on Linux) so a single
  runaway job fails *inside its own process* (marked ``FAILED``) instead of
  consuming the shared container memory and killing the API.
* Firestore is the durable queue + state store. On startup the supervisor
  reclaims ``PROCESSING`` jobs that went stale (e.g. the container was OOM-
  killed) back to ``QUEUED`` and re-runs them. Nothing is lost across restarts.
"""

import os
import asyncio
import logging
import multiprocessing as mp
from datetime import datetime, timezone, timedelta
from typing import Optional

logger = logging.getLogger("chronocut.job_runner")

from app.config import settings
from app.services.firestore_service import JobStateService

MAX_CONCURRENT_JOBS = int(os.getenv("CHRONOCUT_MAX_CONCURRENT_JOBS", "1"))
STALE_AFTER_MIN = int(os.getenv("CHRONOCUT_STALE_MIN", "5"))
# Optional per-job address-space cap (MB). DISABLED by default (0): ffmpeg
# subprocesses inherit this rlimit and HD encoding routinely needs >1.5 GB of
# virtual address space, so capping it silently OOM-killed ffmpeg and produced
# 0-byte/empty renders. API safety comes from running each job in its own child
# process (an OOM there kills the child, not the API). Set this only if you know
# your encoder's working set and want a hard ceiling — keep it well above it.
CHILD_MEM_MB = int(os.getenv("CHRONOCUT_JOB_MEM_MB", "0"))
WORKER_ID = f"{os.getenv('HOSTNAME', 'worker')}-{os.getpid()}"


def _parse_dt(v):
    if isinstance(v, datetime):
        return v
    if isinstance(v, str):
        try:
            return datetime.fromisoformat(v.replace("Z", "+00:00"))
        except Exception:
            return None
    return None


def _child_main(job_id: str) -> None:
    """Entry point executed in the isolated child process."""
    os.environ["CHRONOCUT_WORKER_CHILD"] = "1"
    _set_mem_limit()
    _check_memory()
    try:
        from app.agents.orchestrator import LeadOrchestratorAgent

        input_files = (JobStateService.get_job(job_id) or {}).get("input_files") or {}
        asyncio.run(LeadOrchestratorAgent().run_job(job_id, input_files))
    except Exception as e:  # noqa: BLE001 - last-resort guard
        logger.error(f"job {job_id} child failed: {e}")
        try:
            JobStateService.update_job(job_id, {
                "status": "FAILED",
                "error_log": {"stage": "worker", "message": f"worker crash: {e}"},
            })
        except Exception:
            pass


def _check_memory() -> None:
    """Free-tier guard: log a warning if available memory is critically low."""
    try:
        import psutil  # type: ignore
        avail = psutil.virtual_memory().available
        avail_mb = avail / (1024 * 1024)
        if avail_mb < 200:
            logger.warning(f"Low memory available: {avail_mb:.1f} MB. Render free tier has 512 MB total. Consider disabling MoviePy or reducing resolution.")
    except Exception:
        pass


def _set_mem_limit() -> None:
    if CHILD_MEM_MB <= 0:
        return  # disabled — see note on CHILD_MEM_MB
    try:
        import resource  # type: ignore  (POSIX only)
    except Exception:
        return
    try:
        mb = CHILD_MEM_MB * 1024 * 1024
        soft, hard = resource.getrlimit(resource.RLIMIT_AS)
        cap = mb if hard <= 0 else min(mb, hard)
        resource.setrlimit(resource.RLIMIT_AS, (cap, hard))
    except Exception as e:  # pragma: no cover
        logger.warning(f"mem limit not applied: {e}")


class JobRunner:
    def __init__(self, max_jobs: int = MAX_CONCURRENT_JOBS):
        self.max_jobs = max(1, max_jobs)
        self._sem: Optional[asyncio.Semaphore] = None
        self._queue: Optional[asyncio.Queue] = None
        self._pump_task: Optional[asyncio.Task] = None
        self._started = False

    async def start(self) -> None:
        if self._started:
            return
        if os.environ.get("CHRONOCUT_WORKER_CHILD"):
            return  # never start a supervisor inside a worker child
        self._sem = asyncio.Semaphore(self.max_jobs)
        self._queue = asyncio.Queue()
        await self._recover()
        self._pump_task = asyncio.create_task(self._pump())
        self._started = True
        logger.info(f"JobRunner started (max_jobs={self.max_jobs}, worker={WORKER_ID})")

    async def stop(self) -> None:
        if self._pump_task:
            self._pump_task.cancel()
            self._pump_task = None
        self._started = False

    async def submit(self, job_id: str) -> None:
        if self._queue is None:
            # Supervisor not running (e.g. test mode) — rely on Firestore recovery.
            return
        await self._queue.put(job_id)

    async def _recover(self) -> None:
        try:
            jobs = JobStateService.list_jobs(limit=200)
            now = datetime.now(timezone.utc)
            for j in jobs or []:
                jid = j.get("job_id")
                if not jid:
                    continue
                st = j.get("status")
                if st == "QUEUED":
                    await self._queue.put(jid)
                elif st == "PROCESSING":
                    claimed = _parse_dt(j.get("claimed_at"))
                    if claimed and (now - claimed) > timedelta(minutes=STALE_AFTER_MIN):
                        JobStateService.update_job(jid, {
                            "status": "QUEUED", "claimed_at": None, "claimed_by": None,
                        })
                        await self._queue.put(jid)
                        logger.warning(f"reclaimed stale PROCESSING job {jid}")
                elif st == "FAILED":
                    # R1: re-queue FAILED jobs that died in the worker (OOM / crash)
                    # after a grace period so transient infra failures auto-recover.
                    err = (j.get("error_log") or {}).get("stage")
                    msg = (j.get("error_log") or {}).get("message", "")
                    failed_at = _parse_dt(j.get("updated_at"))
                    if err == "worker" and failed_at and (now - failed_at) > timedelta(minutes=10):
                        JobStateService.update_job(jid, {
                            "status": "QUEUED", "claimed_at": None, "claimed_by": None,
                            "error_log": {},
                        })
                        await self._queue.put(jid)
                        logger.warning(f"re-queued crashed FAILED job {jid}: {msg}")
        except Exception as e:  # pragma: no cover
            logger.warning(f"job recovery skipped: {e}")

    async def _pump(self) -> None:
        assert self._queue is not None and self._sem is not None
        while True:
            job_id = await self._queue.get()
            await self._sem.acquire()
            asyncio.create_task(self._dispatch(job_id))

    async def _dispatch(self, job_id: str) -> None:
        try:
            JobStateService.update_job(job_id, {
                "status": "PROCESSING", "claimed_at": datetime.now(timezone.utc).isoformat(),
                "claimed_by": WORKER_ID,
            })
            ctx = mp.get_context("spawn")
            proc = ctx.Process(target=_child_main, args=(job_id,), daemon=True)
            proc.start()
            await asyncio.to_thread(proc.join)
            if proc.exitcode not in (0, None):
                logger.error(f"job {job_id} child exited with code {proc.exitcode}")
                # Don't re-queue: a crash here means the job itself is too heavy /
                # errored, not a transient infra blip. Re-running would OOM-loop.
                try:
                    cur = JobStateService.get_job(job_id) or {}
                    if cur.get("status") not in ("COMPLETE", "NEEDS_REVIEW", "CANCELLED"):
                        JobStateService.update_job(job_id, {
                            "status": "FAILED",
                            "error_log": {"stage": "worker",
                                          "message": f"process exited {proc.exitcode}"},
                        })
                except Exception:
                    pass
            else:
                logger.info(f"job {job_id} child finished cleanly")
        except Exception as e:  # pragma: no cover
            logger.error(f"dispatch error for {job_id}: {e}")
            try:
                JobStateService.update_job(job_id, {
                    "status": "FAILED", "error_log": {"stage": "runner", "message": str(e)},
                })
            except Exception:
                pass
        finally:
            if self._sem is not None:
                self._sem.release()


# Module-level singleton used by the API.
runner = JobRunner()
