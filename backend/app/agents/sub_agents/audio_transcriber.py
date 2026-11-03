import os
import base64
import logging
import asyncio
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger("chronocut.agents.sub_agents.audio")

from app.config import settings
from app.utils.rate_limiter import with_rate_limit


class AudioTranscriberSubAgent:
    """ARCHIVIST audio worker: transcription through the provider chain.

    Delegates to ``provider_audio_transcribe`` (Meta chunked ASR); this worker
    never talks to a vendor SDK directly.
    """

    def __init__(self, model_name: Optional[str] = None):
        self.model_name = model_name or getattr(settings, "META_ASR_MODEL", "")

    @with_rate_limit(estimated_tokens=5000)
    async def transcribe(self, file_path: str, language: str = "en",
                         job_id: Optional[str] = None) -> Dict[str, Any]:
        from app.tools.audio import provider_audio_transcribe
        try:
            result = await provider_audio_transcribe(file_path, language=language, job_id=job_id)
            logger.info("Transcribed %s via %s: %ss", file_path,
                        result.get("provider"), result.get("duration_seconds", 0))
            return result
        except Exception as e:
            logger.error(f"AudioTranscriber failed for {file_path}: {e}")
            return {"full_text": "", "segments": [], "error": str(e)}

    @with_rate_limit(estimated_tokens=8000)
    async def transcribe_batch(self, file_paths: List[str], language: str = "en",
                               job_id: Optional[str] = None) -> Dict[str, Any]:
        if not file_paths:
            return {"full_text": "", "segments": [], "files": {}}

        semaphore = asyncio.Semaphore(3)
        async def _transcribe_with_limit(fp: str):
            async with semaphore:
                return fp, await self.transcribe(fp, language, job_id=job_id)

        tasks = [_transcribe_with_limit(fp) for fp in file_paths]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        combined_segments = []
        full_text_parts = []
        files_output = {}

        for res in results:
            if isinstance(res, Exception):
                continue
            fp, data = res
            files_output[fp] = data
            combined_segments.extend(data.get("segments", []))
            full_text_parts.append(data.get("full_text", ""))

        combined_segments.sort(key=lambda s: s.get("start", 0))
        return {
            "full_text": "\n".join(full_text_parts),
            "segments": combined_segments,
            "files": files_output,
        }
