import logging
from typing import Any, Dict, List, Optional, Callable
from dataclasses import dataclass, field

logger = logging.getLogger("chronocut.tools.registry")


@dataclass
class BaseTool:
    name: str
    capability: str
    cost_cents: float = 0.0
    requires: List[str] = field(default_factory=list)
    description: str = ""
    fn: Optional[Callable] = None


class ToolRegistry:
    """Runtime-discovered tool registry.

    Tools self-register via the @tool decorator. The orchestrator queries the
    registry for available capabilities instead of hard-coding imports, which
    keeps the system decoupled and auditable.
    """

    def __init__(self):
        self._tools: Dict[str, BaseTool] = {}
        self._discovered = False

    def register(self, tool: BaseTool) -> None:
        self._tools[tool.name] = tool

    def discover(self) -> None:
        if self._discovered:
            return
        # Import side-effect: each module registers its tools.
        try:
            from app.tools import audio as _a  # noqa: F401
            from app.tools import vision as _v  # noqa: F401
            from app.tools import footage as _f  # noqa: F401
            from app.tools import script as _s  # noqa: F401
            from app.tools import storyboard as _sb  # noqa: F401
            from app.tools import render as _r  # noqa: F401
            from app.tools import audio_post as _ap  # noqa: F401
            from app.tools import review as _rv  # noqa: F401
            from app.tools import reference as _ref  # noqa: F401
            from app.tools import governance as _g  # noqa: F401
        except Exception as e:
            logger.warning(f"Tool discovery partial: {e}")
        self._discovered = True

    def get(self, name: str) -> Optional[BaseTool]:
        return self._tools.get(name)

    def all(self) -> List[BaseTool]:
        return list(self._tools.values())

    def support_envelope(self) -> Dict[str, Any]:
        """Live capability map for /api/v1/capabilities.

        Every entry reflects the configuration actually loaded at runtime: the
        active text provider, the speech-to-text and vision modality it serves,
        optional generated stills, and the render profiles the furnace can
        produce. The UI and the agents read this instead of hard-coding a
        provider menu.
        """
        from app.config import settings

        provider, model = settings.model_badge
        provider_key = bool(settings.provider_api_key)
        is_meta = provider == "meta"

        transcribe_providers = []
        if is_meta and provider_key:
            transcribe_providers.append("meta_asr")
        transcribe_providers.append("whisper_local")

        vision_providers = ["meta_vision"] if is_meta and provider_key else []

        try:
            from app.tools.render.profiles import PROFILES
            profile_names = list(PROFILES.keys())
        except Exception:  # pragma: no cover - profiles are always importable
            profile_names = []

        image_gen = settings.image_gen_provider != "off"
        env = {
            "text": {
                "enabled": provider_key,
                "provider": provider,
                "model": model,
                "fallback": "deterministic templates",
                "note": "All generation flows through the provider layer; without a key the pipeline runs deterministic fallbacks",
            },
            "audio_transcribe": {
                "enabled": True,
                "providers": transcribe_providers,
                "model": settings.META_ASR_MODEL if is_meta else None,
                "note": "Provider speech-to-text first, local Whisper last",
            },
            "image_tag": {
                "enabled": True,
                "providers": vision_providers,
                "model": model if is_meta else None,
            },
            "video_understanding": {
                "enabled": bool(is_meta and provider_key),
                "providers": ["meta_files_api"] if is_meta and provider_key else [],
                "note": "Whole-clip summaries through the provider Files API; skipped when unavailable",
            },
            "vision_embed": {
                "enabled": True,
                "providers": [],
                "note": "Semantic footage corpus embeddings; deterministic lexical match without it",
            },
            "footage_search": {
                "enabled": True,
                "providers": {
                    "footage_corpus": settings.ENABLE_FOOTAGE_CORPUS,
                    "pexels": bool(settings.PEXELS_API_KEY),
                    "pixabay": bool(settings.PIXABAY_API_KEY),
                    "wikimedia": True,
                    "archive_org": True,
                    "nasa": True,
                },
                "note": "Fallback chain: corpus -> stock providers -> free archives -> generated stills -> deterministic matte",
            },
            "image_gen": {
                "enabled": image_gen,
                "providers": [settings.image_gen_provider] if image_gen else [],
                "model": "flux-1-schnell" if image_gen else None,
                "note": "Optional generated B-roll stills; degrades to stills/footage when off or out of quota",
            },
            "script": {
                "enabled": True,
                "providers": ["from_transcript", "from_reference", "from_prompt"],
            },
            "storyboard": {
                "enabled": True,
                "providers": ["visual_matcher", "broll_sourcer", "shot_composer"],
            },
            "render": {
                "enabled": True,
                "providers": ["ffmpeg", "moviepy_fallback"],
                "engine": settings.text_overlay_engine,
                "dispatcher": settings.render_dispatcher,
                "max_height": settings.MAX_RENDER_RESOLUTION,
                "profiles": profile_names,
            },
            "audio_post": {
                "enabled": True,
                "providers": ["normalize", "duck", "sfx_bed", "music_mixer"],
            },
            "review": {
                "enabled": settings.ENABLE_SELF_REVIEW,
                "providers": ["ffprobe", "frame_sampler", "audio_levels", "delivery_promise", "slideshow_detector"],
            },
            "edl": {
                "enabled": True,
                "providers": ["validate", "operations", "revision_store", "compiler", "otio_export"],
            },
            "cache": {
                "enabled": True,
                "providers": ["llm_cache", "embedding_cache", "asset_cache"],
            },
            "reference": {
                "enabled": settings.ENABLE_REFERENCE_VIDEO,
                "providers": ["yt_dlp_fetch", "whisper_transcribe", "scene_detect", "keyframe_extract", "reference_analyze"],
            },
            "rag": {
                "enabled": settings.ENABLE_RAG,
                "providers": ["embedding_recall"],
            },
            "governance": {
                "enabled": True,
                "providers": ["budget_governor", "cost_ledger"],
                "per_job_cap_cents": settings.PER_JOB_COST_CAP_CENTS,
            },
            "frontend": {
                "enabled": True,
                "providers": ["sse_emit"],
            },
        }
        return env

    def provider_menu(self) -> List[Dict[str, Any]]:
        from app.tools.llm.scorer import provider_menu
        return provider_menu()


registry = ToolRegistry()


def tool(name: str, capability: str, cost_cents: float = 0.0, requires: Optional[List[str]] = None, description: str = ""):
    def decorator(fn: Callable) -> Callable:
        registry.register(BaseTool(
            name=name, capability=capability, cost_cents=cost_cents,
            requires=requires or [], description=description, fn=fn,
        ))
        return fn
    return decorator
