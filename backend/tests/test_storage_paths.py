"""Storage path resolution: the single tmp-root contract (CHRONOCUT_TMP_DIR),
id scrubbing, filename safety, and database-path re-keying after volumes move.
"""
from pathlib import Path

from app.config import settings
from app.services import storage


def test_safe_job_id_strips_everything_unsafe():
    assert storage.safe_job_id("abc-123") == "abc-123"
    assert storage.safe_job_id("a/b\\c:d*e") == "abcde"
    assert storage.safe_job_id("") == ""
    assert storage.safe_job_id(None) == ""
    assert len(storage.safe_job_id("x" * 200)) == 80


def test_safe_filename_keeps_the_extension_and_sanitizes_the_stem():
    name = storage.safe_filename("../../etc/passwd")
    assert "/" not in name and ".." not in name
    assert name.startswith("passwd_")        # path pieces stripped by basename
    name2 = storage.safe_filename("my interview file.mov")
    assert name2.startswith("my_interview_file_")
    assert name2.endswith(".mov")
    name3 = storage.safe_filename("no_extension")
    assert name3.startswith("no_extension_")
    # unique per call
    assert storage.safe_filename("dup.png") != storage.safe_filename("dup.png")
    super_long = storage.safe_filename("x" * 300 + ".wav")
    assert len(super_long.split(".wav")[0]) <= 60 + 1 + 8


def test_chronocut_tmp_dir_moves_the_whole_tree(tmp_path, monkeypatch):
    root = tmp_path / "root2"
    monkeypatch.setattr(settings, "CHRONOCUT_TMP_DIR", str(root))
    assert storage.tmp_dir() == str(root)
    jd = storage.job_dir("job~A/B")
    assert str(root) in jd and "chronocut_" in jd            # scrubbed name under root
    up = storage.job_upload_dir("job~A/B")
    assert up == str(root / f"chronocut_jobAB" / "input")
    assert (root / "chronocut_jobAB" / "input").is_dir()
    logs = storage.logs_dir()
    assert logs == str(root / "logs") and (root / "logs").is_dir()
    rd = storage.render_dir("jobAB", "render/1")
    assert rd == str(root / "chronocut_jobAB" / "renders" / "render1")
    ad = storage.asset_dir("jobAB", "generated")
    assert ad == str(root / "chronocut_jobAB" / "assets" / "generated")


def test_asset_dir_default_subdir(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "CHRONOCUT_TMP_DIR", str(tmp_path))
    base = storage.asset_dir("plain")
    assert base == str(tmp_path / "chronocut_plain" / "assets")


def test_resolve_media_path_routes_to_the_job_upload_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "CHRONOCUT_TMP_DIR", str(tmp_path))
    p = storage.resolve_media_path("j-1", "clip.zip")
    assert str(tmp_path) in p and p.endswith(".zip")
    # job-less callers land in the shared uploads dir
    p2 = storage.resolve_media_path(None, "clip.zip")
    assert "chronocut_uploads" in p2


def test_resolve_job_path_rekeys_lost_database_paths(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "CHRONOCUT_TMP_DIR", str(tmp_path))
    # a path stored on another volume prefix re-keys onto the live tmp root
    old = r"D:\old_volume\chronocut_j9\renders\r1\out.mp4"
    idx = old.find("chronocut_")
    expected = str(Path(str(tmp_path)) / old[idx:].replace("\\", "/"))
    got = storage.resolve_job_path("j9", old)
    assert got == expected
    # paths that still exist are returned untouched
    real = tmp_path / "keep.bin"
    real.write_text("x")
    assert storage.resolve_job_path("j9", str(real)) == str(real)
    # no marker -> no re-keying guess
    assert storage.resolve_job_path("j9", "/opt/data/other.bin") == \
        "/opt/data/other.bin"
    assert storage.resolve_job_path("j9", "") == ""


def test_ensure_dir_is_idempotent(tmp_path):
    d = storage.ensure_dir(str(tmp_path / "a" / "b"))
    assert Path(d).is_dir()
    assert storage.ensure_dir(d) == d
