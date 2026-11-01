"""N. HyperFrames overlay engine — pure-logic tests (no Node/Chromium needed)."""
import sys
import os

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.tools.render import hyperframes_renderer as hf
from app.config import settings


def _sb():
    return [
        {"shot_id": 1, "duration_seconds": 5.0, "overlay_text": "A rainy neon city"},
        {"shot_id": 2, "duration_seconds": 5.0, "overlay_text": "Close up of hands weaving"},
        {"shot_id": 3, "duration_seconds": 5.0, "overlay_text": None},
    ]


def _scratch_dir(tmp_path={}) -> str:
    """Host-portable scratch dir (a hard-coded /tmp does not exist on Windows)."""
    import tempfile
    d = tempfile.mkdtemp(prefix="cc_hf_test_")
    return os.path.join(d, "")


def test_build_spec_has_intro_lower_outro():
    d = _scratch_dir()
    spec = hf.build_spec(_sb(), d, 15.0, title="My Story")
    kinds = [s["kind"] for s in spec]
    assert "intro" in kinds and "outro" in kinds
    lowers = [s for s in spec if s["kind"] == "lower"]
    # shots 1 and 2 have overlay_text; shot 3 has none.
    assert len(lowers) == 2
    # timings are monotonic and within total.
    assert spec[0]["start"] == 0.0
    assert spec[-1]["end"] <= 15.0 + 1e-6
    # lower-third start times advance by 5s each.
    assert abs(lowers[0]["start"] - 0.0) < 1e-6
    assert abs(lowers[1]["start"] - 5.0) < 1e-6


def test_build_spec_karaoke_words_loaded(tmp_path):
    import json
    wj = tmp_path / "1.mp3.words.json"
    json.dump({"text": "x", "words": [{"word": "rain", "start": 0.1, "end": 0.4}]}, open(wj, "w"))
    spec = hf.build_spec(_sb(), str(tmp_path), 15.0, title="T")
    low = next(s for s in spec if s["kind"] == "lower" and s["start"] == 0.0)
    assert low["words"] and low["words"][0]["word"] == "rain"


def test_write_composition_emits_css_and_no_external_lib(tmp_path):
    spec = hf.build_spec(_sb(), str(tmp_path), 15.0, title="Title")
    p = str(tmp_path / "index.html")
    assert hf.write_composition(spec, 1280, 720, 30, p) is True
    body = open(p, encoding="utf-8").read()
    # No external CDN (offline-safe) and karaoke highlight keyframes present.
    assert "gsap" not in body.lower()
    assert "cdn" not in body.lower()
    assert "wOn" in body and "wOff" in body
    assert "Created with ChronoCut" in body


def test_compose_overlays_unavailable_returns_false():
    # With default drawtext engine, compose_overlays must decline (returns False),
    # forcing the caller's drawtext fallback. No Chromium needed.
    settings.TEXT_OVERLAY_ENGINE = "drawtext"
    prof = type("P", (), {"width": 1280, "height": 720, "fps": 30, "codec": "libx264"})()
    base = _scratch_dir()
    ok = hf.compose_overlays(_sb(), base, prof, os.path.join(base, "base.mp4"), os.path.join(base, "out.mp4"), title="T")
    assert ok is False
    settings.TEXT_OVERLAY_ENGINE = "drawtext"  # restore


def test_engine_property_normalizes():
    settings.TEXT_OVERLAY_ENGINE = "HyperFrames"
    assert settings.text_overlay_engine == "hyperframes"
    settings.TEXT_OVERLAY_ENGINE = "bogus"
    assert settings.text_overlay_engine == "drawtext"
    settings.TEXT_OVERLAY_ENGINE = "drawtext"


def test_render_webm_passes_chrome_args_and_low_memory(monkeypatch):
    """_render_webm must export HYPERFRAMES_CHROME_ARGS + PRODUCER_LOW_MEMORY_MODE
    and use --low-memory-mode/--workers 1 so the bake works on root containers."""
    settings.TEXT_OVERLAY_ENGINE = "hyperframes"
    settings.HYPERFRAMES_BIN = "npx hyperframes"

    captured = {}

    def fake_run(cmd, *a, **kw):
        captured["cmd"] = list(cmd)
        captured["env"] = dict(kw.get("env", {}))
        captured["cwd"] = kw.get("cwd")

        class R:
            returncode = 0
        return R()

    monkeypatch.setattr(hf.subprocess, "run", fake_run)

    # Make the composite step think a webm was produced.
    import pathlib
    d = pathlib.Path(_scratch_dir())
    d.mkdir(parents=True, exist_ok=True)
    out = d / "cc_hf_test.webm"
    out.write_bytes(b"x")

    ok = hf._render_webm(str(d), str(out), 1280, 720, 30)
    assert ok is True
    assert "--low-memory-mode" in captured["cmd"]
    assert "--workers" in captured["cmd"] and "1" in captured["cmd"]
    assert captured["env"].get("HYPERFRAMES_CHROME_ARGS") == settings.HYPERFRAMES_CHROME_ARGS
    assert captured["env"].get("PRODUCER_LOW_MEMORY_MODE") == "1"
    settings.TEXT_OVERLAY_ENGINE = "drawtext"
    out.unlink(missing_ok=True)


def test_hf_env_merges_chrome_args():
    settings.HYPERFRAMES_CHROME_ARGS = "--no-sandbox --disable-dev-shm-usage --single-process"
    env = hf._hf_env()
    assert env["HYPERFRAMES_CHROME_ARGS"] == "--no-sandbox --disable-dev-shm-usage --single-process"
    assert env["PRODUCER_LOW_MEMORY_MODE"] == "1"
    # inherits process env too
    assert "PATH" in env
    settings.HYPERFRAMES_CHROME_ARGS = "--no-sandbox --disable-dev-shm-usage --single-process"
