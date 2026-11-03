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
    preset: str = "medium"
    crf: int = 20

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
            "preset": self.preset,
            "crf": self.crf,
        }


def _clamp_resolution(width: int, height: int) -> tuple:
    """Respect settings.MAX_RENDER_RESOLUTION; scale down proportionally if needed.

    Always returns even dimensions: yuv420p/H.264 encoders reject odd widths or
    heights ("height not divisible by 2"), and a proportional clamp of 16:9
    sources (1280x720 -> 720x405) otherwise yields an odd side.
    """

    def _even(v: int) -> int:
        v = int(v)
        return max(2, v - (v % 2))

    max_dim = int(getattr(settings, "MAX_RENDER_RESOLUTION", 0) or 0)
    if max_dim <= 0:
        return _even(width), _even(height)
    longest = max(width, height)
    if longest <= max_dim:
        return _even(width), _even(height)
    scale = max_dim / float(longest)
    return _even(round(width * scale)), _even(round(height * scale))


def _make(name, width, height, fps, bitrate, audio_bitrate="192k", codec="libx264",
          pipeline="ffmpeg", preset="medium", crf=20):
    w, h = _clamp_resolution(int(width), int(height))
    return RenderProfile(name, w, h, int(fps), codec, bitrate, audio_bitrate, pipeline,
                         preset=preset, crf=crf)


# Output format profiles. `preview_480` is the fast timeline preview; the final
# profiles trade speed for quality. MAX_RENDER_RESOLUTION clamps the tallest
# profiles to the configured ceiling (host workers can run the full 1080/4K
# set; the API container default stays at 720).
PROFILES: Dict[str, RenderProfile] = {
    "preview_480": _make("preview_480", 854, 480, 30, "1M", preset="ultrafast", crf=28),
    "youtube_landscape": _make("youtube_landscape", 1280, 720, 30, "5M", preset="medium", crf=20),
    "youtube_1080": _make("youtube_1080", 1920, 1080, 30, "8M", preset="medium", crf=20),
    "instagram_portrait": _make("instagram_portrait", 1080, 1920, 30, "5M", preset="medium", crf=21),
    "instagram_square": _make("instagram_square", 1080, 1080, 30, "4M", preset="medium", crf=21),
    "youtube_4k": _make("youtube_4k", 3840, 2160, 30, "15M", preset="medium", crf=20),
    "shorts": _make("shorts", 1080, 1920, 30, "5M", preset="medium", crf=21),
    "reels": _make("reels", 1080, 1920, 30, "5M", preset="medium", crf=21),
    "tiktok": _make("tiktok", 1080, 1920, 30, "5M", preset="medium", crf=21),
    "square": _make("square", 1080, 1080, 30, "4M", preset="medium", crf=21),
    "linkedin": _make("linkedin", 1920, 1080, 30, "4M", preset="medium", crf=20),
    "cinematic": _make("cinematic", 2560, 1080, 24, "8M", preset="medium", crf=20),
}


def get_profile(name: str) -> RenderProfile:
    return PROFILES.get(name or "", PROFILES["youtube_landscape"])
