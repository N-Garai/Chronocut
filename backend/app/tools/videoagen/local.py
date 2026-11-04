"""Local text-to-video generation (opt-in; see package docstring).

The heavy lifting (model download + inference) runs in a child interpreter
(``_worker.py``) so the multi-gigabyte model never lives in the API process
and a hung generation is killed by wall-clock timeout instead of blocking
the event loop. Output is a silent mp4 the EDL compiler treats like any
other downloaded clip (``effect: none``).
"""
import logging
import os
import subprocess
import sys
import threading
from typing import Dict, Optional

from app.config import settings

logger = logging.getLogger("chronocut.tools.videoagen.local")

__all__ = ["video_gen_available", "generate_clip", "try_generate_shot_video"]


def video_gen_available() -> bool:
    """Cheap precheck — provider enabled AND the heavy libs importable.

    Deliberately does NOT import torch/diffusers here (that takes seconds
    and hundreds of MB); the child process reports the real failure if the
    precheck passes but inference dies.
    """
    if settings.video_gen_provider != "local":
        return False
    try:
        import importlib.util
        return all(
            importlib.util.find_spec(m) is not None
            for m in ("torch", "diffusers")
        )
    except Exception:
        return False


class _JobBudget:
    """Per-process per-job generation cap (best effort; resets on restart)."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._counts: Dict[str, int] = {}

    def reserve(self, job_id: Optional[str]) -> bool:
        cap = max(0, int(settings.VIDEO_GEN_MAX_PER_JOB))
        if cap <= 0:
            return False
        key = str(job_id or "anon")
        with self._lock:
            if self._counts.get(key, 0) >= cap:
                return False
            self._counts[key] = self._counts.get(key, 0) + 1
            return True

    def release(self, job_id: Optional[str]) -> None:
        key = str(job_id or "anon")
        with self._lock:
            self._counts[key] = max(0, self._counts.get(key, 0) - 1)


_budget = _JobBudget()


def generate_clip(prompt: str, out_path: str, *, duration_s: float = 4.0,
                  width: int = 480, height: int = 320,
                  job_id: Optional[str] = None) -> Dict[str, object]:
    """Generate one short silent clip; never raises.

    Returns ``{"ok": True, "file": ..., "cached": ...}`` on success or
    ``{"ok": False, "error"|"noop": ...}`` on any failure — the caller
    degrades to the next fallback tier.
    """
    prompt = (prompt or "").strip()
    if not prompt:
        return {"ok": False, "noop": "empty_prompt", "error": "no prompt"}
    if settings.video_gen_provider != "local":
        return {"ok": False, "noop": "provider_off",
                "error": "video generation disabled (VIDEO_GEN_PROVIDER=off)"}
    if os.path.isfile(out_path) and os.path.getsize(out_path) > 0:
        return {"ok": True, "file": out_path, "cached": True}

    if not _budget.reserve(job_id):
        return {"ok": False, "noop": "quota_exhausted",
                "error": f"per-job video budget exhausted ({settings.VIDEO_GEN_MAX_PER_JOB})"}
    try:
        seconds = max(1.0, min(float(duration_s or 4.0), float(settings.VIDEO_GEN_MAX_SECONDS)))
        backend_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
        cmd = [
            sys.executable, "-m", "app.tools.videoagen._worker",
            "--prompt", prompt[:800],
            "--out", out_path,
            "--seconds", f"{seconds:.2f}",
            "--width", str(int(width)),
            "--height", str(int(height)),
            "--model", settings.VIDEO_GEN_MODEL,
        ]
        env = dict(os.environ)
        env.setdefault("HF_HUB_DISABLE_TELEMETRY", "1")
        proc = subprocess.Popen(
            cmd, cwd=backend_root, env=env,
            stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
        )
        try:
            _, stderr = proc.communicate(timeout=int(settings.VIDEO_GEN_TIMEOUT_SECONDS))
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.communicate()
            logger.warning("video generation timed out for job %s", job_id)
            return {"ok": False, "noop": "timeout", "error": "generation timed out"}
        if proc.returncode != 0 or not (os.path.isfile(out_path) and os.path.getsize(out_path) > 0):
            tail = (stderr or b"")[-400:].decode("utf-8", "replace")
            logger.warning("video generation failed (rc=%s): %s", proc.returncode, tail)
            return {"ok": False, "error": tail or f"exit {proc.returncode}"}
        return {"ok": True, "file": out_path, "cached": False, "seconds": seconds}
    except Exception as e:  # noqa: BLE001 — generation must never break a job
        logger.warning("video generation error: %s", e)
        return {"ok": False, "error": f"{type(e).__name__}: {str(e)[:200]}"}
    finally:
        _budget.release(job_id)


def try_generate_shot_video(query: str, duration: float, asset_dir: str,
                            job_id: Optional[str] = None) -> Optional[Dict[str, object]]:
    """Resolver-tier wrapper: None unless a clip was actually produced."""
    if not video_gen_available():
        return None
    import hashlib
    key = hashlib.sha1(f"{query}|{int(duration)}".encode()).hexdigest()[:16]
    out_path = os.path.join(asset_dir, f"aivideo_{key}.mp4")
    res = generate_clip(query, out_path, duration_s=duration, job_id=job_id)
    if not res.get("ok"):
        _activity(job_id, "broll_video_gen_skipped", "failed",
                  f"local video model unavailable for '{query}': {res.get('noop') or res.get('error', '')[:120]}")
        return None
    _activity(job_id, "broll_video_generated", "succeeded",
              f"generated {res.get('seconds', duration):.0f}s clip for '{query}' "
              f"({settings.VIDEO_GEN_MODEL}, cached={bool(res.get('cached'))})")
    return {
        "type": "ai_video",
        "url": None,
        "file": res["file"],
        "source": "local_video_model",
        "effect": "none",
    }


def _activity(job_id: Optional[str], action: str, status: str, detail: str) -> None:
    if not job_id:
        return
    try:
        from app.agents import telemetry as _tel
        _tel.record_activity(job_id, agent="scene_caster", action=action,
                             status=status, parent_agent="editor", detail=detail)
    except Exception:
        pass
