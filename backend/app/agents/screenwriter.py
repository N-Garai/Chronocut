import os
import logging
import asyncio
from typing import Dict, Any, List

logger = logging.getLogger("chronocut.agents.screenwriter")

from app.agents.sub_agents.filler_remover import FillerRemovalSubAgent
from app.agents.sub_agents.narrative_arc import NarrativeArcSubAgent
from app.agents.sub_agents.script_builder import ScriptBuilderSubAgent


class ScreenwriterAgent:
    """Primary agent for narrative construction and script assembly."""

    def __init__(self):
        self.filler_agent = FillerRemovalSubAgent()
        self.arc_agent = NarrativeArcSubAgent()
        self.builder_agent = ScriptBuilderSubAgent()

    async def process(self, archivist_output: Dict[str, Any]) -> Dict[str, Any]:
        segments = archivist_output.get("segments", [])
        if not segments:
            return {"script": [], "total_duration_seconds": 0, "filler_removed_pct": 0}

        cleaned_segments, removal_pct = self.filler_agent.clean_transcript(segments)
        arc = self.arc_agent.analyze_arc(cleaned_segments)
        script = self.builder_agent.build_script(cleaned_segments, arc)

        return {
            **script,
            "filler_removed_pct": removal_pct,
            "narrative_arc": arc.get("arc", []),
        }
