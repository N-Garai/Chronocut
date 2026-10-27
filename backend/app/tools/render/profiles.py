from dataclasses import dataclass, field
from typing import Dict

from app.config import settings


@dataclass
class RenderProfile:
    name: str
    width: int
    height: int
    fps: int
    codec: str = "libx264"
    bitrate: str = "5M"
    audio_bitrate: str = "192k"
    pipeline: str = "ffmpeg"

    def as_dict(self) -> Dict[str, object]:
        return {
            "name": self.name,
            "width": self.width,
            "height": self.height,
            "fps": self.fps,
            "codec": self.codec,
            "bitrate": self.bitrate,
            "audio_bitrate": self.audio_bitrate,
            "pipeline": self.pipeline,
        }


def _clamp_resolution(width: int, height: int) -> tuple:
    """Respect settings.MAX_RENDER_RESOLUTION; scale down proportionally if needed."""
    max_dim = int(getattr(settings, "MAX_RENDER_RESOLUTION", 0) or 0)
    if max_dim <= 0:
        return width, height
    longest = max(width, height)
    if longest <= max_dim:
        return width, height
    scale = max_dim / float(longest)
    return int(round(width * scale)), int(round(height * scale))


def _make(name, width, height, fps, bitrate, audio_bitrate="192k", codec="libx264", pipeline="ffmpeg"):
    w, h = _clamp_resolution(int(width), int(height))
    return RenderProfile(name, w, h, int(fps), codec, bitrate, audio_bitrate, pipeline)


PROFILES: Dict[str, RenderProfile] = {
    "youtube_landscape": _make("youtube_landscape", 1920, 1080, 30, "5M"),
    "youtube_4k": _make("youtube_4k", 3840, 2160, 30, "15M"),
    "shorts": _make("shorts", 1080, 1920, 30, "5M"),
    "reels": _make("reels", 1080, 1920, 30, "5M"),
    "tiktok": _make("tiktok", 1080, 1920, 30, "5M"),
    "square": _make("square", 1080, 1080, 30, "4M"),
    "linkedin": _make("linkedin", 1920, 1080, 30, "4M"),
    "cinematic": _make("cinematic", 2560, 1080, 24, "8M"),
}


def get_profile(name: str) -> RenderProfile:
    return PROFILES.get(name or "", PROFILES["youtube_landscape"])
