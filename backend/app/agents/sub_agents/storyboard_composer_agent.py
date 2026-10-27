"""StoryboardComposerAgent — assembles the shot list from the script.

Delegates to the deterministic storyboard composer (which uses the
BRollSourcingSpecialist for B-roll resolution). No model calls of its own.
"""
from typing import Dict, Any, List, Optional


class StoryboardComposerAgent:
    async def run(
        self,
        script_segments: List[Dict[str, Any]],
        photo_files: List[str],
        profile: str = "youtube_landscape",
        job_id: Optional[str] = None,
        reference_brief: Optional[Dict[str, Any]] = None,
        director_plan: Optional[Dict[Any, Dict[str, Any]]] = None,
        length_seconds: Optional[float] = None,
        cancel_check: Optional[Any] = None,
        user_prompt: Optional[str] = None,
        search_keywords: Optional[List[str]] = None,
        video_clips: Optional[List[Dict[str, Any]]] = None,
    ) -> List[Dict[str, Any]]:
        from app.tools.storyboard.shot_composer import compose_shots
        return await compose_shots(
            script_segments, photo_files, profile=profile,
            job_id=job_id, reference_brief=reference_brief,
            director_plan=director_plan, length_seconds=length_seconds,
            cancel_check=cancel_check, user_prompt=user_prompt,
            search_keywords=search_keywords, video_clips=video_clips,
        )
