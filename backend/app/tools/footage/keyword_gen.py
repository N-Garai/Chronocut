"""Extract clean, searchable B-roll keywords from a user prompt.

The screenwriter sometimes echoes the whole prompt as a "visual", which makes a
terrible Pexels/Pixabay query (it matches nothing useful or the same clip for
every shot). This module produces short, concrete, *distinct* search phrases via
an LLM, with a deterministic heuristic fallback so footage search always has good
terms even when Gemini is unavailable.
"""
import logging
import re
from typing import List, Optional

logger = logging.getLogger("chronocut.tools.footage.keyword_gen")

_STOP = {
    "a", "an", "the", "of", "for", "to", "in", "on", "at", "by", "with", "and",
    "or", "about", "how", "what", "why", "this", "that", "these", "those",
    "using", "stock", "footage", "video", "videos", "documentary", "mini",
    "second", "seconds", "short", "cinematic", "film", "films", "movie",
    "story", "tell", "show", "make", "create", "generate", "produce", "is",
    "are", "be", "can", "could", "would", "should", "we", "i", "you", "your",
    "our", "their", "them", "then", "than", "into", "from", "as", "at", "its",
    "it's", "showing", "depicting", "featuring", "scene", "scenes",
}

_DESCRIPTOR = {
    "wide", "shot", "close", "up", "detail", "aerial", "slow", "motion",
    "cinematic", "medium", "long", "establishing", "pan", "zoom", "tracking",
    "static", "lighting", "mood", "color", "colour", "grading", "broll",
    "b-roll", "footage", "video", "view", "angle", "est",
}


def _dedupe(items: List[str]) -> List[str]:
    seen = set()
    out = []
    for it in items:
        k = it.lower().strip()
        if k and k not in seen:
            seen.add(k)
            out.append(it)
    return out


def _is_content(term: str) -> bool:
    """True if the phrase contains at least one non-descriptor, non-stopword."""
    words = re.findall(r"[a-zA-Z]+", term.lower())
    if not words:
        return False
    return any(w not in _DESCRIPTOR and w not in _STOP for w in words)


async def extract_search_keywords(
    prompt: str, n_segments: int = 6, job_id: Optional[str] = None
) -> List[str]:
    """Return up to ``n_segments`` distinct, short, searchable keyword phrases.

    Tries an LLM first (diverse facets so each shot gets a distinct clip), then
    falls back to a heuristic split of the prompt into content-word pairs.
    """
    prompt = (prompt or "").strip()
    if not prompt:
        return _expand(["nature"], max(1, n_segments))
    try:
        from app.tools.llm.call import scored_gemini_json
        system = (
            "You convert a creative brief into B-roll search keywords for stock "
            "video sites (Pexels, Pixabay). Return ONLY JSON: "
            "{\"keywords\": [\"short phrase\", ...]}. "
            "Rules: 2-4 word CONCRETE subject phrases only (e.g. 'city lights "
            "night', 'urban fox nocturnal', 'street lamp moth'); NO full "
            "sentences; NO generic words like 'documentary' or 'cinematic'; "
            "cover DIVERSE facets (different subjects/angles/times) so each shot "
            f"gets a DISTINCT clip; produce exactly {max(3, n_segments)} keywords."
        )
        result = await scored_gemini_json(
            f"Creative brief: {prompt}\nProduce {max(3, n_segments)} distinct search keywords.",
            system=system, job_id=job_id, agent="footage", tool="keyword_gen",
            temperature=0.5, max_output_tokens=512,
        )
        kws = [str(k).strip() for k in (result.get("keywords") or []) if str(k).strip()]
        kws = _dedupe([k for k in kws if 1 < len(k) < 40 and _is_content(k)])
        if len(kws) >= 2:
            return _expand(kws, max(1, n_segments))
    except Exception as e:  # noqa: BLE001
        logger.warning(f"keyword_gen LLM failed: {e}")
    return _heuristic_keywords(prompt, n_segments)


def _heuristic_keywords(prompt: str, n: int) -> List[str]:
    words = [
        w for w in re.findall(r"[a-zA-Z]+", prompt.lower())
        if w not in _STOP and w not in _DESCRIPTOR and len(w) > 2
    ]
    phrases = []
    for i in range(0, len(words), 2):
        ph = " ".join(words[i:i + 2])
        if ph and _is_content(ph):
            phrases.append(ph)
    # If we got very few content pairs, fall back to single content words.
    if len(phrases) < 2:
        phrases = [w for w in words]
    if not phrases:
        phrases = ["nature"]
    return _expand(_dedupe(phrases), max(1, n))


def _expand(items: List[str], n: int) -> List[str]:
    if not items:
        return ["nature"]
    out = list(items)
    while len(out) < n:
        out.append(items[len(out) % len(items)])
    return out[:n]
