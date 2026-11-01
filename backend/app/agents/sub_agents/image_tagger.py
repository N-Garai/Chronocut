import os
import logging
import asyncio
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger("chronocut.agents.sub_agents.image")

from app.config import settings
from app.utils.rate_limiter import with_rate_limit
from app.tools.llm.call import scored_llm_json


class ImageTaggerSubAgent:
    """ARCHIVIST vision worker: image tagging through the provider layer.

    Uses the configured provider (Meta Model API by default, or a local
    OpenAI-compatible endpoint) with the image as media input and a strict
    JSON schema so tagging stays a single code path. Degrades gracefully to
    an empty tag set when no provider credentials are configured.
    """

    def __init__(self, model_name: Optional[str] = None):
        self.model_name = model_name or settings.META_TEXT_MODEL

    @with_rate_limit(estimated_tokens=3000)
    async def tag_single(self, file_path: str, job_id: Optional[str] = None) -> Dict[str, Any]:
        try:
            with open(file_path, "rb") as f:
                data = f.read()
        except Exception as e:
            logger.error(f"ImageTagger failed to read {file_path}: {e}")
            return {"filename": file_path, "error": str(e)}

        mime = "image/jpeg"
        if file_path.lower().endswith(".png"):
            mime = "image/png"
        elif file_path.lower().endswith(".webp"):
            mime = "image/webp"

        schema = {
            "name": "image_tags",
            "schema": {
                "type": "object",
                "properties": {
                    "description": {"type": "string"},
                    "objects": {"type": "array", "items": {"type": "string"}},
                    "era": {"type": "string"},
                    "colors": {"type": "array", "items": {"type": "string"}},
                    "mood": {"type": "string"},
                    "setting": {"type": "string"},
                },
                "required": ["description"],
            },
        }
        try:
            result = await scored_llm_json(
                "Describe this image for a historical documentary storyboard.",
                system=(
                    "You are a documentary photo archivist. Analyze the image and "
                    "respond ONLY with JSON."
                ),
                job_id=job_id,
                agent="archivist",
                tool="image_tag",
                temperature=0.3,
                max_output_tokens=1024,
                media=[{"data": data, "mime_type": mime}],
                json_mode=True,
                require_keys=["description"],
            )
            logger.info("Tagged %s: %s...", file_path, str(result.get("description", ""))[:50])
            return {
                "filename": os.path.basename(file_path),
                "description": result.get("description", ""),
                "objects": result.get("objects", []),
                "era": result.get("era", "unknown"),
                "colors": result.get("colors", []),
                "mood": result.get("mood", "neutral"),
                "setting": result.get("setting", ""),
            }
        except Exception as e:
            logger.error(f"ImageTagger failed for {file_path}: {e}")
            return {"filename": file_path, "error": str(e)}

    @with_rate_limit(estimated_tokens=15000)
    async def tag_batch(self, file_paths: List[str], max_concurrency: int = 3,
                        job_id: Optional[str] = None) -> Dict[str, Any]:
        if not file_paths:
            return {}

        semaphore = asyncio.Semaphore(max_concurrency)

        async def _tag_with_limit(fp: str):
            async with semaphore:
                return fp, await self.tag_single(fp, job_id=job_id)

        tasks = [_tag_with_limit(fp) for fp in file_paths]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        output = {}
        for res in results:
            if isinstance(res, Exception):
                continue
            fp, data = res
            output[fp] = data
        return output
