import os
import asyncio
import logging
from typing import Dict, Any, List, Optional

logger = logging.getLogger("chronocut.agents.archivist")

from app.agents.sub_agents.audio_transcriber import AudioTranscriberSubAgent
from app.agents.sub_agents.image_tagger import ImageTaggerSubAgent


class ArchivistAgent:
    """Primary agent for multimodal ingestion and cataloging."""

    def __init__(self):
        self.audio_agent = AudioTranscriberSubAgent()
        self.image_agent = ImageTaggerSubAgent()

    async def process(self, input_files: Dict[str, List[str]]) -> Dict[str, Any]:
        audio_files = input_files.get("audio_files", [])
        photo_files = input_files.get("photo_files", [])

        audio_task = self.audio_agent.transcribe_batch(audio_files)
        image_task = self.image_agent.tag_batch(photo_files)

        audio_result, image_result = await asyncio.gather(audio_task, image_task)

        return {
            "transcript": audio_result.get("full_text", ""),
            "segments": audio_result.get("segments", []),
            "image_tags": image_result,
            "audio_files_processed": len(audio_files),
            "photo_files_processed": len(photo_files),
        }
