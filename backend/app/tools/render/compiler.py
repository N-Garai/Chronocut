import os
import asyncio
import logging
import tempfile
import subprocess
from dataclasses import replace
from typing import Dict, List, Optional

logger = logging.getLogger("chronocut.tools.render")

from app.tools.render.profiles import get_profile, RenderProfile
from app.tools.render.ffmpeg_assembler import (
    build_segment, concatenate_with_transitions, mix_audio, burn_drawtext_final,
)
from app.tools.render.hyperframes_renderer import compose_overlays
from app.tools.render.moviepy_compiler import render_with_moviepy
from app.services.firestore_service import JobStateService
from app.config import settings


def _make_ambient(out_path: str, kind: str, duration: float) -> Optional[str]:
    """J1: generate a continuous ambient bed locally with ffmpeg (no API key).
    kind ∈ {rain, city, drone, none}. Mixed under narration at low gain."""
    kind = (kind or "drone").lower()
    if kind == "rain":
        src = "anoisesrc=color=brown:duration=2:amplitude=0.4"
        filt = "highpass=f=900,lowpass=f=6500,aresample=44100"
    elif kind in ("city", "street", "traffic", "crowd"):
        src = "anoisesrc=color=brown:duration=2:amplitude=0.3"
        filt = "lowpass=f=520,aresample=44100"
    elif kind == "drone":
        src = "sine=frequency=110:duration=2"
        filt = ("sine=frequency=165:duration=2[s];"
                "[0:a][s]amix=inputs=2:duration=longest,volume=0.18,aresample=44100")
    else:
        src = "anoisesrc=color=pink:duration=2:amplitude=0.2"
        filt = "lowpass=f=1200,aresample=44100"
    cmd = [
        "ffmpeg", "-y", "-f", "lavfi", "-i", src,
        "-filter_complex", f"{filt},apad,atrim=0:{duration:.2f}",
        "-c:a", "libmp3lame", "-b:a", "128k", out_path,
    ]
    try:
        res = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
        return out_path if res.returncode == 0 and os.path.exists(out_path) else None
    except Exception as e:
        logger.warning(f"ambient bed synth failed: {e}")
        return None


def _emit(job_id: Optional[str], progress: int, message: str):
    if not job_id:
        return
    try:
        JobStateService.append_event(job_id, {
            "stage": "editor",
            "progress_percent": int(progress),
            "message": message,
        })
    except Exception:
        pass


def _choose_overlay_engine() -> str:
    """Dynamically choose overlay engine based on available memory.

    HyperFrames needs ~800MB+ free (Chromium + ffmpeg + Python). On Render free
    tier (512MB total) we force drawtext to avoid OOM. On larger instances we
    try HyperFrames first and fall back to drawtext on any failure.
    """
    try:
        from app.services.memory import available_mb
        avail_mb = available_mb()
        # 1024MB = safe threshold for HyperFrames on a 2GB+ instance.
        # Render free tier (512MB) will always fall below this.
        if avail_mb >= 1024:
            return "hyperframes"
        return "drawtext"
    except Exception:
        return "drawtext"


def _valid_video(p: Optional[str]) -> bool:
    """A clip we can safely hand to the next stage / serve: exists and non-empty."""
    return bool(p) and os.path.exists(p) and os.path.getsize(p) > 0


def _decodable_video(p: Optional[str]) -> bool:
    """True when the file actually contains a playable video stream.

    Size > 0 is not enough: a mux with a broken/empty audio input under
    ``-shortest`` exits 0 and writes a container with no decodable streams,
    which then 404s at serve time and reports duration=0 in review. When
    ffprobe itself is unavailable we fall back to the size check so a good
    file is never rejected for a missing tool.
    """
    if not _valid_video(p):
        return False
    try:
        import json as _json
        res = subprocess.run(
            ["ffprobe", "-v", "quiet", "-print_format", "json",
             "-show_format", "-show_streams", p],
            capture_output=True, text=True, timeout=30,
        )
        if res.returncode != 0:
            return True
        data = _json.loads(res.stdout or "{}") or {}
        streams = data.get("streams") or []
        has_video = any(s.get("codec_type") == "video" for s in streams)
        try:
            dur = float((data.get("format") or {}).get("duration", 0) or 0)
        except (TypeError, ValueError):
            dur = 0.0
        return has_video and dur >= 0.5
    except Exception:
        return True


def _create_matte(out_path: str, profile, duration: float = 5.0) -> str:
    """Reliably produce a solid-color placeholder clip.

    This is the last-resort fallback when real footage is unavailable, so it MUST
    always yield a valid, non-empty mp4 (never 0 bytes). It does NOT depend on
    ``build_segment``'s filter chain — a filter regression there must not cascade
    into a 0-byte render. Two independent ffmpeg strategies are tried, each
    logging its failure so the cause is visible in the logs.
    """
    try:
        os.makedirs(os.path.dirname(out_path), exist_ok=True)
    except Exception:
        pass
    # Strategy 1: PIL solid PNG at the exact profile resolution, minimal transcode
    # (no zoompan/scale filters — just a loop+format, the most robust command).
    try:
        from PIL import Image  # type: ignore
        w, h = profile.width, profile.height
        img = Image.new("RGB", (w, h), (18, 18, 24))
        png = out_path + ".png"
        img.save(png)
        cmd = [
            "ffmpeg", "-y", "-threads", "1", "-loop", "1", "-i", png,
            "-t", str(duration), "-c:v", profile.codec, "-pix_fmt", "yuv420p",
            "-r", str(profile.fps), "-an", out_path,
        ]
        res = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
        if res.returncode == 0 and os.path.exists(out_path) and os.path.getsize(out_path) > 0:
            return out_path
        logger.warning(f"_create_matte PIL transcode failed (rc={res.returncode}): "
                       f"{(res.stderr or '')[-300:].replace(chr(10), ' ')}")
    except Exception as e:
        logger.warning(f"_create_matte PIL failed: {e}")
    # Strategy 2: lavfi color source (no PIL needed).
    try:
        cmd = [
            "ffmpeg", "-y", "-threads", "1", "-f", "lavfi",
            "-i", f"color=c=black:s={profile.width}x{profile.height}:d={duration}",
            "-c:v", profile.codec, "-pix_fmt", "yuv420p", "-r", str(profile.fps),
            "-t", str(duration), out_path,
        ]
        res = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
        if res.returncode == 0 and os.path.exists(out_path) and os.path.getsize(out_path) > 0:
            return out_path
        logger.warning(f"_create_matte lavfi failed (rc={res.returncode}): "
                       f"{(res.stderr or '')[-300:].replace(chr(10), ' ')}")
    except Exception as e:
        logger.error(f"_create_matte lavfi exception: {e}")
    return ""


def _concat_narration(narration_files: List[str], out_path: str) -> Optional[str]:
    if not narration_files:
        return None
    list_path = out_path + ".txt"
    try:
        with open(list_path, "w", encoding="utf-8") as f:
            for p in narration_files:
                f.write(f"file '{os.path.abspath(p)}'\n")
        cmd = [
            "ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", list_path,
            "-c:a", "aac", "-b:a", "192k", out_path,
        ]
        res = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
        if res.returncode == 0 and os.path.exists(out_path):
            return out_path
    except Exception as e:
        logger.warning(f"narration concat failed: {e}")
    return None


def _clamp_profile_to_memory(profile: RenderProfile, job_id: Optional[str], pname: str) -> RenderProfile:
    """Scale the render profile down when the host can't hold a full-resolution
    x264 encode alongside the API process. On a 512MB free-tier container the
    720p pipeline render OOM-kills the instance mid-job and the sweep requeues
    the same job into the same death loop (UI stuck at 88%). Rendering at <=480p
    lets those containers complete; bigger hosts keep their original profile.
    """
    try:
        from app.services.memory import available_mb
        avail_mb = available_mb()
    except Exception:
        # Unknown memory fails toward the safe (small) path for the same reason
        # as concatenate_with_transitions: assuming "plenty" OOMs the container.
        avail_mb = 0.0
    # 700MB targets the 512MB Render free-tier container. Bigger hosts (e.g. a
    # local dev laptop whose *available* RAM momentarily dips below the default
    # because of unrelated apps) can raise/lower the bar via env without code
    # changes; the threshold, not the total, is what decides clamping.
    try:
        threshold = float(os.environ.get("CHRONOCUT_MEMORY_CLAMP_MB", "700"))
    except ValueError:
        threshold = 700.0
    if avail_mb >= threshold:
        return profile
    longest = max(profile.width, profile.height)
    scale = 480.0 / longest
    w = max(2, int(profile.width * scale) // 2 * 2)
    h = max(2, int(profile.height * scale) // 2 * 2)
    logger.warning(
        f"low memory ({avail_mb:.0f} MB available): rendering {pname} at {w}x{h} "
        f"instead of {profile.width}x{profile.height}"
    )
    _emit(job_id, 10, f"Low memory ({avail_mb:.0f} MB): rendering {pname} at {w}x{h}")
    return replace(profile, width=w, height=h, bitrate="2M", crf=max(profile.crf, 24))


async def render_job(
    storyboard: List[Dict],
    assets_dir: str,
    narration_dir: str,
    profiles: List[str],
    job_id: Optional[str] = None,
    background_music: Optional[str] = None,
    title: str = "",
) -> Dict[str, str]:
    result: Dict[str, str] = {}
    profiles = profiles or ["youtube_landscape"]
    output_root = os.path.join(tempfile.gettempdir(), "chronocut_render", job_id or "default")
    os.makedirs(output_root, exist_ok=True)

    _emit(job_id, 5, f"Starting render for {len(profiles)} profile(s)")

    for pi, pname in enumerate(profiles):
        profile = _clamp_profile_to_memory(get_profile(pname), job_id, pname)
        out_path = os.path.join(output_root, f"{pname}.mp4")
        try:
            tmp = tempfile.mkdtemp(prefix=f"cc_{pname}_")
            segments: List[str] = []
            transitions: List[str] = []
            total_shots = len(storyboard)

            # Collect per-shot sfx file paths (best-effort, never blocks).
            sfx_paths: List[str] = []

            for si, shot in enumerate(storyboard):
                shot_id = shot.get("shot_id")
                vs = shot.get("visual_source", {}) or {}
                file = vs.get("file")
                if not file or not os.path.exists(file):
                    matte = os.path.join(tmp, f"matte_{shot_id}.mp4")
                    file = _create_matte(matte, profile, float(shot.get("duration_seconds", 3.0)))
                if not file or not os.path.exists(file):
                    continue
                seg = os.path.join(tmp, f"seg_{shot_id}.mp4")
                ok = await asyncio.to_thread(
                    build_segment,
                    file, seg, profile,
                    float(shot.get("duration_seconds", 3.0)),
                    vs.get("effect"), shot.get("color_grade"),
                    shot.get("motion"), shot.get("overlay_text"),
                )
                if ok:
                    segments.append(seg)
                    transitions.append(shot.get("transition") or "fade")
                    _emit(job_id, max(20, min(28, int(20 + (si / max(total_shots, 1)) * 8))), f"Built shot {si + 1}/{total_shots}")

                # Optional SFX discovery (graceful, network optional).
                for sfx in (shot.get("sfx") or []):
                    try:
                        from app.tools.audio_post.sfx_bed import sfx_bed
                        path = await asyncio.to_thread(sfx_bed, sfx, tmp)
                        if path:
                            sfx_paths.append(path)
                    except Exception:
                        pass

            if not segments:
                logger.warning(f"profile {pname}: no segments built, using matte")
                _create_matte(out_path, profile, 5.0)
                result[pname] = out_path if _valid_video(out_path) else ""
                continue

            _emit(job_id, 30 + pi * 10, f"Assembling video for {pname}")
            raw_video = os.path.join(tmp, "raw.mp4")
            ok = await asyncio.to_thread(
                concatenate_with_transitions, segments, profile, transitions, raw_video
            )
            if not ok or not os.path.exists(raw_video):
                if settings.ENABLE_MOVIEPY_FALLBACK:
                    fallback = await asyncio.to_thread(
                        render_with_moviepy, storyboard, profile, assets_dir, narration_dir, raw_video
                    )
                    if not fallback:
                        _create_matte(out_path, profile, 5.0)
                        result[pname] = out_path if _valid_video(out_path) else ""
                        continue
                else:
                    logger.warning(f"profile {pname}: ffmpeg concat failed; MoviePy fallback disabled")
                    _create_matte(out_path, profile, 5.0)
                    result[pname] = out_path if _valid_video(out_path) else ""
                    continue
            _emit(job_id, 40 + pi * 10, f"Concat complete for {pname}")

            for seg in segments:
                try:
                    if os.path.exists(seg):
                        os.remove(seg)
                except Exception:
                    pass

            # N: text overlay engine. Dynamically chosen based on available memory:
            # - >= 1GB free: try HyperFrames first, fallback to drawtext.
            # - < 1GB free: use drawtext directly (safe for Render 512MB).
            # This prevents OOM kills on free-tier hosts while still enabling
            # kinetic typography on larger instances.
            engine = _choose_overlay_engine()
            if engine == "hyperframes":
                overlaid = os.path.join(tmp, "raw_overlay.mp4")
                if await asyncio.to_thread(compose_overlays, storyboard, narration_dir,
                                            profile, raw_video, overlaid, title) and _valid_video(overlaid):
                    raw_video = overlaid
                    _emit(job_id, 45 + pi * 10, f"HyperFrames overlay applied for {pname}")
                else:
                    draw = os.path.join(tmp, "raw_drawtext.mp4")
                    if await asyncio.to_thread(burn_drawtext_final, raw_video, storyboard, profile, draw) and _valid_video(draw):
                        raw_video = draw
                        _emit(job_id, 45 + pi * 10, f"HyperFrames unavailable; drawtext fallback for {pname}")
            else:
                # Low-memory path: skip HyperFrames entirely, use drawtext.
                draw = os.path.join(tmp, "raw_drawtext.mp4")
                if await asyncio.to_thread(burn_drawtext_final, raw_video, storyboard, profile, draw) and _valid_video(draw):
                    raw_video = draw
                    _emit(job_id, 45 + pi * 10, f"drawtext overlay applied for {pname} (low-memory mode)")

            # Audio assembly.
            narration_files = []
            for shot in storyboard:
                p = os.path.join(narration_dir, f"{shot.get('shot_id')}.mp3")
                if os.path.exists(p):
                    narration_files.append(p)
            narr_path = await asyncio.to_thread(_concat_narration, narration_files, os.path.join(tmp, "narration.m4a"))
            _emit(job_id, 55 + pi * 10, f"Narration mixed for {pname}")

            # Total video duration (already scaled to requested length) so the
            # audio track is padded to match and the final mux can't collapse.
            total_video_dur = sum(float(shot.get("duration_seconds", 3.0)) for shot in storyboard)

            # J1: continuous ambient bed (free, local). Pick a bed kind from the
            # director/screenwriter sound_bed cues; default to a soft drone.
            ambient_path = None
            if settings.ENABLE_AMBIENT_BED:
                bed_kind = "drone"
                for shot in storyboard:
                    sb = shot.get("sound_bed") or ""
                    if isinstance(sb, str) and sb.strip():
                        bed_kind = sb.strip()
                        break
                try:
                    ambient_path = await asyncio.to_thread(
                        _make_ambient, os.path.join(tmp, "ambient.mp3"), bed_kind, total_video_dur or 5.0
                    )
                except Exception:
                    ambient_path = None

            final_audio = os.path.join(tmp, "final_audio.m4a")
            audio_ok = await asyncio.to_thread(
                mix_audio, None, narr_path, background_music, sfx_paths, final_audio,
                target_duration=total_video_dur, ambient_path=ambient_path,
            )

            # Mux.
            if audio_ok and _valid_video(final_audio) and _valid_video(raw_video):
                cmd = [
                    "ffmpeg", "-y", "-threads", "1",
                    "-i", raw_video, "-i", final_audio,
                    "-c:v", "copy", "-c:a", "aac", "-shortest", out_path,
                ]
                res = await asyncio.to_thread(
                    lambda: subprocess.run(cmd, capture_output=True, text=True, timeout=600)
                )
                # -shortest collapses the output to ~0s when the audio input is
                # broken/empty (exit 0, streamless file) — verify decodability.
                if res.returncode != 0 or not _decodable_video(out_path):
                    out_path = raw_video
            else:
                out_path = raw_video

            _emit(job_id, 90 + pi * 10, f"Muxed final output for {pname}")

            if _decodable_video(out_path):
                result[pname] = out_path
            elif out_path != raw_video and _decodable_video(raw_video):
                result[pname] = raw_video
            else:
                _create_matte(out_path, profile, 5.0)
                result[pname] = out_path if _decodable_video(out_path) else ""

            _emit(job_id, 100, f"Rendered {pname}")
        except Exception as e:
            logger.error(f"render_job profile {pname} failed: {e}")
            try:
                _create_matte(out_path, profile, 5.0)
                if _decodable_video(out_path):
                    result[pname] = out_path
            except Exception:
                pass

    # Guarantee at least one output.
    if not any(result.values()):
        first = profiles[0]
        profile = get_profile(first)
        placeholder = os.path.join(output_root, f"{first}.mp4")
        _create_matte(placeholder, profile, 5.0)
        result[first] = placeholder if os.path.exists(placeholder) else ""

    _emit(job_id, 100, "Render complete")
    return result
