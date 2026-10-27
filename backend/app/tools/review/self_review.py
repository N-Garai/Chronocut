import logging
from typing import Optional, Dict, Any

logger = logging.getLogger("chronocut.tools.review")

__all__ = ["run_self_review"]


async def run_self_review(video_path: str, declared_duration: float, job_id: Optional[str] = None) -> Dict[str, Any]:
    """Mandatory quality gate (M4). Returns PASS | NEEDS_REVIEW | FAIL."""
    from app.tools.review.ffprobe import ffprobe_check
    from app.tools.review.frame_sampler import frame_sampler
    from app.tools.review.audio_levels import audio_levels
    from app.tools.review.delivery_promise import delivery_promise
    from app.tools.review.slideshow_detector import slideshow_detector

    checks = []

    probe = ffprobe_check(video_path)
    checks.append({"check": "ffprobe", "ok": probe.get("ok", False),
                   "detail": f"duration={probe.get('duration')}s codec={probe.get('codec')}"})

    frames = frame_sampler(video_path, n=8)
    checks.append({"check": "frame_variance", "ok": frames.get("ok", False),
                   "detail": f"avg_variance={frames.get('avg_variance')}"})

    levels = audio_levels(video_path)
    if levels.get("has_audio"):
        checks.append({"check": "audio_levels", "ok": levels.get("ok", True),
                       "detail": f"peak={levels.get('peak_db')}dB"})
    else:
        checks.append({"check": "audio_levels", "ok": True, "detail": "no audio track (silent allowed)"})

    dp = delivery_promise(probe.get("duration", 0), declared_duration)
    checks.append({"check": "delivery_promise", "ok": dp.get("ok", True),
                   "detail": f"delta={dp.get('delta_pct')}%"})

    slide = slideshow_detector(video_path)
    checks.append({"check": "slideshow_detector", "ok": slide.get("ok", True),
                   "detail": f"identical_ratio={slide.get('identical_ratio')}"})

    failed = [c for c in checks if not c["ok"]]
    if failed:
        status = "NEEDS_REVIEW"
        reason = "; ".join(f"{c['check']}: {c['detail']}" for c in failed)
    else:
        status = "PASS"
        reason = "All quality checks passed."

    report = {
        "status": status,
        "review_status": status,
        "checks": checks,
        "actual_duration": probe.get("duration"),
        "declared_duration": declared_duration,
        "reason": reason,
    }
    return report
