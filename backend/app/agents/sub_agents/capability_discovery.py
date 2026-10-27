"""CapabilityDiscoveryAgent (M2) — advertises the live tool/provider registry.

Thin agent: delegates to the runtime ToolRegistry so the orchestrator and UI
can discover what the system can actually do. No model calls (free tier).
"""
from typing import Dict, Any


class CapabilityDiscoveryAgent:
    async def run(self) -> Dict[str, Any]:
        from app.tools.registry import registry
        registry.discover()
        envelope = registry.support_envelope()
        return {
            "capabilities": list(envelope.keys()),
            "count": len(envelope),
            "envelope": envelope,
            "provider_menu": registry.provider_menu(),
        }
