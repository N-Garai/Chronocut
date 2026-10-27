import os
import re
import logging
from typing import Any, Dict, List

logger = logging.getLogger("chronocut.agents.sub_agents.screenwriter")


class FillerRemovalSubAgent:
    """Sub-agent specialized in removing conversational fillers and disfluencies."""

    FILLER_PATTERNS = [
        r"\bum+\b",
        r"\buh+\b",
        r"\blike\b(?!\s+this|\s+that|\s+the|\s+a|\s+an)",
        r"\byou know\b",
        r"\bI mean\b",
        r"\bbasically\b",
        r"\bactually\b(?!\s+is|\s+was|\s+are|\s+were)",
        r"\bso\b(?!\s+much|\s+many|\s+good|\s+bad)",
        r"\bright\b(?!\s+now|\s+away|\s+back)",
        r"\bkind of\b",
        r"\bsort of\b",
    ]

    def clean_transcript(self, segments: List[Dict[str, Any]]) -> tuple[List[Dict[str, Any]], float]:
        cleaned = []
        total_removed = 0
        total_words = 0

        for seg in segments:
            original = seg.get("text", "")
            words = original.split()
            total_words += len(words)

            cleaned_text = original
            for pattern in self.FILLER_PATTERNS:
                cleaned_text = re.sub(pattern, "", cleaned_text, flags=re.IGNORECASE)
                cleaned_text = re.sub(r'\s+', ' ', cleaned_text).strip()

            removed = len(words) - len(cleaned_text.split())
            total_removed += removed

            cleaned.append({**seg, "text": cleaned_text})

        removal_pct = round((total_removed / total_words) * 100, 1) if total_words > 0 else 0
        logger.info(f"Filler removal: {total_removed} words removed ({removal_pct}%)")
        return cleaned, removal_pct
