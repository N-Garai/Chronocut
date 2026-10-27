import logging
from typing import Any, Dict, List

logger = logging.getLogger("chronocut.agents.sub_agents.script_builder")


class ScriptBuilderSubAgent:
    """Sub-agent that assembles the final script with timestamps."""

    def build_script(self, cleaned_segments: List[Dict[str, Any]], arc: Dict[str, Any]) -> Dict[str, Any]:
        script = []
        segment_id = 1
        for seg in cleaned_segments:
            script.append({
                "segment_id": segment_id,
                "text": seg.get("text", "").strip(),
                "audio_start": seg.get("start", 0),
                "audio_end": seg.get("end", 0),
                "tone": self._assign_tone(seg, arc),
                "suggested_visuals": ["user_photo", "broll"],
            })
            segment_id += 1

        total_duration = sum(s.get("audio_end", 0) - s.get("audio_start", 0) for s in cleaned_segments)
        return {"script": script, "total_duration_seconds": round(total_duration, 1)}

    def _assign_tone(self, seg: Dict[str, Any], arc: Dict[str, Any]) -> str:
        for beat in arc.get("key_beats", []):
            if beat.get("start", 0) <= seg.get("start", 0) <= beat.get("end", 0):
                return beat.get("tone", "reflective")
        return "reflective"
