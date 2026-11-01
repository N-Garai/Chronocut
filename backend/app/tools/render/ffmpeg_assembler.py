import os
import re
import logging
import subprocess
import tempfile
from typing import List, Optional, Dict, Any

logger = logging.getLogger("chronocut.tools.render")

from app.config import settings

_IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".bmp", ".gif", ".webp", ".tiff", ".tif"}

# D1: camera-move recipes that are implemented as zoompan (images) or crop-pan
# (video). Kept as a set so the renderer can decide which branch to use.
_ZOOMPAN_MOVES = {"push_in", "pull_out", "pan_left", "pan_right", "parallax"}


def _probe_duration(path: str) -> float:
    try:
        result = subprocess.run(
            [
                "ffprobe", "-v", "quiet", "-print_format", "json",
                "-show_entries", "format=duration", "-i", path,
            ],
            capture_output=True, text=True, timeout=30,
        )
        if result.returncode != 0:
            return 0.0
        import json
        data = json.loads(result.stdout)
        d = float(data.get("format", {}).get("duration", 0.0) or 0.0)
        return d
    except Exception:
        return 0.0


def _is_image(path: str) -> bool:
    return os.path.splitext(path)[1].lower() in _IMAGE_EXTS


def _xfade_type(transition: str) -> str:
    t = (transition or "").lower()
    if "dissolve" in t:
        return "dissolve"
    if "wipe_left" in t or "wipeleft" in t:
        return "wipeleft"
    if "wipe_right" in t or "wiperight" in t:
        return "wiperight"
    if "fadeblack" in t:
        return "fadeblack"
    if "cut" in t:
        return "fade"
    return "fade"


def _xfade_dur(transition: str) -> float:
    t = (transition or "").lower()
    if "cut" in t:
        return 0.5
    m = re.search(r"(\d+\.?\d*)s", t)
    if m:
        try:
            return max(0.1, float(m.group(1)))
        except ValueError:
            return 0.5
    return 0.5


def _image_zoompan(motion: str, w: int, h: int, fps: int, nf: int) -> str:
    """D1: directional camera moves on stills (reliable zoompan path). NF is the
    frame count (duration*fps) substituted in Python because ffmpeg has no NF var."""
    nf1 = max(2, nf - 1)
    cx = "x='iw/2-(iw/zoom/2)'"
    cy = "y='ih/2-(ih/zoom/2)'"
    base = f"s={w}x{h}:fps={fps}"
    if motion == "push_in":
        z = "z='min(zoom+0.0010,1.35)'"
    elif motion == "pull_out":
        z = f"z='max(1.0,1.35-(on/{nf1})*0.35)'"
    elif motion == "pan_left":
        z = "z='1.2'"
        cx = f"x='(iw/zoom - {w})*(on/{nf1})'"
    elif motion == "pan_right":
        z = "z='1.2'"
        cx = f"x='(iw/zoom - {w})*(1 - on/{nf1})'"
    elif motion == "parallax":
        z = "z='min(zoom+0.0006,1.2)'"
        cx = f"x='iw/2-(iw/zoom/2)+(on/{nf1})*(iw*0.08)'"
    else:
        z = "z='min(zoom+0.0008,1.30)'"
    return f"zoompan={z}:d=1:{cx}:{cy}:{base}"


def _video_pan(motion: str, w: int, h: int, dur: float) -> str:
    """D1: fake camera moves on video via time-based crop (avoids zoompan stutter
    on video). Pre-scaled 1.3x so there is room to pan within."""
    sw, sh = int(w * 1.3), int(h * 1.3)
    cx0 = f"(iw-{w})/2"
    cy0 = f"(ih-{h})/2"
    if motion == "push_in":
        x = f"x='{cx0}*(1 - t/{dur})'"
    elif motion == "pull_out":
        x = f"x='{cx0}*(t/{dur})'"
    elif motion == "pan_left":
        x = f"x='{cx0}*(1 - t/{dur})'"
    elif motion == "pan_right":
        x = f"x='{cx0}*(t/{dur})'"
    elif motion == "parallax":
        x = f"x='{cx0} + (t/{dur})*({cx0})*0.3'"
    else:
        x = f"x={cx0}"
    y = f"y={cy0}"
    return f"scale={sw}:{sh}:force_original_aspect_ratio=increase,crop={w}:{h}:{x}:{y}"


def _color_grade_filter(grade: Optional[str]) -> Optional[str]:
    """E1: cinematic look presets (free, pure ffmpeg)."""
    if grade == "cinematic":
        # teal-orange lift + gentle vignette + soft shallow-DoF blur.
        return "eq=r=1.06:b=1.06:g=1.0:saturation=1.12:v=1.02," \
               "vignette=PI/4:alpha=0.18," \
               "gblur=sigma=1.2"
    if grade == "bw":
        return "hue=s=0,eq=contrast=1.12:saturation=0:b=0.02," \
               "vignette=PI/4:alpha=0.12"
    if grade == "anamorphic":
        return "eq=saturation=1.05:contrast=1.08,setsar=1," \
               "vignette=PI/5:alpha=0.15"
    return None


def _build_vf(
    profile,
    is_image: bool,
    effect: Optional[str],
    color_grade: Optional[str],
    motion: Optional[str],
    overlay_text: Optional[str],
    duration: float = 5.0,
):
    """Return (vf_string, temp_textfile_path_or_None)."""
    w, h, fps = profile.width, profile.height, profile.fps
    chain: List[str] = []
    textfile = None

    effect = (effect or "").lower()
    motion = motion or None
    grade = _color_grade_filter(color_grade)

    if is_image:
        if "ken_burns" in effect or motion in _ZOOMPAN_MOVES:
            chain.append(f"scale={w}:{h}:force_original_aspect_ratio=increase")
            chain.append(f"crop={w}:{h}")
            if motion in _ZOOMPAN_MOVES:
                nf = max(2, int(round(duration * fps)))
                chain.append(_image_zoompan(motion, w, h, fps, nf))
            else:
                # default Ken Burns slow zoom
                chain.append(
                    f"zoompan=z='min(zoom+0.0008,1.30)':d=1:"
                    f"x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':s={w}x{h}:fps={fps}"
                )
        else:
            chain.append(f"scale={w}:{h}:force_original_aspect_ratio=decrease")
            chain.append(f"pad={w}:{h}:(ow-iw)/2:(oh-ih)/2")
        if motion == "slowmo_0.5":
            chain.append("setpts=1.5*PTS")
        elif motion == "speed_ramp":
            chain.append("setpts=0.6*PTS")
    else:
        if motion in _ZOOMPAN_MOVES:
            chain.append(_video_pan(motion, w, h, duration))
        else:
            chain.append(f"scale={w}:{h}:force_original_aspect_ratio=decrease")
            chain.append(f"pad={w}:{h}:(ow-iw)/2:(oh-ih)/2")
        if motion == "slowmo_0.5":
            chain.append("setpts=1.5*PTS")
        elif motion == "speed_ramp":
            chain.append("setpts=0.6*PTS")

    if grade:
        chain.append(grade)

    # I1/I2/N: burn captions only when the drawtext engine is active. When the
    # HyperFrames engine is selected, captions are handled by the overlay composer
    # (hyperframes_renderer.compose_overlays) so we never double-burn text.
    if overlay_text and settings.text_overlay_engine == "drawtext":
        try:
            fd, textfile = tempfile.mkstemp(prefix="cc_ovl_", suffix=".txt")
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                f.write(overlay_text)
            # I1: fade the caption in/out so it never pops.
            dur = max(1.0, duration)
            alpha = (f"alpha='if(lt(t,0.3),t/0.3,"
                     f"if(gt(t,{dur}-0.3),({dur}-t)/0.3,1))'")
            chain.append(
                f"drawtext=textfile='{textfile}':fontcolor=white:fontsize=48:"
                "box=1:boxcolor=black@0.4:boxborderw=8:"
                f"x=(w-tw)/2:y=h-th-40:{alpha}"
            )
        except Exception as e:
            logger.warning(f"overlay text setup failed: {e}")

    return ",".join(chain), textfile


def burn_drawtext_final(video_in: str, storyboard: List[Dict], profile, out_path: str) -> bool:
    """N fallback: burn per-shot captions onto an already-cut silent video using
    timed drawtext filters (one layer per shot). Used when the HyperFrames engine
    is selected but the overlay render fails, so captions are never lost.
    """
    try:
        import tempfile as _tf
        chain: List[str] = []
        running = 0.0
        for shot in storyboard:
            txt = shot.get("overlay_text")
            if not txt or not str(txt).strip():
                running += float(shot.get("duration_seconds", 3.0))
                continue
            start = running
            dur = float(shot.get("duration_seconds", 3.0))
            running += dur
            end = start + dur
            fd, tf = _tf.mkstemp(prefix="cc_cap_", suffix=".txt")
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                f.write(str(txt))
            alpha = (f"alpha='if(lt(t,{start + 0.3:.2f}),(t-{start:.2f})/0.3,"
                     f"if(gt(t,{end - 0.3:.2f}),({end - 0.3:.2f}-t)/0.3,1))'")
            chain.append(
                f"drawtext=textfile='{tf}':fontcolor=white:fontsize=48:box=1:"
                f"boxcolor=black@0.4:boxborderw=8:x=(w-tw)/2:y=h-th-40:{alpha}:"
                f"enable='between(t,{start:.2f},{end:.2f})'"
            )
        if not chain:
            cmd = ["ffmpeg", "-y", "-threads", "1", "-preset", "ultrafast", "-i", video_in, "-c:v", "copy", "-an", out_path]
        else:
            cmd = ["ffmpeg", "-y", "-threads", "1", "-preset", "ultrafast", "-i", video_in, "-vf", ",".join(chain),
                   "-c:v", profile.codec, "-pix_fmt", "yuv420p", "-r", str(profile.fps), "-an", out_path]
        res = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
        return res.returncode == 0 and os.path.exists(out_path) and os.path.getsize(out_path) > 0
    except Exception as e:
        logger.error(f"burn_drawtext_final failed: {e}")
        return False


def build_segment(
    input_path: str,
    out_path: str,
    profile,
    duration: float,
    effect: Optional[str] = None,
    color_grade: Optional[str] = None,
    motion: Optional[str] = None,
    overlay_text: Optional[str] = None,
) -> bool:
    try:
        if not input_path or not os.path.exists(input_path):
            logger.error(f"build_segment: input missing {input_path}")
            return False
        is_image = _is_image(input_path)
        vf, textfile = _build_vf(profile, is_image, effect, color_grade, motion, overlay_text, duration)

        def _run(vf_arg: Optional[str]) -> bool:
            cmd = ["ffmpeg", "-y", "-threads", "1", "-preset", "ultrafast"]
            if is_image:
                cmd += ["-loop", "1"]
            else:
                cmd += ["-stream_loop", "-1"]
            cmd += ["-i", input_path]
            cmd += ["-t", str(duration)]
            if vf_arg:
                cmd += ["-vf", vf_arg]
            cmd += [
                "-c:v", profile.codec, "-pix_fmt", "yuv420p",
                "-r", str(profile.fps), "-t", str(duration),
                "-an", out_path,
            ]
            res = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
            if res.returncode != 0 or not (os.path.exists(out_path) and os.path.getsize(out_path) > 0):
                # Surface the failure so a broken filter/codec is diagnosable from
                # the logs instead of silently producing a 0-byte render.
                tail = (res.stderr or "")[-400:].replace("\n", " ")
                logger.warning(
                    f"build_segment ffmpeg rc={res.returncode} vf={vf_arg!r}: {tail}"
                )
                return False
            return True

        ok = _run(vf)
        if not ok and vf:
            base = vf.split(",")[0]
            ok = _run(base)
        if not ok and vf:
            ok = _run(None)
        if not ok:
            logger.error(f"build_segment gave no usable output for {input_path}")
        return ok
    except Exception as e:
        logger.error(f"build_segment failed: {e}")
        return False


def concatenate_with_transitions(
    segments: List[str],
    profile,
    transitions: List[str],
    out_path: str,
    audio_segments: Optional[List[str]] = None,
) -> bool:
    try:
        segments = [s for s in (segments or []) if s and os.path.exists(s)]
        if not segments:
            logger.error("concatenate: no segments")
            return False

        if len(transitions or []) != len(segments) - 1:
            transitions = (transitions or []) + ["fade"] * (len(segments) - 1 - len(transitions or []))

        if len(segments) == 1:
            cmd = [
                "ffmpeg", "-y", "-threads", "1", "-preset", "ultrafast", "-i", segments[0],
                "-map", "0", "-c:v", profile.codec, "-pix_fmt", "yuv420p",
                "-r", str(profile.fps), "-b:v", profile.bitrate,
                "-an", out_path,
            ]
            res = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
            return res.returncode == 0 and os.path.exists(out_path)

        # Free-tier OOM guard: xfade's filter_complex decodes EVERY segment into
        # RAM at once. At 720p that is several hundred MB and on Render's 512MB
        # free tier it exhausts memory and the OOM-killer restarts the whole
        # service. When memory is tight we skip xfade and stream-copy the segments
        # (hard cuts) — still a valid video, just less fancy, and safe to render.
        try:
            import psutil  # type: ignore
            avail_mb = psutil.virtual_memory().available / (1024 * 1024)
        except Exception:
            avail_mb = 2048.0
        low_memory = avail_mb < 1200

        if not low_memory:
            durations = [_probe_duration(s) or 5.0 for s in segments]
            total = sum(durations)
            filter_parts: List[str] = []
            prev = "[0:v]"
            for j in range(1, len(segments)):
                t = _xfade_type(transitions[j - 1])
                d = _xfade_dur(transitions[j - 1])
                offset = max(0.0, sum(durations[:j]) - d)
                out_label = f"[v{j}]"
                filter_parts.append(
                    f"{prev}[{j}:v]xfade=transition={t}:duration={d}:"
                    f"offset={offset:.3f}{out_label}"
                )
                prev = out_label
            last = f"[v{len(segments) - 1}]"

            cmd = ["ffmpeg", "-y", "-threads", "1", "-preset", "ultrafast"]
            for s in segments:
                cmd += ["-i", s]
            cmd += [
                "-filter_complex", ";".join(filter_parts),
                "-map", last, "-an",
                "-c:v", profile.codec, "-pix_fmt", "yuv420p",
                "-r", str(profile.fps), "-b:v", profile.bitrate,
                "-t", str(total), out_path,
            ]
            res = subprocess.run(cmd, capture_output=True, text=True, timeout=900)
            if res.returncode == 0 and os.path.exists(out_path):
                return True
            tail = (res.stderr or "")[-300:].replace("\n", " ")
            logger.warning(f"xfade concat failed (rc={res.returncode}): {tail}; "
                           f"falling back to concat demuxer")

        # Concat demuxer (stream copy): minimal RAM, always works when segment
        # codecs/params match (they do — all built with the same profile).
        list_path = out_path + ".concat.txt"
        with open(list_path, "w", encoding="utf-8") as f:
            for s in segments:
                f.write(f"file '{os.path.abspath(s)}'\n")
        fb = [
            "ffmpeg", "-y", "-threads", "1", "-preset", "ultrafast", "-f", "concat", "-safe", "0", "-i", list_path,
            "-c:v", profile.codec, "-pix_fmt", "yuv420p", "-an", out_path,
        ]
        res2 = subprocess.run(fb, capture_output=True, text=True, timeout=900)
        return res2.returncode == 0 and os.path.exists(out_path)
    except Exception as e:
        logger.error(f"concatenate_with_transitions failed: {e}")
        return False


def mix_audio(
    video_segments_audio: Optional[List[str]],
    narration_path: Optional[str],
    music_path: Optional[str],
    sfx_paths: Optional[List[str]],
    out_audio: str,
    target_duration: Optional[float] = None,
    ambient_path: Optional[str] = None,
) -> bool:
    try:
        inputs: List[str] = []
        parts: List[str] = []
        amix_labels: List[str] = []
        idx = 0
        total_dur = 0.0

        for p in (video_segments_audio or []):
            if p and os.path.exists(p):
                total_dur += _probe_duration(p)

        def _add(path, filters):
            nonlocal idx
            inputs.extend(["-i", path])
            label = f"[{idx}:a]"
            parts.append(f"{label}{filters}[a{idx}]")
            amix_labels.append(f"[a{idx}]")
            idx += 1

        if narration_path and os.path.exists(narration_path):
            _add(narration_path, "aresample=44100")
        if music_path and os.path.exists(music_path):
            _add(music_path, "volume=0.2,aresample=44100")
        if ambient_path and os.path.exists(ambient_path):
            # J1: ambient bed sits under everything at a low, non-competing gain.
            _add(ambient_path, "volume=0.15,aresample=44100")
        for s in (sfx_paths or []):
            if s and os.path.exists(s):
                _add(s, "volume=0.4,aresample=44100")

        # Pad audio to the (already length-correct) video track so the final
        # mux can't collapse to the shorter narration length.
        pad_dur = target_duration or total_dur or 5.0

        if not amix_labels:
            parts.append(
                f"anullsrc=d={pad_dur:.2f}:r=44100:cl=stereo,"
                "aresample=44100[out]"
            )
        else:
            n = len(amix_labels)
            amix = "".join(amix_labels) + f"amix=inputs={n}:duration=longest:normalize=0[pre]"
            parts.append(amix)
            parts.append(f"[pre]apad,aresample=44100,loudnorm=I=-18:TP=-1.5:LRA=11,atrim=0:{pad_dur:.2f}[out]")

        filter_complex = ";".join(parts)
        cmd = ["ffmpeg", "-y", "-threads", "1", "-preset", "ultrafast"] + inputs + [
            "-filter_complex", filter_complex,
            "-map", "[out]", "-c:a", "aac", "-b:a", "192k",
            "-t", f"{pad_dur:.2f}", out_audio,
        ]
        res = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
        return res.returncode == 0 and os.path.exists(out_audio)
    except Exception as e:
        logger.error(f"mix_audio failed: {e}")
        return False
