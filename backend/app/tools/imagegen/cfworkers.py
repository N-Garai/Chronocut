"""Generated B-roll stills via Workers AI ``flux-1-schnell`` (free-tier safe).

Cost model (verified free plan, Oct 2026): 10,000 free neurons/day; one
``flux-1-schnell`` image costs ``ceil((w/512)*(h/512))`` tiles at 4.80
neurons each plus 9.60 per step, so a default 1024x576 4-step still costs
~57.6 neurons — about 170 images/day inside the free daily allowance.

Failures are always graceful: provider ``off`` is a no-op, an exhausted
daily neuron budget refuses further calls, HTTP errors degrade that beat
back to an uploaded still/footage when possible, and generation never
blocks or fails a render. Generated stills are cached under the job's
media tree by prompt hash and reused across revisions.
"""
import base64
import hashlib
import logging
import os
import threading
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import requests

from app.config import settings

logger = logging.getLogger("chronocut.tools.imagegen.cfworkers")

_MODEL = "@cf/black-forest-labs/flux-1-schnell"
_COST_PER_TILE = 4.8   # 512x512 image tile
_COST_PER_STEP = 9.6

__all__ = [
    "cf_imagegen_available", "generate_still", "generate_broll_stills",
    "estimate_neurons", "neuron_budget_status", "ensure_generated_assets",
    "generated_source_id", "GEN_SOURCE_PREFIX",
]

GEN_SOURCE_PREFIX = "gen-"


def cf_imagegen_available() -> bool:
    """True only when the provider is enabled AND credentials exist."""
    return (settings.image_gen_provider == "cfworkers"
            and bool(settings.CF_ACCOUNT_ID and settings.CF_API_TOKEN))


def estimate_neurons(width: int = 1024, height: int = 576, steps: int = 4) -> float:
    """Fixed cost model — 4.8 neurons per 512^2 tile + 9.6 per step."""
    w = max(1, int(width)); h = max(1, int(height)); s = max(1, int(steps))
    tiles = ((w + 511) // 512) * ((h + 511) // 512)
    return round(tiles * _COST_PER_TILE + s * _COST_PER_STEP, 2)


class _NeuronBudget:
    """In-process daily neuron reserve/consume. Loses count across restarts
    (the provider 429s loudly when the free day is exhausted anyway) — the
    counter exists to *prevent* silent 429 storms, not to be an audit."""

    def __init__(self, daily_limit: int) -> None:
        self.daily_limit = max(0, int(daily_limit))
        self._lock = threading.Lock()
        self._day = ""
        self._used = 0.0
        self._reserved = 0.0

    def _roll(self) -> None:
        today = datetime.now(timezone.utc).strftime("%Y%m%d")
        if today != self._day:
            self._day = today
            self._used = 0.0
            self._reserved = 0.0

    def reserve(self, amount: float) -> bool:
        with self._lock:
            self._roll()
            if self._used + self._reserved + amount > self.daily_limit:
                return False
            self._reserved += amount
            return True

    def consume(self, amount: float, *, committed: bool) -> float:
        with self._lock:
            self._roll()
            self._reserved = max(0.0, self._reserved - amount)
            if committed:
                self._used = round(self._used + amount, 2)
            return self._used

    def status(self) -> Dict[str, Any]:
        with self._lock:
            self._roll()
            return {"day_utc": self._day, "used": self._used,
                    "reserved": self._reserved,
                    "daily_limit": self.daily_limit}


_budget = _NeuronBudget(getattr(settings, "IMAGE_GEN_DAILY_NEURONS", 9600))


def neuron_budget_status() -> Dict[str, Any]:
    out = dict(_budget.status())
    out["provider"] = settings.image_gen_provider
    return out


def _ledger_note(job_id: Optional[str], neurons: float, prompt: str) -> None:
    """Usage rows land in the cost ledger as $0 units (external free API)."""
    if not job_id or os.getenv("CHRONOCUT_TEST"):
        return
    try:
        from app.services.firestore_service import JobStateService
        JobStateService.ledger_write(job_id, {
            "tool": "imagegen_flux_schnell", "provider": "cfworkers",
            "calls": 1, "cost_cents": 0.0, "cached": False,
            "units": f"{neurons} neurons", "note": prompt[:80],
        })
    except Exception:  # ledger is best-effort
        pass


def generate_still(prompt: str, out_path: Optional[str] = None,
                   *, width: int = 1024, height: int = 576,
                   negative: str = "text, watermark, logo, blur, deformed",
                   job_id: Optional[str] = None) -> Dict[str, Any]:
    """Generate one still; returns a shot visual_source-compatible dict.

    Contract: provider off/missing creds -> no-op;
    exhausted daily budget -> refused attempt with the snapshot in the
    result; network/API failure -> ``ok: False`` with a short error. The
    cache is keyed by ``(prompt, width, height)`` so a retry or a later
    revision that requests the same prompt reuses the still for free.
    """
    if settings.image_gen_provider != "cfworkers":
        return {"ok": False, "noop": "provider_off",
                "error": "image generation disabled (IMAGE_GEN_PROVIDER=off)"}
    if not cf_imagegen_available():
        return {"ok": False, "noop": "not_configured",
                "error": "Cloudflare Workers AI not configured (CF_ACCOUNT_ID/CF_API_TOKEN)"}
    neurons = estimate_neurons(width, height, settings.IMAGE_GEN_STEPS)
    if not _budget.reserve(neurons):
        st = _budget.status()
        used = st["used"] + st["reserved"]
        return {"ok": False, "noop": "quota_exhausted",
                "error": (f"daily neuron budget exhausted ({used:.1f}/{st['daily_limit']}); "
                          f"another image would cost {neurons:.1f}")}

    cache_key = hashlib.sha1(
        f"{prompt}|{width}x{height}|{int(settings.IMAGE_GEN_STEPS)}".encode()).hexdigest()
    if out_path is None:
        out_dir = os.path.join(os.getcwd(), "tmp", "generated_stills")
        os.makedirs(out_dir, exist_ok=True)
        out_path = os.path.join(out_dir, f"{cache_key}.png")

    # Cache: a still for the same prompt at the same size already exists in
    # this job -> reuse it across revisions at zero neurons.
    if os.path.isfile(out_path) and os.path.getsize(out_path) > 0:
        _budget.consume(neurons, committed=False)   # cache hit: neurons untouched
        _ledger_note(job_id, 0.0, prompt)
        return {"ok": True, "file": out_path, "cached": True, "source": "cfworkers",
                "type": "ai_still", "effect": "ken_burns_slow_zoom", "prompt": prompt[:200]}

    committed = False
    try:
        url = (f"https://api.cloudflare.com/client/v4/accounts/"
               f"{settings.CF_ACCOUNT_ID}/ai/run/{_MODEL}")
        resp = requests.post(
            url,
            headers={"Authorization": f"Bearer {settings.CF_API_TOKEN}"},
            json={
                "prompt": prompt[:1200],
                "steps": max(1, min(int(settings.IMAGE_GEN_STEPS), 8)),
                "width": width,
                "height": height,
                "negative_prompt": negative,
            },
            timeout=120,
        )
        resp.raise_for_status()
        data = resp.json()
        if not data.get("success"):
            raise ValueError(str(data.get("errors") or data)[:200])
        b64 = (data.get("result") or {}).get("image")
        if not b64:
            raise ValueError("no image in response")
        tmp_path = out_path + ".part"
        os.makedirs(os.path.dirname(tmp_path) or ".", exist_ok=True)
        with open(tmp_path, "wb") as f:
            f.write(base64.b64decode(b64))
        _budget.consume(neurons, committed=True)
        committed = True
        os.replace(tmp_path, out_path)
        _ledger_note(job_id, neurons, prompt)
        return {"ok": True, "file": out_path, "cached": False, "source": "cfworkers",
                "type": "ai_still", "effect": "ken_burns_slow_zoom",
                "neurons": neurons, "prompt": prompt[:200]}
    except Exception as e:
        logger.warning("Workers AI imagegen failed: %s", e)
        return {"ok": False, "error": f"{type(e).__name__}: {str(e)[:200]}"}
    finally:
        if not committed:
            _budget.consume(neurons, committed=False)


def generate_broll_stills(prompts: List[str], out_dir: str,
                          *, limit: Optional[int] = None,
                          job_id: Optional[str] = None) -> List[Dict[str, Any]]:
    """Generate up to ``limit`` stills for a job; cheap, guarded, best-effort."""
    cap = int(limit or settings.IMAGE_GEN_MAX_PER_JOB)
    out: List[Dict[str, Any]] = []
    os.makedirs(out_dir, exist_ok=True)
    for i, prompt in enumerate((prompts or [])[:cap]):
        res = generate_still(prompt, os.path.join(out_dir, f"broll_{i:02d}.png"), job_id=job_id)
        if res.get("ok"):
            out.append(res)
    return out


# ---------------------------------------------------------------------------
# EDL wiring: materialize ``insert_broll`` generated sources and degrade
# ---------------------------------------------------------------------------
def generated_source_id(prompt: str) -> str:
    """Stable id for a generated source: same prompt -> same id, so replanning
    the same beat reuses the source without a duplicate (and the still cache)."""
    h = hashlib.sha1((prompt or "").strip().encode()).hexdigest()[:8]
    return f"{GEN_SOURCE_PREFIX}{h}"


def ensure_generated_assets(job_id: str, edl: Dict[str, Any],
                            asset_dir_path: Optional[str] = None) -> bool:
    """Materialize every pending generated still referenced by this EDL.

    Called after an apply/save: for each ``sources[*]`` with a ``generated``
    flag and an empty path, runs the provider (budget+cache); on success fills
    the path; on provider-off / quota / error degrades — the clips that
    reference the source fall back to an available uploaded image source, or
    keep the matte placeholder when none exists. Never raises; returns True
    when the EDL was changed (caller re-saves and bumps the revision).
    """
    changed = False
    sources = edl.get("sources") if isinstance(edl, dict) else None
    if not sources:
        return False
    if asset_dir_path is None:
        from app.services.storage import asset_dir
        asset_dir_path = asset_dir(str(job_id), "generated")

    fallback_image_id = next((str(s.get("id")) for s in sources
                              if str(s.get("type") or "") == "image"
                              and s.get("path")), None)

    for src in sources:
        if not isinstance(src, dict) or not src.get("generated") or src.get("path"):
            continue
        prompt = str(src.get("prompt") or "")
        if not prompt:
            continue
        res = generate_still(prompt, os.path.join(
            asset_dir_path, f"{str(src.get('id') or 'gen')}.png"), job_id=str(job_id))
        if res.get("ok"):
            src["path"] = res["file"]
            changed = True
            _activity(job_id, "broll_generated", "succeeded",
                      f"generated still for {src.get('id')} ({res.get('neurons', 0)} neurons, "
                      f"cached={bool(res.get('cached'))})")
            continue
        noop = res.get("noop") or "error"
        _activity(job_id, "broll_degraded", "failed",
                  f"generated still unavailable ({noop}); beat degrades to "
                  f"{'uploaded still' if fallback_image_id else 'matte'}: "
                  f"{res.get('error', '')[:120]}")
        src["degraded"] = noop
        for track in edl.get("tracks") or []:
            for clip in track.get("clips") or []:
                if str(clip.get("source_id")) == str(src.get("id")) and fallback_image_id:
                    clip["source_id"] = fallback_image_id
                    clip["name"] = "B-roll (still)"
        changed = True
    return changed


def _activity(job_id: str, action: str, status: str, detail: str) -> None:
    try:
        from app.agents import telemetry as _tel
        _tel.record_activity(job_id, agent="scene_caster", action=action,
                             status=status, parent_agent="editor", detail=detail)
    except Exception:
        pass
