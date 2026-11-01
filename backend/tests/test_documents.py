"""Universal input: any file type becomes usable job input.

Audio/photo/video keep their pipeline buckets; everything else is ingested as a
document and folded into the director's brief. Extraction is dependency-free and
must never raise on an unknown or binary format.
"""
import pytest
from fastapi.testclient import TestClient

import app.main as main_mod
from app.job_runner import runner
from app.services.firestore_service import JobStateService
from app.tools.media.documents import (
    brief_from_documents, collect_documents, extract_text, is_document,
)


def test_classification():
    assert is_document("notes.txt") and is_document("brief.md") and is_document("doc.pdf")
    for media in ("a.mp3", "b.wav", "c.jpg", "d.png", "e.mp4", "f.zip"):
        assert not is_document(media)


def test_plain_text_is_read_verbatim(tmp_path):
    p = tmp_path / "brief.txt"
    p.write_text("A 1960s Kolkata family archive; nostalgic, warm, restrained.", encoding="utf-8")
    assert "nostalgic" in extract_text(str(p))


def test_subtitles_lose_timing_and_markup(tmp_path):
    p = tmp_path / "captions.srt"
    p.write_text("1\n00:00:01,000 --> 00:00:03,000\nWe left at dawn.\n\n"
                 "2\n00:00:03,500 --> 00:00:05,000\nThe river was high.\n", encoding="utf-8")
    text = extract_text(str(p))
    assert "We left at dawn." in text and "river was high" in text
    assert "-->" not in text and "00:00:01" not in text


def test_html_tags_are_stripped(tmp_path):
    p = tmp_path / "page.html"
    p.write_text("<h1>Grandmother</h1><p>She arrived in 1962.</p>", encoding="utf-8")
    text = extract_text(str(p))
    assert "Grandmother" in text and "arrived in 1962" in text
    assert "<h1>" not in text


def test_unknown_binary_yields_printable_gist(tmp_path):
    p = tmp_path / "scan.pdf"
    p.write_bytes(b"%PDF-1.4\x00\x00\x01binary\x00Family migration notes, 1962\x00\xff")
    text = extract_text(str(p))
    assert "Family migration notes" in text


def test_empty_and_missing_files_are_safe(tmp_path):
    empty = tmp_path / "empty.txt"
    empty.write_text("", encoding="utf-8")
    assert extract_text(str(empty)) == ""
    assert extract_text(str(tmp_path / "nope.txt")) == ""


def test_collect_and_brief_respect_the_cap(tmp_path):
    a = tmp_path / "a.txt"
    a.write_text("alpha " * 300, encoding="utf-8")
    b = tmp_path / "b.md"
    b.write_text("beta", encoding="utf-8")
    docs = collect_documents([str(a), str(b)])
    assert [d["name"] for d in docs] == ["a.txt", "b.md"]
    assert docs[0]["extracted"] and docs[1]["text"] == "beta"
    brief = brief_from_documents(docs, limit_chars=100)
    assert "a.txt" in brief and len(brief) <= 200
    assert brief_from_documents([]) == ""


def test_prompt_merge_keeps_the_writers_words_and_adds_sources(tmp_path):
    from app.tools.media.documents import merge_prompt_with_documents
    p = tmp_path / "notes.txt"
    p.write_text("Grandmother arrived in 1962 by train.", encoding="utf-8")
    merged = merge_prompt_with_documents("Make it feel like a memory.", [str(p)])
    assert merged["prompt"].startswith("Make it feel like a memory.")
    assert "arrived in 1962" in merged["prompt"]
    assert merged["count"] == 1 and merged["chars"] > 0
    # no documents leaves the brief untouched
    assert merge_prompt_with_documents("hello", [])["prompt"] == "hello"


# ------------------------------------------------------------------ upload path
@pytest.fixture()
def client(monkeypatch):
    async def _no_submit(_job_id):
        return None
    monkeypatch.setattr(runner, "submit", _no_submit)
    return TestClient(main_mod.app)


def test_any_file_type_is_accepted_and_bucketed(client):
    files = [
        ("media", ("notes.txt", b"A quiet street in 1962.", "text/plain")),
        ("media", ("scan.pdf", b"%PDF-1.4 binary family notes", "application/pdf")),
        ("media", ("a.png", b"\x89PNG fake", "image/png")),
    ]
    r = client.post("/api/v1/jobs", data={"mode": "from_media", "prompt": "archive film"},
                    files=files)
    assert r.status_code == 200
    job = JobStateService.get_job(r.json()["job_id"])
    inputs = job["input_files"]
    assert len(inputs["document_files"]) == 2
    assert len(inputs["photo_files"]) == 1
    assert all("notes.txt" in p or "scan.pdf" in p for p in inputs["document_files"])


def test_a_document_only_upload_creates_a_job(client):
    r = client.post("/api/v1/jobs", data={"mode": "from_media"},
                    files=[("media", ("script.md", b"# Story\n\nShe left at dawn.", "text/markdown"))])
    assert r.status_code == 200
    job = JobStateService.get_job(r.json()["job_id"])
    assert len(job["input_files"]["document_files"]) == 1
    assert not job["input_files"]["audio_files"]
