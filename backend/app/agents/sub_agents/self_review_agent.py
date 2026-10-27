"""SelfReviewAgent (M4) — mandatory quality gate before delivery.

Delegates to the review toolkit (ffprobe, frame sampler, audio levels,
delivery promise, slideshow detector). Returns PASS | NEEDS_REVIEW | FAIL.
"""
from typing import Dict, Any, Optional


class SelfReviewAgent:
    async def run(
        self,
        video_path: str,
        declared_duration: float,
        job_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        from app.tools.review.self_review import run_self_review
        return await run_self_review(video_path, declared_duration, job_id=job_id)
