import logging
import os
from typing import Optional, Dict, Any, List

logger = logging.getLogger("chronocut.tools.vision")

__all__ = ["gemini_image_tag_v2"]


async def gemini_image_tag_v2(file_path: str, job_id: Optional[str] = None) -> Dict[str, Any]:
    """Tag an image with Gemini vision; cache result by file SHA256."""
    from app.services.firestore_service import JobStateService, sha256_bytes
    from app.tools.llm.call import scored_gemini_json

    try:
        with open(file_path, "rb") as f:
            data = f.read()
    except Exception as e:
        return {"filename": os.path.basename(file_path), "error": str(e)}

    sha = sha256_bytes(data)
    cached = JobStateService.corpus_get("assets", sha)
    if cached and cached.get("image_tags"):
        return cached["image_tags"]

    mime = "image/jpeg"
    if file_path.lower().endswith(".png"):
        mime = "image/png"
    elif file_path.lower().endswith(".webp"):
        mime = "image/webp"

    system = (
        "You are a documentary photo archivist. Analyze the image and respond ONLY with JSON: "
        "{\"description\": str, \"objects\": [str], \"era\": str, \"colors\": [str hex], "
        "\"mood\": str, \"setting\": str}."
    )
    prompt = "Describe this image for a historical documentary storyboard."
    try:
        result = await scored_gemini_json(
            prompt, system=system, job_id=job_id, agent="archivist",
            tool="gemini_image_tag_v2", temperature=0.3, max_output_tokens=1024,
            media=[{"data": data, "mime_type": mime}],
        )
    except Exception as e:
        logger.error(f"Image tag failed: {e}")
        result = {}

    out = {
        "filename": os.path.basename(file_path),
        "description": result.get("description", ""),
        "objects": result.get("objects", []),
        "era": result.get("era", "unknown"),
        "colors": result.get("colors", []),
        "mood": result.get("mood", "neutral"),
        "setting": result.get("setting", ""),
    }
    try:
        JobStateService.asset_cache_put(sha, {"image_tags": out, "url": None, "local_path": file_path})
    except Exception:
        pass
    return out
