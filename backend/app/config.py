from pydantic_settings import BaseSettings
from pydantic import Field
from typing import Optional, List


class Settings(BaseSettings):
    ENV: str = Field(default="development")
    PORT: int = Field(default=8000)
    HOST: str = Field(default="0.0.0.0")

    GOOGLE_API_KEY: Optional[str] = None
    # Primary model: gemini-3.6-flash. Google's own API 404 recommends upgrading
    # from 3.5/2.0 to 3.6-flash ("latest features and improvements"), and 3.5-flash
    # is frequently rate-limited with 503 "high demand". 3.6-flash satisfies the
    # guide.md rule "gemini 3.5 or higher only" while being far more available.
    GEMINI_MODEL: str = Field(default="gemini-3.6-flash")
    # Configurable model fallback list (B5): real models in the DEPLOYED SDK
    # version. The call wrapper retries every model with backoff, so a transient
    # 503 on one model automatically fails over to the next.
    GEMINI_FALLBACK_MODELS: str = Field(
        default="gemini-3.5-flash,gemini-flash-latest"
    )
    # B3: per-call timeout (seconds) applied to every Gemini request.
    GEMINI_CALL_TIMEOUT: int = Field(default=60)
    # B2: bounded retry attempts for a Gemini call (distinct from model-swap loop).
    GEMINI_MAX_RETRIES: int = Field(default=4)

    FIRESTORE_PROJECT_ID: Optional[str] = None
    FIRESTORE_DATABASE: str = Field(default="(default)")
    FIRESTORE_EMULATOR_HOST: Optional[str] = None
    GOOGLE_APPLICATION_CREDENTIALS: Optional[str] = None
    GOOGLE_APPLICATION_CREDENTIALS_JSON: Optional[str] = None  # R4: inline SA JSON for Render secret files
    GOOGLE_CLOUD_PROJECT: Optional[str] = None

    PEXELS_API_KEY: Optional[str] = None
    PIXABAY_API_KEY: Optional[str] = None
    NASA_API_KEY: Optional[str] = Field(default="DEMO_KEY")
    DISCORD_WEBHOOK_URL: Optional[str] = None

    RENDER_MEMORY_LIMIT_MB: int = Field(default=512)
    MAX_RENDER_RESOLUTION: int = Field(default=720)

    # v2 feature flags.
    # M4 (self-review), M6 (semantic footage corpus) and M9 (RAG) are fully
    # implemented and enabled by default. M6 uses Gemini text embeddings (no
    # heavy CLIP/torch deps). M5 (reference video) remains gated off because its
    # heavy ML deps (whisper/yt-dlp/scenedetect) exceed the free-tier budget.
    ENABLE_FOOTAGE_CORPUS: bool = Field(default=True)
    ENABLE_REFERENCE_VIDEO: bool = Field(default=False)

    # Retention: keep ONLY lightweight metadata in the store; never raw media.
    # Raw media lives on ephemeral disk (/tmp) and is deleted by cleanup.
    DATA_RETENTION_HOURS: int = Field(default=24)      # job/event/ledger metadata TTL
    CORPUS_RETENTION_HOURS: int = Field(default=168)   # RAG + footage corpus (7d)
    ENABLE_MOVIEPY_FALLBACK: bool = Field(default=False)  # off: ffmpeg-only, avoids RAM OOM
    ENABLE_SELF_REVIEW: bool = Field(default=True)
    ENABLE_RAG: bool = Field(default=True)
    ENABLE_PRO_FALLBACK: bool = Field(default=False)

    # v3 feature flags.
    ENABLE_DIRECTOR: bool = Field(default=True)  # F: LLM director (hardcoded map is fallback)
    ENABLE_EDITOR: bool = Field(default=True)  # Editor supervisor: LLM edit pass over storyboard (deterministic fallback)
    ENABLE_AMBIENT_BED: bool = Field(default=True)  # J1: continuous ffmpeg ambient bed
    # N: text overlay engine. "drawtext" is the free, always-available path and
    # the default. "hyperframes" is the opt-in kinetic-typography overlay engine
    # (Apache-2.0, local headless-Chrome, no per-render fee). When set, captions /
    # lower-thirds / intro+end cards are rendered as a transparent WebM overlay and
    # composited over the ffmpeg-cut video. ANY failure (missing Node/Chromium, npx
    # error, render non-zero) falls back to the drawtext path — never breaks the
    # pipeline. Remotion (N5) is intentionally not used; its insights (data-driven,
    # frame-as-function-of-time, word-synced karaoke) are realized via HyperFrames.
    TEXT_OVERLAY_ENGINE: str = Field(default="drawtext")
    # N2: binary used to invoke HyperFrames (must be on PATH / installed at build).
    HYPERFRAMES_BIN: str = Field(default="npx hyperframes")
    # N2: cap any single overlay clip to bound Chromium memory on free tier.
    HYPERFRAMES_CAP_SECONDS: int = Field(default=5)
    # N2: Chrome launch flags injected at render time (root containers on Render /
    # Cloud Run need --no-sandbox; /dev/shm is tiny so --disable-dev-shm-usage is
    # required; --single-process bounds memory on the 512MB free tier). The Docker
    # image wraps the chrome-headless-shell binary so it reads this env on every
    # launch, which is version-independent (no reliance on an undocumented CLI flag).
    HYPERFRAMES_CHROME_ARGS: str = Field(
        default="--no-sandbox --disable-dev-shm-usage --single-process"
    )
    # I2: auto-burn a short caption derived from the narration when the director
    # did not supply an explicit text_overlay. Off by default to avoid clutter.
    ENABLE_CAPTIONS: bool = Field(default=False)
    # C5: Pexels per-hour request budget (auto-resetting guard).
    PEXELS_MAX_REQUESTS_PER_HOUR: int = Field(default=180)
    # Cooperative cancellation (A5): how often long stages re-check the token.
    CANCEL_CHECK_INTERVAL: int = Field(default=5)

    CORPUS_LOCAL_PATH: str = Field(default="/opt/chronocut/corpus")
    PER_JOB_COST_CAP_CENTS: int = Field(default=50)
    LLM_CACHE_TTL_DAYS: int = Field(default=7)
    WHISPER_MODEL: str = Field(default="base")
    DEFAULT_OUTPUT_PROFILES: str = Field(default="youtube_landscape")

    FRONTEND_DIR: str = Field(default="/var/www/html")
    RENDER_FREE_TIER_EXHAUSTED: bool = Field(default=False)

    class Config:
        env_file = ".env"
        extra = "ignore"

    @property
    def output_profiles(self) -> List[str]:
        return [p.strip() for p in self.DEFAULT_OUTPUT_PROFILES.split(",") if p.strip()]

    @property
    def gemini_fallback_models(self) -> List[str]:
        out = []
        for m in self.GEMINI_FALLBACK_MODELS.split(","):
            m = m.strip()
            if m and m != self.GEMINI_MODEL:
                out.append(m)
        return out

    @property
    def text_overlay_engine(self) -> str:
        e = (self.TEXT_OVERLAY_ENGINE or "drawtext").strip().lower()
        return e if e in ("drawtext", "hyperframes") else "drawtext"

    @property
    def overlay_engine_is_hyperframes(self) -> bool:
        return self.text_overlay_engine == "hyperframes"


settings = Settings()
