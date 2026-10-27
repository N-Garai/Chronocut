"""FillerAnalyzerAgent — detects disfluencies in a transcript (pure, no model).

Runs locally so it adds zero latency/cost. Used by the Archivist stage to
flag filler-heavy sentences that the Screenwriter should trim.
"""
import re
from typing import Dict, Any, List

_FILLER = re.compile(
    r"\b(um|uh|er|ah|you know|like|basically|actually|i mean|sort of|kind of|well)\b",
    re.IGNORECASE,
)


class FillerAnalyzerAgent:
    async def run(self, transcript: str) -> Dict[str, Any]:
        if not transcript:
            return {"filler_count": 0, "filler_words": [], "segments": []}
        found: List[str] = _FILLER.findall(transcript)
        sentences = [s.strip() for s in re.split(r"(?<=[.!?])\s+", transcript) if s.strip()]
        segments = [{"text": s, "has_filler": bool(_FILLER.search(s))} for s in sentences]
        return {"filler_count": len(found), "filler_words": found, "segments": segments}
