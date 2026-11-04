"""Generated B-roll video via local open-weights text-to-video models.

A strictly opt-in companion to the Meta Image stills generator: where a shot
cannot be covered by any stock provider (and generated stills are off or
fail), a short clip can be synthesized locally with a diffusers
text-to-video model instead of falling straight to a matte.

Defaults to provider ``off`` — a video model holds gigabytes of weights in
RAM/VRAM and takes minutes per clip on CPU, so it must never engage unless
the operator explicitly sets ``VIDEO_GEN_PROVIDER=local``. Even then it is
capped per job and hard-timeouts in a child process so a slow model can
never stall a pipeline or bloat the API process.
"""
from app.tools.videoagen.local import (
    generate_clip,
    try_generate_shot_video,
    video_gen_available,
)

__all__ = ["generate_clip", "try_generate_shot_video", "video_gen_available"]
