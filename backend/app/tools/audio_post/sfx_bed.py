import os
import logging
import subprocess
import tempfile
from typing import Optional

logger = logging.getLogger("chronocut.tools.audio_post")


def _synth_sfx(query: str, out_path: str) -> Optional[str]:
    """Synthesize a short, royalty-free sound effect locally with ffmpeg.

    Free-tier friendly: no API key, no network. Maps common cue keywords to
    plausible synthesized beds; falls back to a soft ambient pad.
    """
    q = (query or "").lower()
    if any(k in q for k in ("rain", "water", "drip", "drop")):
        src = "anoisesrc=color=brown:duration=2:amplitude=0.35"
        filt = "highpass=f=900,lowpass=f=6500,afade=t=in:st=0:d=0.2,afade=t=out:st=1.8:d=0.2"
    elif any(k in q for k in ("wind", "whoosh", "swoosh", "fly", "sweep")):
        src = "anoisesrc=color=pink:duration=2:amplitude=0.5"
        filt = "bandpass=f=800:width_type=h:w=700,afade=t=in:st=0:d=0.4,afade=t=out:st=1.6:d=0.4"
    elif any(k in q for k in ("city", "street", "traffic", "crowd", "hum", "machine")):
        src = "anoisesrc=color=brown:duration=2:amplitude=0.3"
        filt = "lowpass=f=520,afade=t=in:st=0:d=0.3,afade=t=out:st=1.7:d=0.3"
    elif any(k in q for k in ("click", "pop", "beat", "tick", "snap")):
        src = "sine=frequency=1300:duration=0.09"
        filt = "volume=0.5"
    elif any(k in q for k in ("chime", "bell", "ding", "notify")):
        src = "sine=frequency=880:duration=0.5"
        filt = "volume=0.4,apulsator=mode=sine:hz=4,afade=t=out:st=0.3:d=0.2"
    else:
        # Gentle ambient pad (two detuned sines) for generic "ambient"/"texture".
        src = "sine=frequency=110:duration=2"
        filt = ("sine=frequency=165:duration=2[s];"
                "[0:a][s]amix=inputs=2:duration=longest,volume=0.12,"
                "afade=t=in:st=0:d=0.5,afade=t=out:st=1.5:d=0.5")
    cmd = ["ffmpeg", "-y", "-f", "lavfi", "-i", src, "-filter_complex", filt,
           "-c:a", "libmp3lame", "-b:a", "128k", out_path]
    try:
        res = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
        return out_path if res.returncode == 0 and os.path.exists(out_path) else None
    except Exception as e:
        logger.warning(f"sfx synth failed: {e}")
        return None


def sfx_bed(query: str, out_dir: str) -> Optional[str]:
    """Resolve a sound-effect clip for ``query``.

    Free-tier path: synthesize locally with ffmpeg (no key needed). If a
    Pixabay key is configured, attempt a higher-quality clip first and fall
    back to the local synth on any failure.
    """
    os.makedirs(out_dir, exist_ok=True)
    out_path = os.path.join(out_dir, f"sfx_{abs(hash(query))}.mp3")

    try:
        from app.config import settings
        api_key = getattr(settings, "PIXABAY_API_KEY", None) or os.getenv("PIXABAY_API_KEY")
        if api_key:
            import requests  # lazy
            resp = requests.get(
                "https://pixabay.com/api/",
                params={"key": api_key, "q": query, "media_type": "audio", "per_page": 3},
                timeout=20,
            )
            if resp.status_code == 200:
                hits = resp.json().get("hits", [])
                if hits:
                    url = hits[0].get("audioURL") or hits[0].get("previewURL")
                    if url:
                        dl = requests.get(url, timeout=30)
                        if dl.status_code == 200:
                            with open(out_path, "wb") as f:
                                f.write(dl.content)
                            if os.path.exists(out_path) and os.path.getsize(out_path) > 0:
                                return out_path
    except Exception as e:
        logger.warning(f"sfx_bed remote failed, using local synth: {e}")

    # Local, free, key-less fallback.
    return _synth_sfx(query, out_path)
