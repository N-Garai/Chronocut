from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import Field
from typing import Optional, List, Tuple

# (provider name -> text model / badge) resolution shared by settings,
# the provider factory and the failover chain in ``tools/llm/call.py``.
_TEXT_MODELS = {
    "meta": None,          # resolved from META_TEXT_MODEL at call time
    "baseten": "BASETEN_MODEL",
    "openrouter": "OPENROUTER_TEXT_MODEL",
    "local": "LOCAL_LLM_MODEL",
}


def text_model_for(provider_name: str) -> str:
    """Default text model for a provider slot (empty string for ``meta`` — its
    model id lives in ``META_TEXT_MODEL`` and is resolved by the caller)."""
    field = _TEXT_MODELS.get((provider_name or "").strip().lower())
    if field is None:
        return ""
    return field


def llm_badge_for(provider_name: str, settings: "Settings") -> Tuple[str, str]:
    """(provider, model) shown in telemetry rows / docs for a provider slot."""
    name = (provider_name or "").strip().lower()
    field = _TEXT_MODELS.get(name)
    if field and field != "LOCAL_LLM_MODEL":
        return (name, getattr(settings, field, "") or "")
    if name == "local":
        return ("local", settings.LOCAL_LLM_MODEL or settings.META_TEXT_MODEL or "muse-spark-1.3")
    return ("meta", settings.META_TEXT_MODEL)


_REPO_ROOT_ENV = str(Path(__file__).resolve().parents[2] / ".env")


class Settings(BaseSettings):
    ENV: str = Field(default="development")
    PORT: int = Field(default=8000)
    HOST: str = Field(default="0.0.0.0")

    # ---- Model providers --------------------------------------------------
    # Primary: the first-party Meta Model API (muse-spark / muse-wonder text +
    # muse-voice-transcribe ASR) at api.meta.ai. Alternative: a Baseten-hosted
    # Meta open model via LLM_PROVIDER=meta with META_BASE_URL pointed at the
    # Baseten endpoint, or a local OpenAI-compatible server (Ollama, vLLM) via
    # LLM_PROVIDER=local and LOCAL_LLM_BASE_URL.
    LLM_PROVIDER: str = Field(default="meta")
    MODEL_API_KEY: Optional[str] = None   # canonical name from the provider docs
    META_API_KEY: Optional[str] = None    # alias accepted for existing setups
    META_BASE_URL: str = Field(default="https://api.meta.ai/v1")
    META_TEXT_MODEL: str = Field(default="muse-spark-1.3")
    META_TEXT_FALLBACK_MODELS: str = Field(default="muse-spark-1.2,muse-spark-1.1")
    META_ASR_MODEL: str = Field(default="muse-voice-transcribe-1.0")
    META_VISION_MODEL: str = Field(default="muse-spark-1.3")
    META_SEGMENT_MODEL: str = Field(default="sam-3.1")
    META_IMAGE_MODEL: str = Field(default="muse-image-1.0")  # optional B-roll stills
    META_ASR_MAX_SECONDS: int = Field(default=570)  # request cap safety margin (600s limit)

    # Separate hosted-provider slots, each independently configurable and each
    # serving Meta models (first-party Muse or open-weight Muse Spark). They
    # participate in the automatic text-failover chain via LLM_FALLBACK_PROVIDERS.
    # Baseten: Meta open weights (Muse Spark Open) behind a Baseten endpoint.
    BASETEN_API_KEY: Optional[str] = None
    BASETEN_BASE_URL: str = Field(default="https://inference.baseten.co/v1")
    BASETEN_MODEL: str = Field(default="meta-models/muse-spark-open")
    # OpenRouter: Meta open-weight Muse models (Muse Spark Open) via a hosted
    # inference provider. Serves as the text failover hop when the first-party
    # Meta Model API is unavailable. Llama is not used anywhere in this project.
    OPENROUTER_API_KEY: Optional[str] = None
    OPENROUTER_BASE_URL: str = Field(default="https://openrouter.ai/api/v1")
    OPENROUTER_TEXT_MODEL: str = Field(default="meta/muse-spark-open")

    # Local OpenAI-compatible endpoint (a served Meta open-weight model, e.g.
    # LM Studio running Muse Glimmer, or Ollama/vLLM on any host)
    LOCAL_LLM_BASE_URL: str = Field(default="http://localhost:11434/v1")
    LOCAL_LLM_MODEL: str = Field(default="meta-models/Muse-Glimmer-30B")
    LOCAL_LLM_API_KEY: Optional[str] = None

    # Text-to-speech: Meta MMS-TTS open weights only.
    TTS_PROVIDER: str = Field(default="mms")
    MMS_TTS_MODEL: str = Field(default="facebook/mms-tts-eng")
    MMS_TTS_LANG: str = Field(default="eng")

    FIRESTORE_PROJECT_ID: Optional[str] = None
    FIRESTORE_DATABASE: str = Field(default="(default)")
    FIRESTORE_EMULATOR_HOST: Optional[str] = None
    GOOGLE_APPLICATION_CREDENTIALS: Optional[str] = None
    GOOGLE_APPLICATION_CREDENTIALS_JSON: Optional[str] = None
    GOOGLE_CLOUD_PROJECT: Optional[str] = None

    PEXELS_API_KEY: Optional[str] = None
    PIXABAY_API_KEY: Optional[str] = None
    NASA_API_KEY: Optional[str] = Field(default="DEMO_KEY")

    MAX_RENDER_RESOLUTION: int = Field(default=1280)

    # Feature flags.
    ENABLE_FOOTAGE_CORPUS: bool = Field(default=True)
    ENABLE_REFERENCE_VIDEO: bool = Field(default=False)
    DATA_RETENTION_HOURS: int = Field(default=24)
    CORPUS_RETENTION_HOURS: int = Field(default=168)
    ENABLE_MOVIEPY_FALLBACK: bool = Field(default=False)
    ENABLE_SELF_REVIEW: bool = Field(default=True)
    ENABLE_RAG: bool = Field(default=True)

    ENABLE_DIRECTOR: bool = Field(default=True)
    ENABLE_EDITOR: bool = Field(default=True)
    ENABLE_AMBIENT_BED: bool = Field(default=True)

    # Text overlay engine. "drawtext" is the always-available default;
    # "hyperframes" is opt-in and additionally gated by free RAM at render time.
    TEXT_OVERLAY_ENGINE: str = Field(default="drawtext")
    HYPERFRAMES_BIN: str = Field(default="npx hyperframes")
    HYPERFRAMES_CAP_SECONDS: int = Field(default=5)
    HYPERFRAMES_CHROME_ARGS: str = Field(
        default="--no-sandbox --disable-dev-shm-usage --single-process"
    )
    ENABLE_CAPTIONS: bool = Field(default=False)

    PEXELS_MAX_REQUESTS_PER_HOUR: int = Field(default=180)
    CANCEL_CHECK_INTERVAL: int = Field(default=5)
    # Wall-clock budget (seconds) for the B-roll resolution loop inside the
    # storyboard composer. When exhausted, remaining shots fall back to matte
    # instead of letting slow/failing stock providers stall the whole job.
    FOOTAGE_BUDGET_SECONDS: int = Field(default=360)

    PER_JOB_COST_CAP_CENTS: int = Field(default=50)
    LLM_CACHE_TTL_DAYS: int = Field(default=7)
    DEFAULT_OUTPUT_PROFILES: str = Field(default="youtube_landscape")

    # ---- Paths (and no dead vars) ------------------------------------------
    # tmp is now solely resolved through CHRONOCUT_TMP_DIR (see storage service)
    CHRONOCUT_TMP_DIR: str = Field(default="")

    # ---- API-only backend (static frontend elsewhere) -----------------------
    # The FastAPI process serves no frontend anymore; CORS is restricted to the
    # known frontend origins instead of "*".
    CORS_ORIGINS: str = Field(default="http://localhost:5173,http://localhost:4173")
    APP_BASE_URL: str = Field(default="")
    KEEP_WARM: str = Field(default="")
    MAX_ACTIVE_JOBS: int = Field(default=3)

    # ---- Render dispatch ----------------------------------------------------
    # local: in-process/child-process runner (development)
    # actions: dispatch an external render worker via repository_dispatch
    # modal: Modal function (deployed via the Modal app; requires an account)
    CHRONOCUT_DISABLE_RUNNER: bool = Field(default=False)
    RENDER_DISPATCHER: str = Field(default="local")
    MODAL_ENABLED: bool = Field(default=False)
    GH_DISPATCH_TOKEN: Optional[str] = None
    GH_REPO: Optional[str] = None

    # ---- Output storage for the render worker --------------------------------
    STORAGE_BACKEND: str = Field(default="local")  # local | supabase | github_release
    SUPABASE_URL: Optional[str] = None
    SUPABASE_SERVICE_KEY: Optional[str] = None
    GH_RELEASE_TAG_PREFIX: str = Field(default="chronocut-render")

    # ---- Generated B-roll stills (optional, default off) --------------------
    # META on the Model API: muse-image-1.0 via the OpenAI-compatible Images
    # endpoint at META_BASE_URL ($0.01 per image, billed against free credits).
    IMAGE_GEN_PROVIDER: str = Field(default="off")  # off | muse
    # Optional text failover: when the primary hosted Meta provider errors, the
    # same call is retried through the failover chain (OpenRouter, then Baseten,
    # then local — every slot serves a Meta Muse model; Llama is never used).
    # The switch below gates the whole chain; slots without credentials are
    # skipped at runtime.
    ENABLE_LLM_FAILOVER: bool = Field(default=True)
    # Failover chain order after the configured primary. Valid entries:
    # openrouter, baseten, local.
    LLM_FALLBACK_PROVIDERS: str = Field(default="openrouter")
    IMAGE_GEN_MAX_PER_JOB: int = Field(default=6)
    IMAGE_GEN_DAILY_IMAGES: int = Field(default=60)  # controlled spend from free credits

    # Load backend/.env first, then the repo-root .env; later files win
    # conflicts, so the root .env (the one actually maintained/edited) overrides
    # any stale backend-local copy. uvicorn runs from backend/, where a bare
    # ".env" would otherwise never see the root credentials.
    model_config = SettingsConfigDict(
        env_file=(".env", _REPO_ROOT_ENV),
        extra="ignore",
    )

    @property
    def provider_api_key(self) -> Optional[str]:
        """One key for the configured provider; MODEL_API_KEY wins over the alias."""
        return self.MODEL_API_KEY or self.META_API_KEY

    @property
    def model_badge(self) -> Tuple[str, str]:
        """(provider, model) actually in use — shown in telemetry rows and docs."""
        provider = (self.LLM_PROVIDER or "").strip().lower()
        return llm_badge_for(provider, self)

    @property
    def llm_fallback_providers(self) -> List[str]:
        """Ordered failover slots after the configured primary provider."""
        out = []
        for p in (self.LLM_FALLBACK_PROVIDERS or "").split(","):
            p = p.strip().lower()
            if p:
                out.append(p)
        return out

    @property
    def llm_any_provider_ready(self) -> bool:
        """True when the primary provider or any failover slot has credentials
        (``LLM_PROVIDER=local`` counts — it is keyless by design)."""
        if (self.LLM_PROVIDER or "").strip().lower() == "local":
            return True
        return any(
            bool((getattr(self, k) or "").strip())
            for k in (
                "MODEL_API_KEY", "META_API_KEY", "BASETEN_API_KEY",
                "OPENROUTER_API_KEY",
            )
        )

    @property
    def output_profiles(self) -> List[str]:
        return [p.strip() for p in self.DEFAULT_OUTPUT_PROFILES.split(",") if p.strip()]

    @property
    def meta_text_fallback_models(self) -> List[str]:
        out = []
        for m in (self.META_TEXT_FALLBACK_MODELS or "").split(","):
            m = m.strip()
            if m:
                out.append(m)
        return out

    @property
    def cors_origin_list(self) -> List[str]:
        return [o.strip() for o in (self.CORS_ORIGINS or "").split(",") if o.strip()]

    @property
    def image_gen_provider(self) -> str:
        p = (self.IMAGE_GEN_PROVIDER or "off").strip().lower()
        return p if p in ("off", "muse") else "off"

    @property
    def render_dispatcher(self) -> str:
        d = (self.RENDER_DISPATCHER or "").strip().lower()
        if d in ("local", "actions", "modal"):
            return d
        return "actions" if (self.MODAL_ENABLED is False and (self.GH_REPO or self.GH_DISPATCH_TOKEN)) else "local"

    @property
    def text_overlay_engine(self) -> str:
        e = (self.TEXT_OVERLAY_ENGINE or "drawtext").strip().lower()
        return e if e in ("drawtext", "hyperframes") else "drawtext"

    @property
    def overlay_engine_is_hyperframes(self) -> bool:
        return self.text_overlay_engine == "hyperframes"


settings = Settings()
