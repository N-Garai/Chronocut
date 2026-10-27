"""BRollSourcingSpecialist — cascading B-roll retrieval for the Director.

Wraps VisualMatcherSpecialist so the fallback chain is encapsulated behind a
single agent the StoryboardComposer (and Director) can call per shot.
"""
from typing import Dict, Any, Optional


class BRollSourcingSpecialist:
    async def resolve(
        self,
        query: str,
        duration: float = 5.0,
        job_id: Optional[str] = None,
        profile: str = "youtube_landscape",
        avoid_urls: Optional[set] = None,
    ) -> Dict[str, Any]:
        from app.agents.sub_agents.visual_matcher_specialist import VisualMatcherSpecialist
        return await VisualMatcherSpecialist().match(
            query, job_id=job_id, profile=profile, duration=duration, avoid_urls=avoid_urls
        )
