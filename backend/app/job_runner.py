"""Process-isolated, Firestore-backed job execution.

Why this exists
---------------
The original API ran the entire production pipeline inside the web-server
process via ``BackgroundTasks``. A heavy job (large ZIP buffered in memory,
ffmpeg building many segments, a Chromium-based overlay renderer
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
* Firestore is the durable queue + state store. On startup — and every minute
  thereafter — the supervisor reclaims ``PROCESSING`` jobs whose worker stopped
  heartbeating (e.g. the container was OOM-killed) back to ``QUEUED`` and
  re-runs them, resuming from the last completed stage. Nothing is lost across
  restarts.
"""

import os
import asyncio
import logging
import multiprocessing as mp
import threading
import time
from datetime import datetime, timezone, timedelta
from typing import Optional

logger = logging.getLogger("chronocut.job_runner")

from app.config import settings
from app.services.firestore_service import JobStateService

MAX_CONCURRENT_JOBS = int(os.getenv("CHRONOCUT_MAX_CONCURRENT_JOBS", "1"))
STALE_AFTER_MIN = int(os.getenv("CHRONOCUT_STALE_MIN", "5"))
# Recovery requeues per job (stale PROCESSING sweep + crashed-FAILED recovery).
# Unbounded requeueing turns a deterministically crashing job into a zombie that
# occupies the only job slot forever (max concurrent jobs is 1); after this many
# recovery attempts the job stays FAILED with the last error.
MAX_JOB_REQUEUES = int(os.getenv("CHRONOCUT_MAX_JOB_REQUEUES", "3"))
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

    # Liveness heartbeat: a daemon thread refreshes heartbeat_at while the
    # child is alive, so a container OOM-kill (thread dies with the process)
    # is distinguishable from a long, healthy ffmpeg stage. Without this a
    # dead job can only be detected by the once-at-startup sweep — and a job
    # claimed <STALE_AFTER_MIN before a crash then stays PROCESSING forever.
    def _beat() -> None:
        while True:
            try:
                JobStateService.update_job(job_id, {
                    "heartbeat_at": datetime.now(timezone.utc).isoformat(),
                })
            except Exception:
                pass
            threading.Event().wait(60)

    threading.Thread(target=_beat, daemon=True).start()

    try:
        from app.agents.orchestrator import LeadOrchestratorAgent

        from app.services.firestore_service import get_firestore_client
        print(f"[child] {job_id} client=None? {get_firestore_client() is None} "
              f"t={datetime.now(timezone.utc).isoformat()}", flush=True)
        _doc: dict = {}
        # The child must see the job doc the API just wrote; retry briefly so a
        # slow first read can never silently strip the job's input_files (the
        # observed "Untitled story"/60s fallback regression).
        for _attempt in range(6):
            _doc = JobStateService.get_job(job_id) or {}
            if _doc.get("input_files"):
                break
            print(f"[child] {job_id} attempt {_attempt}: doc_keys={sorted(_doc.keys())[:12]} "
                  f"t={datetime.now(timezone.utc).isoformat()}", flush=True)
            time.sleep(2)
        input_files = _doc.get("input_files") or {}
        print(f"[child] {job_id} final input_keys={sorted(input_files.keys())[:10]} "
              f"mode={input_files.get('mode')!r}", flush=True)
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
        from app.services.memory import available_mb
        avail_mb = available_mb()
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
        self._sweep_task: Optional[asyncio.Task] = None
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
        self._sweep_task = asyncio.create_task(self._sweep_loop())
        self._started = True
        logger.info(f"JobRunner started (max_jobs={self.max_jobs}, worker={WORKER_ID})")

    async def stop(self) -> None:
        for t in (self._pump_task, getattr(self, "_sweep_task", None)):
            if t:
                t.cancel()
        self._pump_task = None
        self._sweep_task = None
        self._started = False

    async def submit(self, job_id: str) -> None:
        if self._queue is None:
            # Supervisor not running (e.g. test mode) — rely on Firestore recovery.
            return
        await self._queue.put(job_id)

    async def _recover(self) -> None:
        # Startup recovery re-queues everything left QUEUED/PROCESSING/FAILED
        # by a dead worker. Right for the always-on Render instance (OOM crash
        # recovery), but wrong for local demo runs: any stale job in the shared
        # local store gets claimed and re-run before the user's new job.
        # CHRONOCUT_RESUME_STALE_JOBS=0 skips the whole startup sweep.
        if os.getenv("CHRONOCUT_RESUME_STALE_JOBS", "1").strip().lower() in ("0", "false", "no"):
            logger.info("startup job recovery disabled (CHRONOCUT_RESUME_STALE_JOBS=0)")
            return
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
                    await self._requeue_if_stale(j, now)
                elif st == "FAILED":
                    # Re-queue FAILED jobs that died in the worker (OOM / crash)
                    # after a grace period so transient infra failures auto-recover.
                    err = (j.get("error_log") or {}).get("stage")
                    msg = (j.get("error_log") or {}).get("message", "")
                    failed_at = _parse_dt(j.get("updated_at"))
                    if err == "worker" and failed_at and (now - failed_at) > timedelta(minutes=10):
                        await self._requeue_with_limit(j, jid, f"crashed: {msg}")
        except Exception as e:  # pragma: no cover
            logger.warning(f"job recovery skipped: {e}")

    async def _requeue_with_limit(self, j: dict, jid: str, reason: str) -> bool:
        """Requeue a dead job unless it has already burned its recovery budget.

        Returns True when the job was requeued. Past MAX_JOB_REQUEUES the job
        stays FAILED with the last error instead of looping forever and
        blocking the single job slot.
        """
        count = int(j.get("requeue_count") or 0)
        if count >= MAX_JOB_REQUEUES:
            logger.error(
                f"job {jid} not requeued again ({count}/{MAX_JOB_REQUEUES} recovery "
                f"requeues used): {reason}"
            )
            return False
        JobStateService.update_job(jid, {
            "status": "QUEUED", "claimed_at": None, "claimed_by": None,
            # Clear the dead run's heartbeat too: a stale heartbeat_at takes
            # precedence over claimed_at in the staleness check, and leaving it
            # behind makes every 60s sweep instantly re-dispatch the job again
            # (the observed 1-2 minute OOM crash loop on the 512MB instance).
            "heartbeat_at": None,
            "error_log": {}, "requeue_count": count + 1,
        })
        await self._queue.put(jid)
        logger.warning(f"re-queued job {jid} (requeue {count + 1}/{MAX_JOB_REQUEUES}): {reason}")
        return True

    async def _requeue_if_stale(self, j: dict, now: datetime) -> bool:
        """Requeue a PROCESSING job whose worker stopped heartbeating.

        Liveness is ``heartbeat_at`` (refreshed by the child every 60s), falling
        back to ``claimed_at`` for jobs created before the heartbeat existed.
        """
        jid = j.get("job_id")
        if not jid:
            return False
        last = _parse_dt(j.get("heartbeat_at")) or _parse_dt(j.get("claimed_at"))
        if last and (now - last) <= timedelta(minutes=STALE_AFTER_MIN):
            return False
        await self._requeue_with_limit(j, jid, "stale PROCESSING (no heartbeat)")
        return True

    async def _sweep_loop(self) -> None:
        """Periodic stale-job sweep.

        Startup recovery alone misses any job claimed less than STALE_AFTER_MIN
        before a container death — exactly the case in the observed 88% stall
        (instance OOM-killed ~3 min into the job). The sweep re-checks every
        minute for the life of the process.
        """
        while True:
            await asyncio.sleep(60)
            if os.getenv("CHRONOCUT_RESUME_STALE_JOBS", "1").strip().lower() in ("0", "false", "no"):
                continue
            try:
                jobs = JobStateService.list_jobs(limit=200)
                now = datetime.now(timezone.utc)
                for j in jobs or []:
                    if j.get("status") == "PROCESSING":
                        await self._requeue_if_stale(j, now)
            except asyncio.CancelledError:
                raise
            except Exception as e:
                logger.warning(f"stale-job sweep skipped: {e}")

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
