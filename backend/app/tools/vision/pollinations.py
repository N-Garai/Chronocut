import logging
import os
import urllib.parse
from typing import Optional, Dict, Any

logger = logging.getLogger("chronocut.tools.vision")

__all__ = ["pollinations_image_generate"]


def pollinations_image_generate(prompt: str, out_path: Optional[str] = None) -> Dict[str, Any]:
    """Generate a fallback image via Pollinations.ai (free, no API key)."""
    import tempfile
    import requests

    if out_path is None:
        out_path = os.path.join(tempfile.gettempdir(), f"chronocut_poll_{abs(hash(prompt))}.png")

    try:
        encoded = urllib.parse.quote(prompt[:200])
        url = f"https://image.pollinations.ai/prompt/{encoded}"
        resp = requests.get(url, timeout=60)
        resp.raise_for_status()
        with open(out_path, "wb") as f:
            f.write(resp.content)
        return {"type": "pollinations_ai", "url": url, "file": out_path, "source": "pollinations",
                "effect": "ken_burns_slow_zoom", "note": "AI-generated fallback image"}
    except Exception as e:
        logger.error(f"Pollinations failed: {e}")
        # Procedural matte fallback
        try:
            from PIL import Image, ImageDraw, ImageFont
            img = Image.new("RGB", (1280, 720), (18, 18, 22))
            d = ImageDraw.Draw(img)
            try:
                font = ImageFont.load_default()
            except Exception:
                font = None
            d.text((40, 340), prompt[:80], fill=(220, 220, 220), font=font)
            img.save(out_path)
            return {"type": "color_matte", "url": None, "file": out_path, "source": "generated",
                    "effect": "none", "note": "procedural matte"}
        except Exception:
            return {"type": "color_matte", "url": None, "file": None, "source": "generated", "effect": "none"}
