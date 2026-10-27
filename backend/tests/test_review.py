import asyncio

from app.tools.review.delivery_promise import delivery_promise
from app.tools.review.self_review import run_self_review


def test_delivery_promise_pass():
    assert delivery_promise(60.0, 60.0)["ok"] is True


def test_delivery_promise_fail_outside_tolerance():
    # 55 vs 60 -> ~8.3% delta > 5% tolerance
    assert delivery_promise(55.0, 60.0, tolerance=0.05)["ok"] is False


def test_self_review_missing_file_is_graceful():
    rep = asyncio.run(run_self_review("/nonexistent/video.mp4", 60.0, job_id="test"))
    assert isinstance(rep, dict)
    assert rep.get("status") in ("PASS", "NEEDS_REVIEW", "FAIL")
