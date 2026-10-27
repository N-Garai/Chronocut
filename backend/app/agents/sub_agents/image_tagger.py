import os
import base64
import logging
import asyncio
from pathlib import Path
from typing import Any, Dict, List

logger = logging.getLogger("chronocut.agents.sub_agents.image")

from app.utils.rate_limiter import with_rate_limit


class ImageTaggerSubAgent:
    """Sub-agent specialized in visual asset analysis and tagging."""

    def __init__(self, model_name: str = "gemini-3.5-flash"):
        self.model_name = model_name

    @with_rate_limit(estimated_tokens=3000)
    async def tag_single(self, file_path: str) -> Dict[str, Any]:
        from app.tools.image_tools import describe_image
        try:
            result = await asyncio.to_thread(describe_image, file_path)
            logger.info(f"Tagged {file_path}: {result.get('description', '')[:50]}...")
            return result
        except Exception as e:
            logger.error(f"ImageTagger failed for {file_path}: {e}")
            return {"filename": file_path, "error": str(e)}

    @with_rate_limit(estimated_tokens=15000)
    async def tag_batch(self, file_paths: List[str], max_concurrency: int = 3) -> Dict[str, Any]:
        if not file_paths:
            return {}

        semaphore = asyncio.Semaphore(max_concurrency)

        async def _tag_with_limit(fp: str):
            async with semaphore:
                return fp, await self.tag_single(fp)

        tasks = [_tag_with_limit(fp) for fp in file_paths]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        output = {}
        for res in results:
            if isinstance(res, Exception):
                continue
            fp, data = res
            output[fp] = data
        return output
