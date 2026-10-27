import os
import logging
import subprocess
import tempfile
from typing import Dict, Any, List, Optional
from pathlib import Path

logger = logging.getLogger("chronocut.tools.video")


def extract_video_metadata(file_path: str) -> Dict[str, Any]:
    """Extract metadata from a video file using ffprobe."""
    try:
        path = Path(file_path)
        if not path.exists():
            return {"error": f"File not found: {file_path}"}

        result = subprocess.run(
            [
                "ffprobe",
                "-v", "quiet",
                "-print_format", "json",
                "-show_format",
                "-show_streams",
                str(path),
            ],
            capture_output=True,
            text=True,
            timeout=30,
        )

        if result.returncode != 0:
            return {"error": f"ffprobe failed: {result.stderr}"}

        import json
        data = json.loads(result.stdout)

        video_stream = next(
            (s for s in data.get("streams", []) if s.get("codec_type") == "video"),
            None,
        )
        audio_stream = next(
            (s for s in data.get("streams", []) if s.get("codec_type") == "audio"),
            None,
        )

        format_info = data.get("format", {})

        return {
            "filename": path.name,
            "duration_seconds": float(format_info.get("duration", 0)),
            "size_bytes": int(format_info.get("size", 0)),
            "video": {
                "codec": video_stream.get("codec_name") if video_stream else None,
                "width": video_stream.get("width") if video_stream else None,
                "height": video_stream.get("height") if video_stream else None,
                "fps": eval(video_stream.get("r_frame_rate", "0/1")) if video_stream else None,
            } if video_stream else None,
            "audio": {
                "codec": audio_stream.get("codec_name") if audio_stream else None,
                "sample_rate": audio_stream.get("sample_rate") if audio_stream else None,
            } if audio_stream else None,
        }
    except Exception as e:
        logger.error(f"Video metadata extraction failed: {e}")
        return {"error": str(e)}


def extract_video_frames(file_path: str, num_frames: int = 5) -> List[str]:
    """Extract frames from a video file. Returns paths to extracted frame images."""
    try:
        path = Path(file_path)
        if not path.exists():
            return []

        output_dir = tempfile.mkdtemp(prefix="chronocut_frames_")
        frames = []

        metadata = extract_video_metadata(file_path)
        if "error" in metadata:
            return []

        duration = metadata.get("duration_seconds", 0)
        if duration <= 0:
            return []

        interval = max(1, duration / (num_frames + 1))

        for i in range(1, num_frames + 1):
            timestamp = i * interval
            output_path = os.path.join(output_dir, f"frame_{i:03d}.jpg")
            subprocess.run(
                [
                    "ffmpeg",
                    "-ss", str(timestamp),
                    "-i", str(path),
                    "-vframes", "1",
                    "-q:v", "2",
                    str(output_path),
                ],
                capture_output=True,
                timeout=10,
            )
            if os.path.exists(output_path):
                frames.append(output_path)

        return frames
    except Exception as e:
        logger.error(f"Frame extraction failed: {e}")
        return []


def process_video_file(file_path: str) -> Dict[str, Any]:
    """Process a video file: extract metadata and frames."""
    metadata = extract_video_metadata(file_path)
    frames = extract_video_frames(file_path, num_frames=5)

    return {
        "metadata": metadata,
        "extracted_frames": frames,
        "can_be_used_as_broll": len(frames) > 0,
        "suggested_use": "broll" if metadata.get("duration_seconds", 0) < 30 else "background",
    }
