import logging
from typing import Optional, List, Dict, Any

logger = logging.getLogger("chronocut.tools.llm.scorer")


# 7-dimension scoring rubric (M3). Gemini Flash is the only provider on the
# free tier; Pro fallback is disabled unless explicitly enabled via env.
def score_provider(task: str, prompt_tokens: int) -> Dict[str, Any]:
    from app.config import settings
    dims = ["task_fit", "output_quality", "cost", "reliability", "latency", "continuity", "safety"]
    # Flash scores well on cost/latency; we keep it as the default workhorse.
    scores = {
        "task_fit": 0.85,
        "output_quality": 0.82,
        "cost": 0.99,
        "reliability": 0.88,
        "latency": 0.92,
        "continuity": 0.85,
        "safety": 0.9,
    }
    overall = round(sum(scores.values()) / len(dims), 3)
    fallback = "cache_or_error"
    if settings.ENABLE_PRO_FALLBACK:
        fallback = "gemini-pro"
    return {
        "provider": "gemini-flash",
        "model": settings.GEMINI_MODEL,
        "score": overall,
        "dimensions": {d: scores[d] for d in dims},
        "cost_cents": 0.0,
        "fallback": fallback,
    }


def provider_menu() -> List[Dict[str, Any]]:
    from app.config import settings
    menu = [score_provider("default", 0)]
    if settings.ENABLE_PRO_FALLBACK:
        pro = dict(menu[0])
        pro["provider"] = "gemini-pro"
        pro["model"] = settings.GEMINI_MODEL.replace("flash", "pro")
        pro["score"] = 0.95
        pro["fallback"] = "cache_or_error"
        menu.append(pro)
    return menu
