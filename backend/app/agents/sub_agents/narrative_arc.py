import logging
from typing import Any, Dict, List

logger = logging.getLogger("chronocut.agents.sub_agents.narrative")


class NarrativeArcSubAgent:
    """Sub-agent specialized in detecting narrative structure and story beats."""

    def analyze_arc(self, segments: List[Dict[str, Any]]) -> Dict[str, Any]:
        if not segments:
            return {"arc": [], "key_beats": []}

        total_duration = segments[-1].get("end", 0) - segments[0].get("start", 0)
        third = total_duration / 3 if total_duration > 0 else 1

        beats = []
        current_beat = []
        beat_start = segments[0].get("start", 0)

        for seg in segments:
            seg_time = seg.get("start", 0)
            elapsed = seg_time - beat_start

            if elapsed > third and current_beat:
                beats.append({
                    "start": beat_start,
                    "end": seg_time,
                    "text": " ".join(s.get("text", "") for s in current_beat),
                    "tone": self._detect_tone(current_beat),
                })
                current_beat = []
                beat_start = seg_time
            current_beat.append(seg)

        if current_beat:
            beats.append({
                "start": beat_start,
                "end": segments[-1].get("end", 0),
                "text": " ".join(s.get("text", "") for s in current_beat),
                "tone": self._detect_tone(current_beat),
            })

        arc_labels = ["origin", "conflict", "resolution"] if len(beats) >= 3 else ["setup", "payoff"]
        arc = [{"label": arc_labels[i] if i < len(arc_labels) else f"beat_{i}", **beat} for i, beat in enumerate(beats)]

        return {"arc": arc, "key_beats": beats}

    def _detect_tone(self, segments: List[Dict[str, Any]]) -> str:
        text = " ".join(s.get("text", "") for s in segments).lower()
        if any(w in text for w in ["love", "happy", "wonderful", "beautiful", "joy"]):
            return "nostalgic"
        if any(w in text for w in ["hard", "struggle", "difficult", "lost", "cry"]):
            return "emotional"
        if any(w in text for w in ["work", "job", "career", "business"]):
            return "professional"
        return "reflective"
