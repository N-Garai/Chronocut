"""Sub-agent registry .

The orchestrator decomposes the pipeline into specialized sub-agents. Each is a
thin, free-tier-safe wrapper around the existing deterministic tools — no agent
spins up its own extra model calls, so the system stays within the 512MB /
free-tier budget while presenting a clean agent decomposition for auditing.
"""
from typing import Dict, Any


_AGENTS: Dict[str, Any] = {}


def register(name: str, cls) -> None:
    _AGENTS[name] = cls


def discover() -> None:
    from app.agents.sub_agents.capability_discovery import CapabilityDiscoveryAgent
    from app.agents.sub_agents.budget_governor_agent import BudgetGovernorAgent
    from app.agents.sub_agents.filler_analyzer import FillerAnalyzerAgent
    from app.agents.sub_agents.narrative_arc_specialist import NarrativeArcSpecialist
    from app.agents.sub_agents.visual_matcher_specialist import VisualMatcherSpecialist
    from app.agents.sub_agents.broll_sourcing_specialist import BRollSourcingSpecialist
    from app.agents.sub_agents.storyboard_composer_agent import StoryboardComposerAgent
    from app.agents.sub_agents.self_review_agent import SelfReviewAgent

    register("capability_discovery", CapabilityDiscoveryAgent)
    register("budget_governor", BudgetGovernorAgent)
    register("filler_analyzer", FillerAnalyzerAgent)
    register("narrative_arc_specialist", NarrativeArcSpecialist)
    register("visual_matcher_specialist", VisualMatcherSpecialist)
    register("broll_sourcing_specialist", BRollSourcingSpecialist)
    register("storyboard_composer", StoryboardComposerAgent)
    register("self_review", SelfReviewAgent)


def list_agents() -> Dict[str, Any]:
    discover()
    return dict(_AGENTS)
