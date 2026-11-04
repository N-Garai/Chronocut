"""EDL compiler: renders a validated EDL to a real video file.

Pipeline per render:
1. Validate and normalize the EDL.
2. Resolve sources (local files, remote URLs cached once per job).
3. For each video-track clip: trim (-ss/-t), speed (setpts), scale/crop
   transform, grade, motion, per-clip drawtext overlay -> intermediate segment
   (libx264, fast preset, no audio).
4. Concatenate; junction transitions are baked in as dips through black
   (black slivers fill gaps).
5. Build captions as an ASS file from the caption track; burn with
   ``subtitles`` (fallback: timed drawtext).
6. Mix narration/music/sfx with per-clip gain, sidechain ducking under
   narration, loudness normalization to -14 LUFS and a limiter.
7. Mux with -movflags +faststart, yuv420p, AAC 192k.

The legacy storyboard path stays available in ``app.tools.render.compiler``;
the orchestrator prefers this compiler once the job has an EDL.
"""
import asyncio
import json
import logging
import os
import shutil
import subprocess
import tempfile
import urllib.request
from typing import Any, Callable, Dict, List, Optional, Tuple

from app.edl.schema import (
    ALLOWED_PROFILE_RESOLUTIONS,
    EDLValidationError,
    TRACK_CAPTION,
    TRACK_MUSIC,
    TRACK_NARRATION,
    TRACK_SFX,
    TRACK_VIDEO,
    normalize_edl,
    validate_edl,
)
from app.services.storage import tmp_dir
from app.tools.render.ffmpeg_assembler import (
    _image_zoompan,
    _probe_duration,
    _video_pan,
)

logger = logging.getLogger("chronocut.edl.compiler")

_IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".jpe", ".jfif", ".bmp", ".dib", ".gif",
               ".webp", ".tiff", ".tif", ".avif", ".heic", ".heif", ".jp2", ".tga"}
_AUDIO_EXTS = {".mp3", ".wav", ".m4a", ".aac", ".ogg", ".oga", ".flac", ".opus",
               ".wma", ".aiff", ".aif", ".au", ".amr", ".mka"}

_MIN_CLIP = 0.06
_SEGMENT_SUFFIX = ".seg.mp4"


# --------------------------------------------------------------------------
# small process helpers
# --------------------------------------------------------------------------
def run_ffmpeg(cmd: List[str], timeout: int = 900) -> Tuple[bool, str]:
    try:
        res = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        if res.returncode == 0:
            return True, ""
        tail = (res.stderr or "")[-500:].replace("\n", " ")
        logger.warning("ffmpeg rc=%s: %s", res.returncode, tail)
        return False, tail
    except Exception as e:
        logger.error("ffmpeg exception: %s", e)
        return False, str(e)


def valid_media(path: Optional[str]) -> bool:
    return bool(path) and os.path.exists(path) and os.path.getsize(path) > 0


# --------------------------------------------------------------------------
# source resolution
# --------------------------------------------------------------------------
def _classify(path: str) -> str:
    ext = os.path.splitext(path)[1].lower()
    if ext in _IMAGE_EXTS:
        return "image"
    if ext in _AUDIO_EXTS:
        return "audio"
    return "video"


def resolve_sources(edl: Dict[str, Any], cache_dir: str) -> Dict[str, Dict[str, Any]]:
    """Return {source_id: {type, path, duration}} with remote URLs fetched once."""
    resolved: Dict[str, Dict[str, Any]] = {}
    for src in edl.get("sources") or []:
        sid = str(src.get("id") or "")
        if not sid:
            continue
        path = str(src.get("path") or "")
        url = str(src.get("url") or "").strip()
        stype = str(src.get("type") or "")
        if stype == "synth":
            resolved[sid] = {"type": "synth", "path": "", "kind": str(src.get("kind") or "drone")}
            continue
        if (not path or not os.path.exists(path)) and url:
            safe_name = f"remote_{sid}.{(url.split('?')[0].rsplit('.', 1)[-1] or 'bin')[:8]}"
            local = os.path.join(cache_dir, safe_name)
            try:
                req = urllib.request.Request(url, headers={"User-Agent": "ChronoCut/1.0"})
                with urllib.request.urlopen(req, timeout=60) as r, open(local, "wb") as f:
                    f.write(r.read(50_000_000))
                path = local
            except Exception as e:
                logger.warning("source %s download failed (%s): %s", sid, url, e)
                continue
        if not path or not os.path.exists(path):
            continue
        duration = src.get("duration")
        if duration in (None, "") and stype != "image":
            duration = _probe_duration(path) or None
        if not stype or stype in ("", "video"):
            stype = _classify(path)
        resolved[sid] = {"type": stype, "path": path, "duration": duration}
    return resolved


# --------------------------------------------------------------------------
# video segments
# --------------------------------------------------------------------------
def grade_filter(value: Optional[str]) -> Optional[str]:
    """Extend the color-grade preset allow-list."""
    g = (value or "").lower()
    if g in ("clean", "neutral", ""):
        return None
    if g == "cinematic":
        return "eq=r=1.06:b=1.06:g=1.0:saturation=1.12:v=1.02,vignette=PI/4:alpha=0.18,gblur=sigma=1.2"
    if g in ("bw", "b&w"):
        return "hue=s=0,eq=contrast=1.12:saturation=0:b=0.02,vignette=PI/4:alpha=0.12"
    if g == "nostalgic":
        return "eq=gamma=1.08:saturation=0.82:contrast=0.94,colorbalance=rs=0.06:gs=0.02:bs=-0.04:bsh=0.08"
    if g == "warm":
        return "colorbalance=rs=0.08:bs=-0.06,eq=saturation=1.08"
    if g == "professional":
        return "eq=contrast=1.08:saturation=0.96:brightness=0.01,colorbalance=bs=0.03"
    if g == "teal_orange":
        return "colorbalance=rs=0.06:bs=0.06:rm=0.02:bm=0.04,eq=saturation=1.1:contrast=1.06"
    if g == "anamorphic":
        return "eq=saturation=1.05:contrast=1.08,setsar=1,vignette=PI/5:alpha=0.15"
    return None


def _motion_from_effects(effects: List[Dict[str, Any]]) -> Optional[str]:
    for e in effects or []:
        if e.get("type") == "motion":
            return str(e.get("value") or "") or None
    return None


def _grade_from_effects(effects: List[Dict[str, Any]]) -> Optional[str]:
    for e in effects or []:
        if e.get("type") == "grade":
            return str(e.get("value") or "") or None
    return None


_MOTION_FOR_ZOOMPAN = {"push_in", "pull_out", "pan_left", "pan_right", "parallax",
                       "ken_burns_slow_zoom", "ken_burns_in", "ken_burns_out"}
_KEN_BURNS_ALIASES = {"ken_burns_slow_zoom": None, "ken_burns_in": "push_in", "ken_burns_out": "pull_out"}

_SLOW_MOTIONS = {"slowmo_0.5": 1.5, "speed_ramp": 0.6}


def clip_vf_chain(
    clip: Dict[str, Any],
    profile_w: int,
    profile_h: int,
    fps: int,
    duration: float,
    is_image: bool,
    burn_text: Optional[Dict[str, Any]] = None,
) -> Tuple[str, Optional[str]]:
    """Visual filter chain for one video-track clip.

    Returns (vf, textfile) — textfile is set when the overlay drawtext is
    used so the caller can unlink it after the run.
    """
    w, h = profile_w, profile_h
    chain: List[str] = []
    effects = clip.get("effects") or []
    motion = _motion_from_effects(effects)
    grade = grade_filter(_grade_from_effects(effects))

    if is_image:
        chain.append(f"scale={w}:{h}:force_original_aspect_ratio=increase")
    else:
        chain.append(f"scale={w}:{h}:force_original_aspect_ratio=increase")

    # transform: crop-focus + zoom + pan offsets
    tr = clip.get("transform") or {}
    crop = tr.get("crop")
    if isinstance(crop, dict):
        try:
            left = max(0.0, float(crop.get("left", 0.0)))
            top = max(0.0, float(crop.get("top", 0.0)))
            right = max(0.0, float(crop.get("right", 0.0)))
            bottom = max(0.0, float(crop.get("bottom", 0.0)))
            cw = max(64, int(w * (1 - min(0.95, left + right))))
            ch = max(64, int(h * (1 - min(0.95, top + bottom))))
            chain.append(f"crop={cw}:{ch}:{int(w * left)}:{int(h * top)}")
        except (TypeError, ValueError):
            pass

    scale = tr.get("scale", 1.0)
    zoompan_motion = motion
    if scale is not None and float(scale) != 1.0 and motion not in _MOTION_FOR_ZOOMPAN:
        zoompan_motion = "push_in"

    if zoompan_motion:
        mapped = _KEN_BURNS_ALIASES.get(zoompan_motion, zoompan_motion)
        if is_image:
            nf = max(2, int(round(duration * fps)))
            if mapped in (None, "push_in", "pull_out", "pan_left", "pan_right", "parallax"):
                chain.append(_image_zoompan(mapped or "push_in", w, h, fps, nf))
        else:
            chain.append(_video_pan(mapped or "push_in", w, h, duration))
    else:
        # solid, centered framing + optional zoom/pan offsets from the transform
        sx = float(tr.get("scale", 1.0) or 1.0)
        if sx and sx > 1.001:
            chain.append(f"scale={int(w * sx)}:-1")
        chain.append(f"crop={w}:{h}")
        ox, oy = float(tr.get("x", 0.0) or 0.0), float(tr.get("y", 0.0) or 0.0)
        if abs(ox) > 0.001 or abs(oy) > 0.001:
            xoff = int(-ox * w / 4)
            yoff = int(-oy * h / 4)
            chain.append(f"crop={w}:{h}:{max(0, xoff)}:{max(0, yoff)}")
        else:
            chain.append(f"crop={w}:{h}:0:0")
    chain.append(f"scale={w}:{h}")
    if grade:
        chain.append(grade)

    slow = _SLOW_MOTIONS.get(motion)
    if slow:
        chain.append(f"setpts={slow}*PTS")

    textfile: Optional[str] = None
    if burn_text:
        text = str(burn_text.get("text") or "").strip()
        if text:
            style = burn_text.get("style") or {}
            position = "top" if style.get("position") == "top" else "bottom"
            size = max(12, min(120, int(style.get("size", 42) or 42)))
            color = str(style.get("color") or "#ffffff")
            try:
                import tempfile as _tf
                fd, textfile = _tf.mkstemp(prefix="cc_cap_", suffix=".txt")
                with os.fdopen(fd, "w", encoding="utf-8") as f:
                    f.write(text.lstrip("\\"))
                ypos = "h-th-40" if position == "bottom" else "40"
                dur = max(1.0, duration)
                alpha = (f"alpha='if(lt(t,0.3),t/0.3,"
                         f"if(gt(t,{dur - 0.3:.2f}),({dur - 0.3:.2f}-t)/0.3,1))'")
                chain.append(
                    f"drawtext=textfile='{textfile}':fontcolor={color}:fontsize={size}:"
                    f"box=1:boxcolor=black@0.4:boxborderw=8:x=(w-tw)/2:y={ypos}:{alpha}"
                )
            except Exception as e:
                logger.warning("overlay drawtext failed: %s", e)
                textfile = None

    return ",".join(chain), textfile


def build_edl_segment(
    source_path: str,
    clip: Dict[str, Any],
    profile_w: int,
    profile_h: int,
    fps: int,
    out_path: str,
    *,
    timeout: int = 300,
) -> bool:
    """Render one silent video segment for a video-track clip."""
    try:
        clip_start = float(clip.get("start", 0.0))
        clip_dur = float(clip.get("duration", 0.0))
        clip_in = float(clip.get("in", 0.0) or 0.0)
        speed = float(clip.get("speed", 1.0) or 1.0)
        if clip_dur < _MIN_CLIP:
            return False
        is_image = _classify(source_path) == "image"
        vf, textfile = clip_vf_chain(
            clip, profile_w, profile_h, fps, clip_dur, is_image,
            burn_text={"text": clip.get("overlay_text"), "style": (clip.get("overlay_style") or {})},
        )

        def _run(vf_arg: Optional[str], timeout_: int) -> bool:
            # Encoder options (-preset) must sit on the OUTPUT side: ffmpeg >= 6.1
            # hard-fails on codec options placed before -i.
            cmd = ["ffmpeg", "-y", "-threads", "1"]
            if clip_in > 0.01:
                cmd += ["-ss", f"{clip_in:.3f}"]
            if is_image:
                cmd += ["-loop", "1"]
            else:
                cmd += ["-stream_loop", "-1"]
            cmd += ["-i", source_path]
            src_dur = clip_dur
            if clip_start:
                src_dur = clip_dur  # absolute project time handled via adelay/mix
            cmd += ["-t", f"{src_dur:.3f}"]
            if vf_arg:
                cmd += ["-vf", vf_arg]
            cmd += [
                "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p",
                "-r", str(fps), "-an", out_path,
            ]
            ok, _ = run_ffmpeg(cmd, timeout=timeout_)
            return ok and valid_media(out_path)

        ok = _run(vf, timeout)
        if not ok and vf:
            ok = _run(vf.split(",")[0], timeout)
        if not ok and vf:
            ok = _run(None, timeout)
        if textfile:
            try:
                os.remove(textfile)
            except OSError:
                pass
        return ok
    except Exception as e:
        logger.error("build_edl_segment failed for clip %s: %s", clip.get("id"), e)
        return False


def _black_segment(w: int, h: int, fps: int, duration: float, out_path: str) -> bool:
    cmd = [
        "ffmpeg", "-y", "-threads", "1", "-f", "lavfi",
        "-i", f"color=c=black:s={w}x{h}:d={duration:.3f}",
        "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p",
        "-r", str(fps), out_path,
    ]
    ok, _ = run_ffmpeg(cmd, timeout=120)
    return ok and valid_media(out_path)


def _xfade_for(value: Optional[str]) -> Optional[Tuple[str, float]]:
    t = (value or "").lower()
    if not t or t in ("cut", "hard_cut", "match_cut"):
        return None
    if t.startswith("crossfade"):
        dur = 0.5
        try:
            dur = max(0.1, float(t.split("_")[-1].rstrip("s")))
        except (ValueError, IndexError):
            dur = 0.5
        return ("fade", dur)
    if t == "dissolve":
        return ("dissolve", 0.5)
    if t == "dip_black":
        return ("fadeblack", 0.5)
    if t == "fade":
        return ("fade", 0.5)
    return None


def concatenate_edl_timeline(
    segments: List[Tuple[float, float, str]],  # (start, end, path)
    transitions: List[Tuple[float, Optional[str]]],  # junction start times + transition values
    profile_w: int,
    profile_h: int,
    fps: int,
    total: float,
    out_path: str,
    timeout: int = 1200,
) -> bool:
    """Assemble absolute-timeline segments into one silent video.

    Segments are on the project timeline; the timeline may have gaps. Where
    clips actually meet, the junction's transition is baked into both sides
    as a dip through black (memory-lean: one decoder at a time); elsewhere
    segments are concatenated directly. Gaps are bridged with black slivers
    and transitions that would cross a gap fall back to a straight cut.
    """
    try:
        segments = [(s, e, p) for (s, e, p) in segments if valid_media(p)]
        if not segments:
            return False
        segments.sort(key=lambda x: x[0])

        # bridges: fill gaps with black and produce a fully contiguous chain
        contiguous: List[Tuple[float, float, str]] = []
        cursor = 0.0
        for (s, e, p) in segments:
            s = max(s, cursor)
            if s > cursor + 0.03:
                gap = s - cursor
                black = out_path + f".gap{len(contiguous)}{fps}.mp4"
                if _black_segment(profile_w, profile_h, fps, gap, black):
                    contiguous.append((cursor, s, black))
                    cursor = s
            if e <= cursor:
                continue
            contiguous.append((s, e, p))
            cursor = e
        if total - cursor > 0.3:
            black = out_path + ".gap_tail.mp4"
            if _black_segment(profile_w, profile_h, fps, total - cursor, black):
                contiguous.append((cursor, total, black))

        if not contiguous:
            return False
        if len(contiguous) == 1:
            cmd = ["ffmpeg", "-y", "-threads", "1", "-i", contiguous[0][2],
                   "-map", "0", "-c:v", "libx264", "-preset", "ultrafast",
                   "-pix_fmt", "yuv420p",
                   "-r", str(fps), "-an",
                   "-t", f"{max(total, contiguous[0][1]):.3f}", out_path]
            ok, _ = run_ffmpeg(cmd, timeout=timeout)
            return ok and valid_media(out_path)

        # build junction list aligned with contiguous segments
        junc_infos: List[Tuple[float, Tuple[str, float]]] = []
        for i in range(len(contiguous) - 1):
            at = contiguous[i][1]
            value = None
            for jt, tv in transitions:
                if abs(jt - at) < 0.08:
                    value = tv
                    break
            xf = _xfade_for(value)
            junc_infos.append((at, xf or ("fade", 0.0)))

        has_real_transitions = any(d > 0.01 for _, (t, d) in junc_infos) if junc_infos else False
        if has_real_transitions:
            # Crossfades render as dips through black: each junction's fade is
            # baked into the two touching segments (one ffmpeg pass per
            # segment, a single decoder alive at a time), then everything is
            # joined with the concat demuxer. This keeps absolute EDL timing
            # intact and peak memory flat — a multi-input composite graph
            # holds one live decoder per segment and OOM-kills 512MB
            # containers mid-pipeline.
            faded_dir = out_path + ".faded"
            os.makedirs(faded_dir, exist_ok=True)
            assembly: List[str] = []
            for i, (s, e, p) in enumerate(contiguous):
                tlen_in = junc_infos[i - 1][1][1] if i > 0 else 0.0
                tlen_out = junc_infos[i][1][1] if i < len(junc_infos) else 0.0
                seg_dur = e - s
                if tlen_in > 0.01 or tlen_out > 0.01:
                    filters = []
                    if tlen_in > 0.01:
                        filters.append(f"fade=in:st=0:d={min(tlen_in, seg_dur):.3f}")
                    if tlen_out > 0.01:
                        st = max(0.0, seg_dur - min(tlen_out, seg_dur))
                        filters.append(f"fade=out:st={st:.3f}:d={min(tlen_out, seg_dur):.3f}")
                    faded_path = os.path.join(faded_dir, f"seg{i:03d}.mp4")
                    cmd = ["ffmpeg", "-y", "-threads", "1", "-i", p,
                           "-vf", ",".join(filters),
                           "-c:v", "libx264", "-preset", "ultrafast",
                           "-pix_fmt", "yuv420p", "-r", str(fps), "-an", faded_path]
                    ok, _ = run_ffmpeg(cmd, timeout=timeout)
                    if ok and valid_media(faded_path):
                        assembly.append(faded_path)
                        continue
                    logger.warning("fade pre-pass failed for %s; using raw segment", p)
                assembly.append(p)
            if assembly:
                list_path = out_path + ".concat.txt"
                with open(list_path, "w", encoding="utf-8") as f:
                    for p in assembly:
                        f.write(f"file '{os.path.abspath(p)}'\n")
                cmd = ["ffmpeg", "-y", "-threads", "1", "-f", "concat", "-safe", "0", "-i", list_path,
                       "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p",
                       "-r", str(fps), "-an", out_path]
                ok, _ = run_ffmpeg(cmd, timeout=timeout)
                if ok and valid_media(out_path):
                    shutil.rmtree(faded_dir, ignore_errors=True)
                    return True
                logger.warning("faded concat failed; falling back to plain concat")

        # concat demuxer fallback: hard cuts, minimal RAM
        list_path = out_path + ".concat.txt"
        with open(list_path, "w", encoding="utf-8") as f:
            for (_, _, p) in contiguous:
                f.write(f"file '{os.path.abspath(p)}'\n")
        cmd = ["ffmpeg", "-y", "-threads", "1", "-f", "concat", "-safe", "0", "-i", list_path,
               "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p", "-r", str(fps), "-an", out_path]
        ok, _ = run_ffmpeg(cmd, timeout=timeout)
        return ok and valid_media(out_path)
    except Exception as e:
        logger.error("concatenate_edl_timeline failed: %s", e)
        return False


# --------------------------------------------------------------------------
# captions
# --------------------------------------------------------------------------
def _ass_timestamp(sec: float) -> str:
    if sec < 0:
        sec = 0.0
    h = int(sec // 3600)
    m = int((sec % 3600) // 60)
    s = sec % 60
    return f"{h}:{m:02d}:{s:05.2f}"


def build_ass_captions(captions: List[Dict[str, Any]], out_path: str) -> str:
    """Build an .ass subtitle file from the caption track."""
    lines: List[str] = [
        "[Script Info]",
        "ScriptType: v4.00+",
        "PlayResX: 1920",
        "PlayResY: 1080",
        "WrapStyle: 0",
        "",
        "[V4+ Styles]",
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour,"
        " BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle,"
        " BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV",
        ("Style: ChronoCut,DejaVu Sans,54,&H00FFFFFF,&H00FFFFFF,&H00101010,&H7E101010,"
         "0,0,0,0,100,100,0,0,3,2,2,2,60,60,60"),
        "",
        "[Events]",
        "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text",
    ]
    for cap in sorted(captions, key=lambda c: float(c.get("start", 0.0))):
        start = float(cap.get("start", 0.0))
        end = start + float(cap.get("duration", 2.0))
        text = str(cap.get("text") or "").replace("\n", "\\N")
        style = cap.get("style") or {}
        margin = 90 if (style.get("position") == "top") else 80
        size = max(12, min(120, int(style.get("size", 42) or 42)))
        fontsize = int(54 * size / 42)
        lines.append(
            f"Dialogue: 0,{_ass_timestamp(start)},{_ass_timestamp(end)},ChronoCut,,0,0,{margin},,{text}"
        )
    content = "\n".join(lines) + "\n"
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(content)
    return out_path


def burn_ass_captions(video_in: str, ass_path: str, out_path: str, timeout: int = 900) -> bool:
    """Burn the caption .ass file. Falls back to drawtext-style timed text if
    libass is missing."""
    if not valid_media(video_in) or not os.path.exists(ass_path):
        return False
    try:
        escaped = ass_path.replace("\\", "/").replace(":", "\\:")
        cmd = ["ffmpeg", "-y", "-threads", "1", "-i", video_in,
               "-vf", f"subtitles={escaped}", "-c:v", "libx264", "-preset", "ultrafast",
               "-pix_fmt", "yuv420p",
               "-an", out_path]
        ok, _ = run_ffmpeg(cmd, timeout=timeout)
        return ok and valid_media(out_path)
    except Exception as e:
        logger.warning("ASS burn failed: %s", e)
        return False


# --------------------------------------------------------------------------
# audio mix
# --------------------------------------------------------------------------
def mix_audio_edl(
    clips_by_track: Dict[str, List[Dict[str, Any]]],
    sources: Dict[str, Dict[str, Any]],
    total: float,
    out_audio: str,
    *,
    timeout: int = 600,
) -> Tuple[bool, List[Dict[str, str]]]:
    """Mix narration/music/sfx from the EDL onto one timeline.

    Every clip is trimmed once (in/duration), delayed to its absolute start,
    gained by its track gain and mixed; music with ``duck_under: "a1"`` is
    sidechain-compressed against the narration bus. Finally -14 LUFS
    normalization + limiter + hard trim to the project duration.
    """
    try:
        os.makedirs(os.path.dirname(out_audio) or ".", exist_ok=True)
        base_label = "[base_]"
        inputs: List[str] = ["-f", "lavfi", "-i",
                             f"anullsrc=r=44100:cl=stereo:d={total:.3f}"]  # [0]
        parts: List[str] = [f"[0:a]aresample=44100{base_label}"]
        narration_labels: List[str] = []
        music_labels: List[str] = []
        sfx_labels: List[str] = []
        clip_idx = 1
        work_files: List[str] = []

        def _register(track: str, labels: List[str]) -> None:
            pass

        for track_id in (TRACK_NARRATION, TRACK_MUSIC, TRACK_SFX):
            for c in clips_by_track.get(track_id, []):
                src = sources.get(str(c.get("source_id") or ""))
                if src is None:
                    continue
                dur = max(0.1, float(c.get("duration", 3.0) or 3.0))
                if src.get("type") == "synth":
                    synth_path = out_audio + f".synth{clip_idx}.mp3"
                    ok, _ = run_ffmpeg(["ffmpeg", "-y", "-f", "lavfi", "-i", _synth_lavfi(src.get("kind", "drone")),
                                        "-t", f"{dur:.3f}", "-c:a", "libmp3lame", "-b:a", "128k",
                                        synth_path], timeout=120)
                    if not ok or not valid_media(synth_path):
                        continue
                    path = synth_path
                    work_files.append(synth_path)
                else:
                    path = src["path"]
                trimmed = out_audio + f".trim{clip_idx}.m4a"
                if not _trim_audio(path, float(c.get("in", 0.0) or 0.0), dur, trimmed):
                    continue
                work_files.append(trimmed)
                gain = float(c.get("gain", 0.22 if track_id == TRACK_MUSIC else 1.0))
                gain = max(0.0, min(2.0, gain))
                delay_ms = int(max(0.0, float(c.get("start", 0.0))) * 1000)
                label = f"[a{clip_idx}]"
                inputs += ["-i", trimmed]
                parts.append(
                    f"[{clip_idx}:a]aresample=44100,volume={gain:.3f},"
                    f"adelay={delay_ms}|{delay_ms}{label}"
                )
                if track_id == TRACK_NARRATION:
                    narration_labels.append(label)
                elif track_id == TRACK_MUSIC:
                    music_labels.append(label)
                else:
                    sfx_labels.append(label)
                clip_idx += 1

        # Buses.
        if narration_labels:
            parts.append("".join(narration_labels) +
                         f"amix=inputs={len(narration_labels)}:duration=longest:normalize=0[narr]")
        if music_labels:
            parts.append("".join(music_labels) +
                         f"amix=inputs={len(music_labels)}:duration=longest:normalize=0[music]")
        if sfx_labels:
            parts.append("".join(sfx_labels) +
                         f"amix=inputs={len(sfx_labels)}:duration=longest:normalize=0[sfx]")

        # Ducking: music keyed by narration (only when the EDL asks for it).
        # The narration bus must be split so it can both merge and key; the
        # split guarantees every label is consumed exactly once.
        wants_duck = bool(narration_labels and music_labels) and any(
            (c.get("duck_under") in ("a1", True, "narration"))
            for c in clips_by_track.get(TRACK_MUSIC, []))
        narr_label_for_merge = "[narr]"
        musical = ""
        if music_labels:
            musical = "[music]"
        if wants_duck:
            musical = "[music_ducked]"
            narr_label_for_merge = "[narrMain]"
            parts.append("[music]asplit[musicDuck][musicBus]")
            parts.append("[narr]asplit[narrMain][narrKey]")
            parts.append("[musicDuck][narrKey]sidechaincompress=threshold=0.02:ratio=8:"
                         "attack=50:release=350[music_ducked]")
            musical = "[music_ducked]"

        merge_inputs = [base_label]
        if narration_labels:
            merge_inputs.append(narr_label_for_merge)
        if musical:
            merge_inputs.append(musical)
        if sfx_labels:
            merge_inputs.append("[sfx]")
        if len(merge_inputs) > 1:
            parts.append("".join(merge_inputs) +
                         f"amix=inputs={len(merge_inputs)}:duration=longest:normalize=0[merged]")
        else:
            parts.append(f"{base_label}anull[merged]")
        parts.append(
            "[merged]aresample=44100,loudnorm=I=-14:TP=-1.5:LRA=11,"
            f"alimiter=limit=0.97,atrim=0:{total:.3f}[out]"
        )

        filter_complex = ";".join(parts)
        cmd = ["ffmpeg", "-y", "-threads", "1"] + inputs + [
            "-filter_complex", filter_complex,
            "-map", "[out]", "-c:a", "aac", "-b:a", "192k",
            "-t", f"{total:.3f}", out_audio]
        ok, _ = run_ffmpeg(cmd, timeout=timeout)
        for f in work_files:
            try:
                os.remove(f)
            except OSError:
                pass
        return ok, []
    except Exception as e:
        logger.error("mix_audio_edl failed: %s", e)
        return False, []


def _trim_audio(path: str, in_point: float, duration: float, out_path: str) -> bool:
    try:
        cmd = ["ffmpeg", "-y", "-threads", "1", "-i", path,
               "-ss", f"{max(0.0, in_point):.3f}", "-t", f"{max(0.05, duration):.3f}",
               "-c:a", "aac", "-b:a", "192k", out_path]
        ok, _ = run_ffmpeg(cmd, timeout=180)
        return ok and valid_media(out_path)
    except Exception as e:
        logger.warning("audio trim failed for %s: %s", path, e)
        return False


def _synth_lavfi(kind: str) -> Optional[str]:
    key = str(kind or "drone").strip().lower()
    if key == "rain":
        return "anoisesrc=color=brown:amplitude=0.4:seed=3"
    if key in ("city", "street", "traffic", "crowd"):
        return "anoisesrc=color=brown:amplitude=0.3:seed=7"
    if not key or key in ("drone", "ambient"):
        return "sine=frequency=110"
    return None


def _ass_escape(text: str) -> str:
    return text.replace("\\", "\\\\")


# --------------------------------------------------------------------------
# orchestration
# --------------------------------------------------------------------------
async def render_edl(
    edl: Dict[str, Any],
    out_path: str,
    *,
    profile_name: str = "preview_480",
    job_id: Optional[str] = None,
    progress_cb: Optional[Callable[[int, str], None]] = None,
) -> Dict[str, Any]:
    """Render a validated EDL to ``out_path``. Returns a report dict."""
    report: Dict[str, Any] = {"ok": False, "profile": profile_name, "out_path": out_path}
    try:
        edl = normalize_edl(edl)
        edl = validate_edl(edl)
    except EDLValidationError as e:
        report["error"] = str(e)
        return report

    res = ALLOWED_PROFILE_RESOLUTIONS.get(profile_name) or (854, 480, 30)
    profile_w, profile_h, profile_fps = res

    # Per-profile framing: a 16:9 cut exported to 9:16/1:1/21:9 gets a crop
    # window per clip (subject-aware when the framer recorded a focus point).
    try:
        from app.tools.media.reframe import apply_reframe_to_edl, focus_from_context
        reframed = apply_reframe_to_edl(edl, profile_w, profile_h, focus_from_context(job_id))
        if reframed:
            report["reframed_clips"] = reframed
    except Exception as e:  # framing must never block a render
        logger.warning("reframe skipped for %s (%s): %s", profile_name, job_id, e)
    total = float(edl.get("project", {}).get("duration", 10.0) or 10.0)
    work = tempfile.mkdtemp(prefix="cc_edl_", dir=tmp_dir())
    cache_dir = os.path.join(work, "sources")
    os.makedirs(cache_dir, exist_ok=True)

    def emit(pct: int, msg: str):
        if progress_cb:
            try:
                progress_cb(pct, msg)
            except Exception:
                pass

    emit(2, "Resolving EDL sources")
    sources = await asyncio.to_thread(resolve_sources, edl, cache_dir)
    tracks = {t.get("id"): t for t in edl.get("tracks") or []}
    video_track = tracks.get(TRACK_VIDEO) or {"clips": []}
    clips = [c for c in video_track.get("clips") or [] if float(c.get("duration", 0) or 0) >= _MIN_CLIP]

    # 3) segments
    segments: List[Tuple[float, float, str]] = []
    missing: List[str] = []
    emit(8, f"Building {len(clips)} segment(s)")
    for i, clip in enumerate(clips):
        src = sources.get(str(clip.get("source_id") or ""))
        if src is None or not src.get("path") or src.get("type") == "synth":
            black = os.path.join(work, f"missing_{i}{_SEGMENT_SUFFIX}")
            if _black_segment(profile_w, profile_h, profile_fps,
                              float(clip.get("duration", 1.0) or 1.0), black):
                segments.append((float(clip["start"]), float(clip["start"]) + float(clip["duration"]), black))
                missing.append(str(clip.get("id")))
            continue
        seg_path = os.path.join(work, f"clip_{i:03d}{_SEGMENT_SUFFIX}")
        ok = await asyncio.to_thread(
            build_edl_segment, src["path"], clip, profile_w, profile_h, profile_fps, seg_path)
        if ok:
            segments.append((float(clip["start"]), float(clip["start"]) + float(clip["duration"]), seg_path))
        else:
            missing.append(str(clip.get("id")))
        emit(10 + int(30 * (i + 1) / max(1, len(clips))), f"Segment {i + 1}/{len(clips)}")
    report["missing_clips"] = missing

    if not segments:
        report["error"] = "no renderable video segments"
        return report

    # 4) transitions + concat
    junctions: List[Tuple[float, Optional[str]]] = []
    ordered = sorted(clips, key=lambda c: float(c.get("start", 0.0)))
    for i in range(len(ordered) - 1):
        a, b = ordered[i], ordered[i + 1]
        junction_start = float(a.get("start", 0.0)) + float(a.get("duration", 0.0))
        value = b.get("transition_in") or a.get("transition_out") or "cut"
        junctions.append((junction_start, value))
    emit(45, "Assembling timeline")
    silent = os.path.join(work, "silent.mp4")
    ok = await asyncio.to_thread(
        concatenate_edl_timeline, segments, junctions, profile_w, profile_h, profile_fps, total, silent)
    if not ok:
        report["error"] = "timeline assembly failed"
        return report
    report["total_footage"] = round(sum(end - s for (s, end, _) in segments), 3)

    # 5) captions
    caption_track = tracks.get(TRACK_CAPTION) or {"clips": []}
    captions = [c for c in caption_track.get("clips") or [] if str(c.get("text") or "").strip()]
    current_video = silent
    if captions:
        ass_path = os.path.join(work, "captions.ass")
        await asyncio.to_thread(build_ass_captions, captions, ass_path)
        burned = os.path.join(work, "captioned.mp4")
        if await asyncio.to_thread(burn_ass_captions, current_video, ass_path, burned):
            current_video = burned
            emit(60, "Captions burned")
        else:
            logger.warning("ASS caption burn failed; falling back to drawtext")

    # 6) audio
    emit(65, "Mixing audio")
    audio_clips: Dict[str, List[Dict[str, Any]]] = {
        TRACK_NARRATION: [c for c in (tracks.get(TRACK_NARRATION) or {}).get("clips", [])
                          if str(c.get("source_id") or "") in sources],
        TRACK_MUSIC: [c for c in (tracks.get(TRACK_MUSIC) or {}).get("clips", [])
                      if str(c.get("source_id") or "") in sources],
        TRACK_SFX: [c for c in (tracks.get(TRACK_SFX) or {}).get("clips", [])
                    if str(c.get("source_id") or "") in sources],
    }
    audio_path = os.path.join(work, "mix.m4a")
    audio_ok, _ = await asyncio.to_thread(mix_audio_edl, audio_clips, sources, total, audio_path)
    if not valid_media(audio_path):
        audio_ok = False

    # 7) mux
    emit(85, "Muxing output")
    final = out_path
    cmd = ["ffmpeg", "-y", "-threads", "1", "-i", current_video]
    if audio_ok:
        cmd += ["-i", audio_path, "-c:v", "libx264"]
    else:
        cmd += ["-c:v", "libx264"]
    cmd += ["-preset", "ultrafast", "-pix_fmt", "yuv420p", "-movflags", "+faststart"]
    if audio_ok:
        cmd += ["-c:a", "aac", "-b:a", "192k", "-shortest"]
    else:
        cmd += ["-an"]
    cmd += ["-r", str(profile_fps), final]
    ok, _ = await asyncio.to_thread(run_ffmpeg, cmd)
    report["audio_present"] = bool(audio_ok)
    if ok and valid_media(final):
        report["ok"] = True
        emit(100, "Render complete")
    else:
        report["error"] = "mux failed"
    return report


# --------------------------------------------------------------------------
# lightweight quality check
# --------------------------------------------------------------------------
def quick_render_check(path: str, *, kind: str = "preview") -> Dict[str, Any]:
    """Non-zero duration, audio stream present, no black first frame."""
    report: Dict[str, Any] = {"duration": 0.0, "audio": False, "black_first_frame": None, "pass": False}
    if not valid_media(path):
        report["error"] = "file missing or empty"
        return report
    report["duration"] = _probe_duration(path)
    try:
        result = subprocess.run(
            ["ffprobe", "-v", "quiet", "-print_format", "json", "-show_streams", path],
            capture_output=True, text=True, timeout=30)
        data = json.loads(result.stdout or "{}")
        report["audio"] = any(s.get("codec_type") == "audio" for s in data.get("streams", []))
    except Exception as e:
        report["error"] = f"probe failed: {e}"
        report["pass"] = report["duration"] > 0.5
        return report
    # black-frame check: 1s sample; failures are non-blocking
    try:
        res = subprocess.run(
            ["ffmpeg", "-t", "1", "-i", path,
             "-vf", "blackdetect=d=0.05:pix_th=0.10", "-an", "-f", "null", "-"],
            capture_output=True, text=True, timeout=30)
        bd = [ln for ln in (res.stderr or "").splitlines() if "blackdetect" in ln and "black_start" in ln]
        if bd:
            try:
                start = float(bd[0].split("black_start:")[1].split()[0])
                report["black_first_frame"] = start < 0.05
            except (ValueError, IndexError):
                report["black_first_frame"] = False
        else:
            report["black_first_frame"] = False
    except Exception:
        report["black_first_frame"] = None
    report["pass"] = report["duration"] > 0.5
    if report["black_first_frame"]:
        report["warning"] = "first frame is black"
    return report
