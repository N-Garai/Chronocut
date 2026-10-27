import os
import base64
import logging
from pathlib import Path
from typing import Any, Dict, List

logger = logging.getLogger("chronocut.tools.image")


def describe_image(file_path: str) -> Dict[str, Any]:
    """Analyze an image using the multimodal model. Returns description, objects, era, colors."""
    try:
        import google.generativeai as genai
    except ImportError:
        return {"error": "google-generativeai not installed"}

    api_key = os.getenv("GOOGLE_API_KEY")
    if not api_key:
        return {"error": "GOOGLE_API_KEY not configured"}

    genai.configure(api_key=api_key)
    path = Path(file_path)
    if not path.exists():
        return {"error": f"File not found: {file_path}"}

    try:
        with open(file_path, "rb") as f:
            image_data = f.read()

        model = genai.GenerativeModel(os.getenv("GEMINI_MODEL", "gemini-3.5-flash"))
        prompt = (
            "Analyze this image. Respond in JSON with: "
            "description (one sentence), objects (array of strings), "
            "era (string), colors (array of hex codes), mood (string)."
        )

        response = model.generate_content(
            [
                {"mime_type": "image/jpeg", "data": base64.b64encode(image_data).decode()},
                prompt,
            ]
        )

        return _parse_response(response.text or "{}", path.name)
    except Exception as e:
        logger.error(f"Image analysis failed: {e}")
        return {"error": str(e)}


def _parse_response(raw: str, filename: str) -> Dict[str, Any]:
    import json, re
    match = re.search(r'\{.*\}', raw, re.DOTALL)
    if not match:
        return {"filename": filename, "description": raw[:200], "objects": [], "era": "unknown", "colors": [], "mood": "neutral"}

    try:
        data = json.loads(match.group())
    except json.JSONDecodeError:
        data = {}

    return {
        "filename": filename,
        "description": data.get("description", ""),
        "objects": data.get("objects", []),
        "era": data.get("era", "unknown"),
        "colors": data.get("colors", []),
        "mood": data.get("mood", "neutral"),
    }
