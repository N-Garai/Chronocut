import os
import logging
from typing import Dict, List, Optional

logger = logging.getLogger("chronocut.tools.render")


def render_with_moviepy(
    storyboard: List[Dict],
    profile,
    assets_dir: str,
    narration_dir: str,
    out_path: str,
) -> Optional[str]:
    """Fallback renderer using moviepy. Returns out_path or None on failure."""
    try:
        from moviepy.editor import (  # type: ignore
            ImageClip, VideoFileClip, concatenate_videoclips, AudioFileClip,
            TextClip, CompositeVideoClip,
        )

        clips = []
        for shot in storyboard:
            vs = shot.get("visual_source", {}) or {}
            file = vs.get("file") or vs.get("url")
            if not file or not os.path.exists(file):
                continue
            dur = float(shot.get("duration_seconds", 3.0))
            try:
                if file.lower().endswith((".png", ".jpg", ".jpeg", ".bmp", ".webp", ".gif", ".tif", ".tiff")):
                    clip = ImageClip(file).set_duration(dur)
                else:
                    clip = VideoFileClip(file).subclip(0, min(dur, VideoFileClip(file).duration)).set_duration(dur)
            except Exception as e:
                logger.warning(f"shot clip load failed {file}: {e}")
                continue

            clip = clip.resize((profile.width, profile.height))
            clip = clip.crossfadein(0.4)

            # E4: honor color_grade on the MoviePy fallback path (motion is ffmpeg-only;
            # this path runs only when ENABLE_MOVIEPY_FALLBACK is on). Keep the cinematic
            # intent so the degrade path doesn't regress to flat footage.
            grade = shot.get("color_grade")
            if grade in ("cinematic", "bw", "nostalgic", "professional"):
                try:
                    from moviepy.video.fx import (  # type: ignore
                        colorx, blackwhite,
                    )
                    if grade == "bw":
                        clip = clip.fx(blackwhite)
                    else:
                        # teal-orange-ish lift for cinematic/nostalgic/professional.
                        clip = clip.fx(colorx, 1.08)
                except Exception:
                    pass

            # I1: honor a burned caption on the MoviePy fallback path.
            overlay = shot.get("overlay_text")
            if overlay:
                try:
                    txt = (TextClip(overlay, fontsize=48, color="white",
                                    bg_color="black", size=(profile.width, 80))
                           .set_duration(dur).set_position(("center", "bottom")))
                    clip = CompositeVideoClip([clip, txt])
                except Exception:
                    pass

            audio_path = os.path.join(narration_dir, f"{shot.get('shot_id')}.mp3")
            if os.path.exists(audio_path):
                try:
                    clip = clip.set_audio(AudioFileClip(audio_path).subclip(0, dur))
                except Exception:
                    pass

            clips.append(clip)

        if not clips:
            logger.error("render_with_moviepy: no usable clips")
            return None

        final = concatenate_videoclips(clips, method="compose")
        final.write_videofile(
            out_path, fps=profile.fps, codec=profile.codec,
            audio_codec="aac", bitrate=profile.bitrate,
        )
        if os.path.exists(out_path):
            return out_path
        return None
    except Exception as e:
        logger.error(f"render_with_moviepy failed: {e}")
        return None
