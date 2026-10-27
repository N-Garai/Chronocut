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
    from app.tools.audio.transcribe import gemini_audio_transcribe, get_duration
    from app.tools.vision.image_tag import gemini_image_tag_v2

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
            res = await gemini_audio_transcribe(wav, job_id=job_id)
            transcript_text = res.get("full_text", "")
            segments = res.get("segments", [])
    except Exception as e:
        logger.warning(f"video transcribe failed: {e}")

    try:
        if _extract_frame(video_path, frame):
            visual = await gemini_image_tag_v2(frame, job_id=job_id)
    except Exception as e:
        logger.warning(f"video frame tag failed: {e}")

    return {
        "file": video_path,
        "duration": duration,
        "transcript": transcript_text,
        "segments": segments,
        "visual_description": visual.get("description", ""),
        "visual_objects": visual.get("objects", []),
        "visual_mood": visual.get("mood", ""),
    }
