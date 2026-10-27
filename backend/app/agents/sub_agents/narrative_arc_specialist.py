"""NarrativeArcSpecialist — extracts/validates the 3-act structure of a script.

Read-only analysis of the Screenwriter output; no model calls. Ensures every
script carries a usable narrative_arc that downstream agents can rely on.
"""
from typing import Dict, Any, List


class NarrativeArcSpecialist:
    async def run(self, script_out: Dict[str, Any]) -> Dict[str, Any]:
        script_out = script_out or {}
        arc: List[str] = list(script_out.get("narrative_arc") or [])
        segs: List[Dict[str, Any]] = script_out.get("script", []) or []
        if not arc and segs:
            n = len(segs)
            if n == 1:
                arc = ["hook"]
            else:
                arc = ["hook"] + ["setup"] * (n - 2) + ["payoff"]
        return {"narrative_arc": arc, "segment_count": len(segs)}
