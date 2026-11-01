"""Ingest an uploaded video for the 'from_media' pipeline.

A from_media job should be built *from the uploaded content*, not ignored. For
each uploaded video we: (1) extract its audio and transcribe it with an LLM so the
narration is derived from what was actually said/shown, and (2) sample a keyframe
and tag it with an LLM so the visual content is known. The original clip is then
exposed as usable footage for the storyboard composer.
"""
import logging
import os
import subprocess
import tempfile
from typing import Dict, Any, Optional

logger = logging.getLogger("chronocut.tools.media.ingest_video")


def _extract_audio(video_path: str, out_wav: str) -> bool:
    try:
        subprocess.run(
            ["ffmpeg", "-y", "-i", video_path, "-vn", "-ac", "1", "-ar", "16000",
             "-f", "wav", out_wav],
            capture_output=True, text=True, timeout=300,
        )
        return os.path.exists(out_wav)
    except Exception as e:
        logger.warning(f"video audio extract failed: {e}")
        return False


def _extract_frame(video_path: str, out_img: str) -> bool:
    try:
        subprocess.run(
            ["ffmpeg", "-y", "-ss", "00:00:01", "-i", video_path, "-frames:v", "1",
             "-q:v", "2", out_img],
            capture_output=True, text=True, timeout=120,
        )
        return os.path.exists(out_img)
    except Exception as e:
        logger.warning(f"video frame extract failed: {e}")
        return False


async def ingest_video_file(video_path: str, job_id: Optional[str] = None) -> Dict[str, Any]:
    """Analyze an uploaded video (LLM transcription + keyframe tagging).

    Returns a dict with the clip path, its duration, the transcribed narration,
    and a visual description used to brief the screenwriter.
    """
    from app.tools.audio.transcribe import provider_audio_transcribe, get_duration
    from app.agents.sub_agents.image_tagger import ImageTaggerSubAgent

    tmp = tempfile.mkdtemp(prefix="cc_vid_")
    base = os.path.splitext(os.path.basename(video_path))[0]
    wav = os.path.join(tmp, f"{base}.wav")
    frame = os.path.join(tmp, f"{base}.jpg")

    duration = get_duration(video_path)
    transcript_text = ""
    segments = []
    visual: Dict[str, Any] = {}

    try:
        if _extract_audio(video_path, wav):
            res = await provider_audio_transcribe(wav, job_id=job_id)
            transcript_text = res.get("full_text", "")
            segments = res.get("segments", [])
    except Exception as e:
        logger.warning(f"video transcribe failed: {e}")

    try:
        if _extract_frame(video_path, frame):
            visual = await ImageTaggerSubAgent().tag_single(frame, job_id=job_id)
    except Exception as e:
        logger.warning(f"video frame tag failed: {e}")

    # Whole-clip understanding (Files API when uploadable, keyframes otherwise).
    understanding = await _understand_video(video_path, job_id=job_id,
                                           duration=duration,
                                           transcript=transcript_text)

    description = str(visual.get("description", ""))
    if understanding.get("summary"):
        description = f"{description} {understanding['summary']}".strip()

    return {
        "file": video_path,
        "duration": duration,
        "transcript": transcript_text,
        "segments": segments,
        "visual_description": description,
        "visual_objects": visual.get("objects", []),
        "visual_mood": visual.get("mood", ""),
        "understanding": understanding,
    }


async def _understand_video(video_path: str, *, job_id: Optional[str] = None,
                            duration: float = 0.0, transcript: str = "") -> Dict[str, Any]:
    """Structured whole-clip analysis; degrades to ``{}`` with no provider."""
    if _extract_frame is None:
        return {}
    try:
        from app.tools.llm.provider import get_provider
        provider = get_provider()
        if not hasattr(provider, "describe_video"):
            return {}
        prompt = (
            "Summarize this uploaded clip for a documentary editor. Reply with JSON only: "
            '{"summary": str, "setting": str, "subjects": [str], "actions": [str], '
            '"mood": str, "notable_moments": [{"at_s": number, "what": str}]}.'
            f" Clip duration: {round(float(duration or 0.0), 2)}s."
        )
        if transcript:
            prompt += f" Its audio says: {transcript[:600]}"
        res = await provider.describe_video(video_path, prompt=prompt, job_id=job_id)
        if not isinstance(res, dict):
            return {}
        out = {k: res.get(k) for k in ("summary", "setting", "subjects", "actions",
                                       "mood", "notable_moments") if res.get(k) is not None}
        if out:
            try:
                from app.agents.telemetry import record_activity
                record_activity(job_id, agent="archivist", action="video_understanding",
                                status="succeeded", provider=getattr(provider, "name", None),
                                model=getattr(provider, "default_model", None),
                                detail=str(out.get("summary") or "clip understood")[:160])
            except Exception:
                pass
        return out
    except Exception as e:
        logger.warning("video understanding unavailable: %s", e)
        return {}
