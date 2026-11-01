import logging
from typing import Optional, List, Dict, Any

logger = logging.getLogger("chronocut.tools.llm.scorer")


# 7-dimension scoring rubric. One provider is active per deployment: the hosted
# Meta Model API by default, or a local open-weights endpoint via
# LLM_PROVIDER=local. No provider fallback is enabled unless explicitly
# configured via env.
def score_provider(task: str, prompt_tokens: int) -> Dict[str, Any]:
    from app.config import settings
    badge = settings.model_badge
    dims = ["task_fit", "output_quality", "cost", "reliability", "latency", "continuity", "safety"]
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
    return {
        "provider": badge[0],
        "model": badge[1],
        "score": overall,
        "dimensions": {d: scores[d] for d in dims},
        "cost_cents": 0.0,
        "fallback": fallback,
    }


def provider_menu() -> List[Dict[str, Any]]:
    from app.config import settings
    menu = [score_provider("default", 0)]
    return menu
