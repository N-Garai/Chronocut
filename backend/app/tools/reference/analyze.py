import logging
import os
import tempfile

from app.config import settings
from app.tools.reference.fetch import fetch
from app.tools.reference.transcribe import transcribe
from app.tools.reference.scene_detect import detect_scenes
from app.tools.reference.keyframe_extract import extract_keyframes
from app.tools.reference.analyze_frames import analyze_frames

logger = logging.getLogger("chronocut.tools.reference")

_SAFE_DEFAULTS = {
    "status": "unavailable",
    "transcript": "",
    "segments": [],
    "total_duration": 0.0,
    "pacing_seconds_per_shot": 5.0,
    "hook_seconds": 3.0,
    "structure": "hook -> setup -> payoff",
    "tone_keywords": ["cinematic"],
    "keyframe_descriptions": [],
    "note": "Could not fetch reference (yt-dlp unavailable or blocked)",
}


async def analyze_reference(url: str, job_id: str = None) -> dict:
    """Produce a structured ReferenceBrief from a reference video URL."""
    brief = {
        "reference_url": url,
        "status": "ok",
        "transcript": "",
        "segments": [],
        "total_duration": 0.0,
        "pacing_seconds_per_shot": 5.0,
        "hook_seconds": 3.0,
        "structure": "hook -> setup -> payoff",
        "tone_keywords": ["cinematic"],
        "keyframe_descriptions": [],
        "note": "",
    }

    dest_dir = tempfile.mkdtemp(prefix="chronocut_ref_")
    try:
        video = fetch(url, dest_dir)
    except Exception as e:
        logger.warning(f"fetch raised unexpectedly: {e}")
        video = None

    if not video:
        out = dict(_SAFE_DEFAULTS)
        out["reference_url"] = url
        return out

    try:
        # Transcript
        tr = {}
        try:
            tr = transcribe(video) or {}
        except Exception as e:
            logger.warning(f"transcribe failed: {e}")
        brief["transcript"] = tr.get("full_text", "") or ""
        brief["segments"] = tr.get("segments", []) or []
        brief["total_duration"] = float(tr.get("duration_seconds", 0.0) or 0.0)

        # Scenes -> pacing
        scenes = []
        try:
            scenes = detect_scenes(video) or []
        except Exception as e:
            logger.warning(f"scene detection failed: {e}")
        if scenes:
            diffs = [scenes[i] - scenes[i - 1] for i in range(1, len(scenes))]
            if diffs:
                brief["pacing_seconds_per_shot"] = round(sum(diffs) / len(diffs), 2)

        # Keyframe descriptions
        keyframes = []
        try:
            keyframes = extract_keyframes(video, 8) or []
        except Exception as e:
            logger.warning(f"keyframe extraction failed: {e}")
        if keyframes:
            try:
                brief["keyframe_descriptions"] = await analyze_frames(keyframes, job_id)
            except Exception as e:
                logger.warning(f"frame analysis failed: {e}")

        # Summarize a brief via LLM
        try:
            from app.tools.llm.call import scored_llm_json

            summary_prompt = (
                "Analyze this documentary reference material and return JSON with keys:\n"
                "pacing_seconds_per_shot (number), hook_seconds (number),\n"
                "structure (short string, e.g. 'hook -> setup -> payoff'),\n"
                "tone_keywords (array of strings).\n\n"
                f"Transcript:\n{brief['transcript'][:4000]}\n\n"
                f"Keyframe descriptions:\n" + "\n".join(brief["keyframe_descriptions"])
            )
            summary = await scored_llm_json(
                summary_prompt,
                agent="reference",
                tool="reference_summarize",
                job_id=job_id,
            )
            if isinstance(summary, dict):
                if summary.get("pacing_seconds_per_shot") is not None:
                    brief["pacing_seconds_per_shot"] = float(summary["pacing_seconds_per_shot"])
                if summary.get("hook_seconds") is not None:
                    brief["hook_seconds"] = float(summary["hook_seconds"])
                if summary.get("structure"):
                    brief["structure"] = str(summary["structure"])
                if summary.get("tone_keywords"):
                    brief["tone_keywords"] = list(summary["tone_keywords"])
        except Exception as e:
            logger.warning(f"reference summarize LLM failed; using heuristics: {e}")

    finally:
        # Best-effort temp cleanup.
        try:
            for f in os.listdir(dest_dir):
                os.remove(os.path.join(dest_dir, f))
            os.rmdir(dest_dir)
        except Exception:
            pass

    return brief
