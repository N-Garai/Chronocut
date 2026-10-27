import logging
import os

logger = logging.getLogger("chronocut.tools.reference")


async def analyze_frames(frames: list[str], job_id: str = None) -> list[str]:
    """Describe each frame (capped at 8) via Gemini.

    Returns a list of one-sentence visual descriptions. Skips unreadable
    frames gracefully.
    """
    from app.tools.llm.call import scored_gemini_call

    descriptions: list[str] = []
    prompt = (
        "Describe the visual grammar of this shot: camera movement, color "
        "palette, motion, subject. One sentence."
    )

    for frame in frames[:8]:
        try:
            if not os.path.isfile(frame):
                continue
            try:
                from PIL import Image  # lazy import
                with Image.open(frame) as im:
                    im.verify()
            except ImportError:
                pass  # PIL not installed; still attempt to read bytes
            except Exception:
                logger.warning(f"frame unreadable (skipping): {frame}")
                continue

            with open(frame, "rb") as f:
                data = f.read()
            if not data:
                continue

            desc = await scored_gemini_call(
                prompt,
                media=[{"data": data, "mime_type": "image/jpeg"}],
                json_mode=False,
                agent="reference",
                tool="reference_analyze",
                job_id=job_id,
            )
            if desc and desc.strip():
                descriptions.append(desc.strip())
        except Exception as e:
            logger.warning(f"analyze_frames failed for a frame: {e}")
            continue

    return descriptions
