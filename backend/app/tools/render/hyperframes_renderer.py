"""N. HyperFrames kinetic-typography overlay engine (Apache-2.0, local, free-tier).

Renders rich animated text overlays (intro kinetic card, per-shot lower-thirds,
word-synced karaoke captions, end card) as a transparent WebM via headless Chrome
+ ffmpeg, then composites it over the ffmpeg-cut video. Realizes the Remotion
insights (N5) -- data-driven, frame-as-function-of-time animation and word-synced
karaoke -- using plain HTML/CSS (no React, no external JS lib, works offline).

CRITICAL: every failure (missing Node/Chromium, npx error, non-zero render,
composite error) returns False so the caller falls back to the drawtext path.
This module NEVER raises into the render pipeline.
"""
import os
import json
import logging
import shutil
import subprocess
import tempfile
from typing import Dict, Any, List, Optional

logger = logging.getLogger("chronocut.tools.render.hyperframes")


def _esc(s: str) -> str:
    return (str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
            .replace('"', "&quot;"))


def _hf_available() -> bool:
    """True only if the HyperFrames CLI can be invoked (Node + npx present)."""
    from app.config import settings
    exe = settings.HYPERFRAMES_BIN.split()[0]
    if exe == "npx":
        return shutil.which("npx") is not None and shutil.which("node") is not None
    return shutil.which(exe) is not None


def build_spec(
    storyboard: List[Dict], narration_dir: str, total_duration: float, title: str = ""
) -> List[Dict[str, Any]]:
    """Turn the storyboard into a list of timed overlay descriptors.

    Each: {kind, text, start, end, words?} where words is the edge-tts
    word-boundary list (N4 karaoke) when a sidecar exists.
    """
    from app.config import settings
    spec: List[Dict[str, Any]] = []
    cap = max(1, settings.HYPERFRAMES_CAP_SECONDS)
    total = max(1.0, total_duration)

    # Intro kinetic card (Remotion-style title that "feels like an ad").
    t = (title or "ChronoCut").strip() or "ChronoCut"
    intro_end = min(max(2.5, len(t.split()) * 0.22), cap, total * 0.4)
    spec.append({"kind": "intro", "text": t, "start": 0.0, "end": round(intro_end, 2)})

    running = 0.0
    for shot in storyboard:
        dur = float(shot.get("duration_seconds", 3.0))
        start = running
        running += dur
        txt = shot.get("overlay_text")
        if not txt or not str(txt).strip():
            continue
        words = None
        wj = os.path.join(narration_dir, f"{shot.get('shot_id')}.mp3.words.json")
        if os.path.exists(wj):
            try:
                with open(wj, encoding="utf-8") as f:
                    words = json.load(f).get("words")
            except Exception:
                words = None
        spec.append({
            "kind": "lower", "text": str(txt).strip(),
            "start": round(start, 2), "end": round(start + dur, 2),
            "words": words,
        })

    # End card.
    if total > cap:
        spec.append({"kind": "outro", "text": "Created with ChronoCut",
                     "start": round(total - cap, 2), "end": round(total, 2)})
    return spec


def write_composition(spec: List[Dict[str, Any]], width: int, height: int,
                      fps: int, html_path: str) -> bool:
    """Write a single transparent index.html composition using CSS keyframe
    animations (no GSAP/CDN) so it is deterministic and works offline."""
    try:
        fs = max(20, int(height * 0.045))      # lower-third font
        fk = max(28, int(height * 0.075))      # kinetic font
        blocks = []
        for o in spec:
            start = float(o["start"])
            end = float(o["end"])
            if o["kind"] in ("intro", "outro"):
                out_t = max(start, end - 0.5)
                anim = f"kIn .6s cubic-bezier(.2,.8,.2,1) both {start:.2f}s, kOut .5s ease both {out_t:.2f}s"
                blocks.append(
                    f'<div class="kinetic" style="animation:{anim}">{_esc(o["text"])}</div>'
                )
            else:
                # lower-third; karaoke if word timings are present.
                out_t = max(start, end - 0.4)
                anim = f"inUp .4s ease both {start:.2f}s, outUp .4s ease both {out_t:.2f}s"
                if o.get("words"):
                    inner = ""
                    for w in o["words"]:
                        ws = start + float(w.get("start", 0))
                        we = start + float(w.get("end", 0))
                        inner += (f'<span class="w" style="animation:wOn .12s both {ws:.2f}s, '
                                  f'wOff .12s both {we:.2f}s">{_esc(w.get("word", ""))} </span>')
                else:
                    inner = _esc(o["text"])
                blocks.append(f'<div class="lower" style="animation:{anim}">{inner}</div>')

        css = f"""
        html,body{{margin:0;padding:0;width:{width}px;height:{height}px;
          background:transparent;overflow:hidden;}}
        *{{box-sizing:border-box;}}
        .lower{{position:absolute;left:6%;bottom:9%;max-width:88%;
          color:#fff;font:600 {fs}px/1.3 'Segoe UI',Arial,sans-serif;
          text-shadow:0 2px 10px rgba(0,0,0,.85);
          background:rgba(10,10,10,0.85);padding:1.4vh 2.2vh;border-radius:1.4vh;
          letter-spacing:.2px;}}
        .kinetic{{position:absolute;left:0;right:0;top:50%;transform:translateY(-50%);
          text-align:center;color:#fff;font:800 {fk}px/1.15 'Segoe UI',Arial,sans-serif;
          text-shadow:0 4px 24px rgba(0,0,0,.7);padding:0 6%;}}
        .w{{color:#fff;}}
        @keyframes inUp{{from{{opacity:0;transform:translateY(24px)}}to{{opacity:1;transform:translateY(0)}}}}
        @keyframes outUp{{from{{opacity:1;transform:translateY(0)}}to{{opacity:0;transform:translateY(-18px)}}}}
        @keyframes kIn{{from{{opacity:0;transform:translateY(-50%) scale(.82)}}to{{opacity:1;transform:translateY(-50%) scale(1)}}}}
        @keyframes kOut{{from{{opacity:1;transform:translateY(-50%) scale(1)}}to{{opacity:0;transform:translateY(-50%) scale(1.08)}}}}
        @keyframes wOn{{to{{color:#ffd54a;}}}}
        @keyframes wOff{{to{{color:#fff;}}}}
        """
        html = (
            "<!doctype html><html lang='en'><head><meta charset='utf-8'>"
            f"<style>{css}</style></head><body>" + "".join(blocks) + "</body></html>"
        )
        with open(html_path, "w", encoding="utf-8") as f:
            f.write(html)
        return True
    except Exception as e:
        logger.error(f"hyperframes composition write failed: {e}")
        return False


def _hf_env() -> Dict[str, str]:
    """Process env for HyperFrames launches.

    HYPERFRAMES_CHROME_ARGS drives the wrapped chrome-headless-shell binary (so it
    applies on every render). PRODUCER_LOW_MEMORY_MODE is required for containers,
    where HyperFrames' low-memory detection reads host RAM (not cgroup limits).
    """
    from app.config import settings
    env = dict(os.environ)
    env["HYPERFRAMES_CHROME_ARGS"] = settings.HYPERFRAMES_CHROME_ARGS
    env["PRODUCER_LOW_MEMORY_MODE"] = "1"
    return env


def _render_webm(html_dir: str, out_webm: str, width: int, height: int, fps: int) -> bool:
    from app.config import settings
    bin = settings.HYPERFRAMES_BIN.split()
    env = _hf_env()
    # Best-effort: ensure a Chrome is available (no-op if already present / offline).
    try:
        subprocess.run(bin + ["browser", "ensure"], cwd=html_dir, env=env,
                       capture_output=True, text=True, timeout=300)
    except Exception:
        pass
    # --low-memory-mode + --workers 1 keep a 5s clip inside the 512MB free tier;
    # --quiet trims logs. Chrome flags come from the wrapped binary via env.
    cmd = bin + ["render", "--format", "webm", "--output", out_webm,
                "--width", str(width), "--height", str(height), "--fps", str(fps),
                "--low-memory-mode", "--workers", "1", "--quiet"]
    try:
        res = subprocess.run(cmd, cwd=html_dir, env=env,
                             capture_output=True, text=True, timeout=600)
        return res.returncode == 0 and os.path.exists(out_webm) and os.path.getsize(out_webm) > 0
    except Exception as e:
        logger.error(f"hyperframes render failed: {e}")
        return False


def compose_overlays(
    storyboard: List[Dict], narration_dir: str, profile, base_video: str,
    out_video: str, title: str = "",
) -> bool:
    """Render the HyperFrames overlay and composite it over base_video.

    Returns True on success; False on ANY failure (caller must fall back to
    drawtext). Does not raise.
    """
    try:
        from app.config import settings
        if not settings.overlay_engine_is_hyperframes:
            return False
        if not _hf_available():
            logger.warning("HyperFrames CLI unavailable (Node/Chromium missing); "
                           "falling back to drawtext captions.")
            return False
        total = sum(float(s.get("duration_seconds", 3.0)) for s in storyboard) or 5.0
        spec = build_spec(storyboard, narration_dir, total, title)
        if not spec:
            return False
        d = tempfile.mkdtemp(prefix="cc_hf_")
        html_path = os.path.join(d, "index.html")
        if not write_composition(spec, profile.width, profile.height, profile.fps, html_path):
            return False
        webm = os.path.join(d, "overlay.webm")
        if not _render_webm(d, webm, profile.width, profile.height, profile.fps):
            return False
        # N1/N4: composite the transparent WebM over the ffmpeg-cut video.
        cmd = [
            "ffmpeg", "-y", "-threads", "2", "-i", base_video, "-i", webm,
            "-filter_complex", "[0:v][1:v]overlay=format=auto:shortest=1",
            "-c:v", profile.codec, "-pix_fmt", "yuv420p", "-r", str(profile.fps),
            "-an", out_video,
        ]
        res = subprocess.run(cmd, capture_output=True, text=True, timeout=900)
        return res.returncode == 0 and os.path.exists(out_video) and os.path.getsize(out_video) > 0
    except Exception as e:
        logger.error(f"hyperframes compose_overlays failed: {e}")
        return False
