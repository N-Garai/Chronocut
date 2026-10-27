"""VisualMatcherSpecialist — semantic match of a text query to a visual.

Single-query primitive used by the B-roll sourcing stage. Delegates to the
footage resolver (corpus -> Pexels -> Pixabay -> Wikimedia -> NASA ->
Pollinations -> matte). No extra model calls beyond the resolver itself.
"""
from typing import Dict, Any, Optional


class VisualMatcherSpecialist:
    async def match(
        self,
        query: str,
        job_id: Optional[str] = None,
        profile: str = "youtube_landscape",
        duration: float = 5.0,
        avoid_urls: Optional[set] = None,
    ) -> Dict[str, Any]:
        from app.tools.footage import resolve_visual
        return resolve_visual(query, duration, job_id=job_id, profile=profile, avoid_urls=avoid_urls)
