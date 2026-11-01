"""Document ingestion: turn any uploaded file into usable brief text.

The studio accepts any file type. Audio, images and video go to their pipeline
buckets; everything else is treated as a document — a brief, a script, a notes
file, a subtitle or an exported chat — and its text becomes part of the
director's brief. Extraction is dependency-free: text-like files are decoded
directly, subtitle formats are normalised, and binaries contribute their file
name plus any printable strings so the plan is never silently empty.
"""
import logging
import os
import re
from typing import Any, Dict, List, Optional

logger = logging.getLogger("chronocut.tools.media.documents")

MAX_DOC_CHARS = 8000
TEXT_EXTS = {
    ".txt", ".md", ".markdown", ".rst", ".json", ".csv", ".tsv", ".yaml", ".yml",
    ".log", ".ini", ".toml", ".html", ".htm", ".xml", ".tex",
}
SUB_EXTS = {".srt", ".vtt", ".ass", ".ssa"}
_STRINGS_RE = re.compile(rb"[\x20-\x7e]{12,}")
_TAG_RE = re.compile(r"<[^>]+>")

__all__ = ["is_document", "extract_text", "collect_documents", "brief_from_documents",
           "merge_prompt_with_documents"]


def is_document(filename: str) -> bool:
    ext = os.path.splitext(str(filename or ""))[1].lower()
    return ext not in {""} and ext not in {
        ".mp3", ".wav", ".m4a", ".aac", ".ogg", ".flac", ".wma", ".opus", ".aiff", ".au",
        ".jpg", ".jpeg", ".png", ".webp", ".heic", ".gif", ".bmp", ".tiff", ".tif", ".svg",
        ".avif", ".mp4", ".mov", ".avi", ".mkv", ".webm", ".m4v", ".mpg", ".mpeg", ".zip",
    }


def _decode_text(data: bytes) -> str:
    for enc in ("utf-8", "utf-16", "latin-1"):
        try:
            return data.decode(enc)
        except (UnicodeDecodeError, LookupError):
            continue
    return data.decode("utf-8", "ignore")


def _strip_subtitle_timing(text: str) -> str:
    lines = []
    for line in text.splitlines():
        s = line.strip()
        if not s or s.isdigit() or "-->" in s:
            continue
        if s.upper().startswith(("WEBVTT", "NOTE", "[SCRIPT", "DIALOGUE:")):
            continue
        if s.startswith(("Dialogue:", "Comment:")):      # .ass
            parts = s.split(",", 9)
            if len(parts) == 10:
                lines.append(parts[9].replace("\\N", " "))
            continue
        lines.append(s)
    return " ".join(lines)


def _printable_strings(data: bytes, limit: int = 4000) -> str:
    chunks = [m.group(0).decode("latin-1", "ignore") for m in _STRINGS_RE.finditer(data[:2_000_000])]
    return " ".join(chunks)[:limit]


def extract_text(path: str, filename: Optional[str] = None) -> str:
    """Best-effort text for one document; never raises."""
    name = filename or os.path.basename(path)
    ext = os.path.splitext(name)[1].lower()
    try:
        with open(path, "rb") as f:
            data = f.read()
    except OSError as e:
        logger.warning("document read failed for %s: %s", name, e)
        return ""
    if not data:
        return ""
    raw = _decode_text(data)
    if ext in SUB_EXTS:
        return _strip_subtitle_timing(raw)[:MAX_DOC_CHARS]
    if ext in TEXT_EXTS:
        text = _TAG_RE.sub(" ", raw) if ext in {".html", ".htm", ".xml"} else raw
        return re.sub(r"\s+\n", "\n", text).strip()[:MAX_DOC_CHARS]
    # Unknown/binary format (pdf, docx, ...): printable strings keep the gist.
    text = _printable_strings(data)
    return text.strip()[:MAX_DOC_CHARS]


def collect_documents(paths: List[str]) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for path in paths or []:
        name = os.path.basename(path)
        text = extract_text(path, name)
        out.append({
            "file": path,
            "name": name,
            "chars": len(text),
            "text": text,
            "extracted": bool(text),
        })
    return out


def merge_prompt_with_documents(prompt: str, document_files: List[str]) -> Dict[str, Any]:
    """Fold document text into the director's brief.

    Returns ``{prompt, documents, count, chars}``; a missing/unreadable document
    still contributes its name so the brief stays honest about what was added.
    """
    docs = collect_documents(list(document_files or []))
    brief = brief_from_documents(docs)
    merged = (str(prompt or "").strip()
              + ("\n\nSource documents:\n" + brief if brief else "")).strip()
    return {"prompt": merged, "documents": docs, "count": len(docs),
            "chars": sum(int(d.get("chars") or 0) for d in docs)}


def brief_from_documents(docs: List[Dict[str, Any]], limit_chars: int = 2400) -> str:
    """Brief fragment appended to the director's prompt."""
    parts: List[str] = []
    used = 0
    for doc in docs or []:
        text = (doc.get("text") or "").strip()
        if not text:
            parts.append(f"[{doc.get('name')}: attached, no extractable text]")
            continue
        room = max(0, limit_chars - used)
        if room <= 0:
            break
        chunk = text[:room]
        parts.append(f"[{doc.get('name')}] {chunk}")
        used += len(chunk)
    return "\n\n".join(parts).strip()
