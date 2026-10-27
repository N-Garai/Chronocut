import logging
from typing import Dict, Any

logger = logging.getLogger("chronocut.tools.review")

__all__ = ["delivery_promise"]


def delivery_promise(actual_duration: float, declared_duration: float, tolerance: float = 0.10) -> Dict[str, Any]:
    if not declared_duration or declared_duration <= 0:
        return {"delta_pct": 0.0, "ok": True}
    delta = abs(actual_duration - declared_duration) / declared_duration
    return {"delta_pct": round(delta * 100, 1), "ok": delta <= tolerance}
