# ChronoCut

Autonomous video-editing orchestrator for interviews, oral history and documentary footage.

ChronoCut turns raw interview audio, videos and scattered photos into fully scripted, synchronized and rendered mini-documentaries. Every AI decision lands in a versioned, reviewable Edit Decision List (EDL) that you refine by hand in a browser timeline and re-render. Each telemetry row in the product names the exact model that produced a given decision, so the automated edit is auditable end to end.

**Live demo:** https://chronocut.pages.dev/ — upload footage, watch the agents work, then edit the cut in the timeline. (Free-tier backend: the first visit may need up to a minute while the instance wakes.)

## Highlights

- **Multi-agent production pipeline** — an archivist, screenwriter, director and editor supervisor cooperate under a deterministic lead orchestrator; each stage is segmented, crash-safe and resumable.
- **EDL as the single source of truth** — every cut, caption, grade, transition, speed ramp and B-roll insert is a validated, versioned operation on a persistent EDL document, never a side effect of a model response.
- **Browser timeline studio** — real clip blocks with waveform/thumbnail previews, a command URI validated on the server, revision history with undo, and a live playhead transport, all editing the server EDL with optimistic local mirroring.
- **Any file in** — audio, photos and video route to their pipeline stages; any other file (notes, script, subtitle, PDF) is read as text and folded into the director's brief.
- **Conversational edit agent** — a chat-driven planner maps natural-language requests ("cut the pauses", "make it feel warmer") onto the same structured operation vocabulary as the UI.
- **Live telemetry** — job progress, agent activity and EDL revisions stream to the frontend over Server-Sent Events.
- **Governed model seam** — one entrypoint wraps every model call with prompt caching, rate limiting, a per-job cost cap, in-flight coalescing and an automatic Meta-model-only failover chain; deterministic templates backstop everything.
- **Free-tier first** — every external provider has a deterministic or graceful fallback; the whole product deploys with no paid API essential.

## Architecture

We document the system in depth (with rendered diagrams) in [`docs/architecture.md`](docs/architecture.md) and [`docs/pipeline.md`](docs/pipeline.md). Short version:

```
        Upload (audio / video / photos / prompt / reference URL)
                          │
                          ▼
     ┌─────────────────────────────────────────────┐
     │            Lead Orchestrator                │
     │      (deterministic, governed states)       │
     └─────────────────────────────────────────────┘
        │            │              │             │
        ▼            ▼              ▼             ▼
   ┌──────────┐ ┌─────────────┐ ┌─────────┐ ┌──────────────────┐
   │Archivist │ │ Screenwriter│ │ Director│ │Editor Supervisor │
   │transcribe│ │ 3 script    │ │ edit-   │ │+ 6 specialist    │
   │ingest,   │ │ modes       │ │ decision│ │sub-agents (rhythm│
   │tag media │ │ (A/B/C)     │ │ list    │ │motion/color/xfade│
   │          │ │             │ │         │ │audio/type)       │
   └──────────┘ └─────────────┘ └─────────┘ └──────────────────┘
                                       │
                                       ▼
                     ┌──────────────────────────────────┐
                     │   EDL revision (versioned store) │
                     │  build → validate → distribute   │
                     └──────────────────────────────────┘
                          │                         │
                          ▼                         ▼
                ┌──────────────────┐     ┌───────────────────┐
                │ Timeline Studio  │     │  Render pipeline   │
                │ browse ops, chat │     │ preview_480 →      │
                │ agent, re-render │     │ social/cinematic   │
                └──────────────────┘     └───────────────────┘
                          │
                          ▼
              State store (Firestore or local JSON, cost ledger, RAG memory)
```

### The production pipeline

1. **Ingest & capability discovery** — the orchestrator probes model providers and reports the available tool registry before any media work begins.
2. **Archivist** — transcribes audio (speech-to-text, chunked for long uploads), ingests video, tags photos with vision calls and analyzes filler words for later cutting.
3. **Screenwriter** — builds the narration script in any of three modes: from your media, from a prompt-only brief, or by analyzing a reference video; a narrative-arc specialist shapes structure and, when enabled, retrieval of past successful scripts informs tone.
4. **Director** — when a model is available it proposes an edit-decision plan (shot choices, grades, motions, transitions); a deterministic storyboard composer applies the plan over its guaranteed fallback mapping with strict allow-lists, so a malformed plan can never inject invalid values. Each shot's visuals resolve through a tiered footage chain (local corpus → stock APIs → free public archives → optional generated stills → deterministic matte).
5. **Editor supervisor** — a second model pass refines the composed shots through six batched specialist sub-agents (rhythmist, motionist, colorist, transitionist, audioist, typographer) under a hard call cap, while all actual cutting stays in the deterministic render path.
6. **Render** — narration is synthesized locally per shot, the EDL revision is persisted, and the video is rendered into the requested format profiles with crossfade transitions and music/SFX mixing through ffmpeg. Render dispatch is in-process, on an external GitHub Actions worker, or on Modal.
7. **Quality gate** — a self-review agent checks the output against the declared duration and media coverage and can mark the job `NEEDS_REVIEW`; a budget governor reports spend against the per-job cap.

Framing is per export profile: a 16:9 cut rendered to 9:16 or 1:1 gets an aspect-correct crop per clip, shifted toward the subject detected by a vision grounding call, and centered when that call is unavailable. Video clips additionally get a whole-clip summary through the model layer before the storyboard is composed.

## The EDL contract

The EDL is a versioned JSON document with fixed track order (`v1` video, `c1` captions, `a1` narration, `m1` music, `s1` sfx) and a bounded operation vocabulary (max 200 ops per batch):

`split` · `split_every` · `trim` · `delete` · `move` · `set_effect` · `set_grade_all` · `set_transition_all` · `set_motion_all` · `set_speed` · `add_caption` · `update_caption` · `replace_music` · `ensure_captions` · `remove_silence` · `set_profile` · `insert_broll`

Every write goes through validation, bumps a revision number and keeps full revision history so the frontend can diff, pulse changed clips and revert. Past the final render, an OpenTimelineIO JSON export is written alongside the video for interchange with other editors.

## Project layout

```
backend/
  app/
    agents/            orchestrator + domain agents and sub-agents
    api/               timeline/EDL/render and agent-command routers
    edl/               schema, operations, store, storyboard bridge, compiler
    services/          state store, render records, storage, cleanup, RAG
    skills/            director skill files (cuts, grade, motion, sound)
    tools/
      audio/           transcription (chunked ASR), TTS, silence detection
      footage/         tiered visual resolution (corpus → stock → matte)
      imagegen/        optional generated B-roll stills
      llm/             provider slots, caching, governance, failover chain
      media/           ingest, reframe, focus crops
      render/          profiles, compiler, ffmpeg assembler, overlays
      vision/          subject-aware reframe (subject box → crop)
      storyboard/      shot composer
    workers/           render worker entrypoints
  bin/                 bundled Windows ffmpeg (auto-prepended to PATH)
  tests/               unit tests (pytest)

frontend/
  src/
    pages/             landing page, intake studio, timeline workspace
    components/        marketing surfaces + timeline workspace parts
    studio/            shared job-state context
    timeline/          time scale, commands, history, snapping, controllers
    hooks/             data hooks: jobs, agent, timeline, shortcuts
    lib/               API client, EDL helpers

docs/                  deep-dive documentation + rendered diagrams
.github/workflows/     CI, keep-warm pinger, external render worker
```

## Quick start

### Prerequisites

- Python 3.11+ and FFmpeg on the backend host. On Windows, a bundled `ffmpeg.exe` under `backend/bin` is picked up automatically as long as the app package is imported through `python -m uvicorn` (we prepend `backend/bin` to `PATH` in `app/__init__.py`). An `ffprobe` on `PATH` is still required for media probing.
- Node.js 18+ for the frontend.
- Optional but recommended: a first-party Meta Model API key (see *Models in use* below). A Pexels key upgrades the stock-footage tier.

### Backend

```bash
cd backend
python -m venv .venv
source .venv/bin/activate            # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env                 # then edit .env
python -m uvicorn app.main:app --reload --port 8000
```

Without any API keys the backend still boots and runs the full pipeline deterministically (graceful fallbacks everywhere). With no Firestore configured it persists state transparently to a local JSON store. Two escape hatches worth knowing on a laptop:

- `CHRONOCUT_RESUME_STALE_JOBS=0` — skips the startup sweep that re-queues stale jobs (useful for demos with a shared local store).
- `CHRONOCUT_DISABLE_FIRESTORE=1` — forces the local JSON store even when a Firestore client is configured (useful when the daily free quota is exhausted).

### Frontend

```bash
cd frontend
npm install
npm run dev        # http://localhost:5173
```

The frontend talks to `http://localhost:8000` by default (override with `VITE_API_BASE_URL`). Routes: `/` (landing), `/studio` (intake), `/studio/:jobId/timeline` (editor).

### Tests

```bash
# backend (pytest; install the test extras first)
cd backend && pip install -r requirements-dev.txt && python -m pytest tests -q

# frontend (vitest: timeline math, commands, history, snapping, agent bridge,
# telemetry, EDL helpers)
cd frontend && npm test
```

CI (`.github/workflows/ci.yml`) byte-compiles every backend module, runs the pytest suite, runs the frontend unit tests and runs the production build.

## API surface

| Method | Path | Description |
|--------|------|-------------|
| GET | `/health` | Liveness + provider capability probe |
| GET | `/api/v1/capabilities` | Live tool/provider registry |
| POST | `/api/v1/jobs` | Create a job (multipart: mode, media files, prompt, profiles, length) |
| GET | `/api/v1/jobs` | Recent jobs |
| GET | `/api/v1/jobs/{job_id}` | Full job state |
| DELETE | `/api/v1/jobs/{job_id}` | Delete job and reusable assets |
| POST | `/api/v1/jobs/{job_id}/cancel` | Cooperative cancellation |
| GET | `/api/v1/jobs/{job_id}/events` | SSE: progress, agent activity, EDL revisions |
| GET | `/api/v1/jobs/{job_id}/video` | Stream the rendered primary video |
| GET | `/api/v1/jobs/{job_id}/assets` | Asset bin: every source with kind, size, availability, thumbnail |
| GET | `/api/v1/jobs/{job_id}/assets/{asset_id}/thumb` | Cached 320 px thumbnail (ffmpeg, generated once) |
| GET | `/api/v1/jobs/{job_id}/waveform?asset_id=` | Cached waveform PNG for an audio source |
| GET | `/api/v1/jobs/{job_id}/ledger` | Budget/cost ledger |
| GET | `/api/v1/jobs/{job_id}/review` | Self-review report |
| GET | `/api/v1/jobs/{job_id}/edl` | Current EDL document |
| PUT | `/api/v1/jobs/{job_id}/edl` | Replace the EDL draft (validated) |
| POST | `/api/v1/jobs/{job_id}/edl/operations` | Apply a batch of structured ops (dry-run supported) |
| POST | `/api/v1/jobs/{job_id}/timeline/command` | Apply exactly one validated op (keyboard fast path) |
| GET | `/api/v1/jobs/{job_id}/edl/silence` | Silence ranges for the `remove_silence` recipe |
| GET | `/api/v1/jobs/{job_id}/edl/revisions[/{rev}]` | Revision history |
| GET | `/api/v1/jobs/{job_id}/edl.otio` | OpenTimelineIO export |
| POST | `/api/v1/jobs/{job_id}/render` | Queue preview_480 or final render of a revision |
| GET | `/api/v1/jobs/{job_id}/renders` / …/{render_id}[/video] | Render records and 307-redirect playback |
| POST | `/api/v1/jobs/{job_id}/agent` | Chat-apply an NL edit as one validated op batch |
| GET | `/api/v1/jobs/{job_id}/agent/activity` | Cold-load agent activity replay |

## Models in use

Every model that runs in the shipped configuration is a Meta model: the hosted Muse family first-party, plus Meta's open-weight releases on the failover slots. There is no other vendor's model in the text, vision, speech, image or narration runtime. Each agent-activity row in the telemetry feed carries the provider and model that produced it (for example `meta · muse-spark-1.3`, or `local · <LOCAL_LLM_MODEL>` when `LLM_PROVIDER=local`), so the model actually answering is never a guess.

**Which Meta models run where:**

- **`muse-spark-1.3`** (with `muse-spark-1.2` / `muse-spark-1.1` as in-family fallbacks) — script writing, narrative arc, vision tagging, the Director's edit decisions, and the Editor agent's revision plans. Runs on the first-party **Meta Model API** (`api.meta.ai`).
- **`muse-voice-transcribe-1.0`** — speech-to-text for uploaded footage, chunked into ≤10-minute multipart windows (570 s against the 600 s request cap). Runs on the first-party **Meta Model API**.
- **`muse-image-1.0`** — optional generated B-roll stills via the Images endpoint when no real footage matches a beat; off by default, capped per job (6) and per day (60 images). Runs on the first-party **Meta Model API**.
- **Subject-aware reframe** — for portrait crops, probed frames get a subject bounding box from muse-spark vision grounding (a center-crop fallback keeps reframing non-blocking). Configured with `sam-3.1` as the segmentation slot (`META_SEGMENT_MODEL`) for a future dedicated segmentation pass; the live path is muse-spark vision.
- **Meta MMS-TTS** (`facebook/mms-tts-eng`) — narration. Open weights, runs **locally**.
- **Muse Spark Open** (open weights) — the automatic failover host for text: `meta/muse-spark-open` via **OpenRouter** and `meta-models/muse-spark-open` via **Baseten** (either can also serve as primary via `LLM_PROVIDER=openrouter` / `baseten`).
- **`meta-models/Muse-Glimmer-30B`** (open weights, Apache 2.0) — a self-hostable `LLM_PROVIDER=local` slot via any OpenAI-compatible server (LM Studio, Ollama, vLLM), proving the whole pipeline runs on open weights without cloud services.

| Role | Default model | Where it runs |
|------|---------------|----------------|
| Script, direction, edit decisions, vision tagging | `muse-spark-1.3` (+ `muse-spark-1.2`/`1.1` retries) | Meta Model API |
| Speech-to-text | `muse-voice-transcribe-1.0`, 570 s windows | Meta Model API |
| Generated B-roll stills (optional) | `muse-image-1.0`, per-beat, off by default | Meta Model API, Images endpoint |
| Narration | Meta MMS-TTS (`facebook/mms-tts-eng`) | Locally (transformers, CPU) |
| Hosted failover | `openrouter` slot by default (`meta/muse-spark-open`); `baseten` and `local` slots join the chain via `LLM_FALLBACK_PROVIDERS` | OpenRouter / Baseten / local |
| Last resort | deterministic templates, planner/director owned | In-process |

Governance (one seam, `tools/llm/call.py`): prompt cache (7-day TTL) → rate limiter → per-job cost cap (`PER_JOB_COST_CAP_CENTS`, default 50¢) → in-flight coalescing → failover chain (`ENABLE_LLM_FAILOVER`, default true) → deterministic templates. Cost metering uses the documented Muse Spark rates ($1.25 / 1M input, $4.25 / 1M output); open-weight local inference costs zero.

## Output profiles

`preview_480` feeds timeline previews. Final profiles: `youtube_landscape`, `youtube_1080`, `youtube_4k`, `instagram_portrait`, `instagram_square`, `shorts`, `reels`, `tiktok`, `square`, `linkedin`, `cinematic` (21:9). `MAX_RENDER_RESOLUTION` (code default 1280; the sample `.env` pins 720) proportionally clamps the longest side to the configured ceiling, and always emits even dimensions for H.264/yuv420p encoders — raise it on a host with headroom to unlock the 1080/4K profiles.

## Configuration

Key environment variables (see `backend/.env.example` for the full annotated set):

| Variable | Purpose |
|----------|---------|
| `LLM_PROVIDER` | `meta` (default, first-party Meta Model API); `openrouter`, `baseten` or `local` to move the primary elsewhere |
| `MODEL_API_KEY` / `META_API_KEY` | Meta Model API key (dev.meta.ai → Model API → API keys; the alias is accepted for older setups) |
| `META_BASE_URL` | `https://api.meta.ai/v1` |
| `META_TEXT_MODEL` / `META_TEXT_FALLBACK_MODELS` | `muse-spark-1.3` / `muse-spark-1.2,muse-spark-1.1` |
| `OPENROUTER_API_KEY` / `OPENROUTER_TEXT_MODEL` | OpenRouter-hosted Muse slot (`meta/muse-spark-open`) |
| `BASETEN_API_KEY` / `BASETEN_BASE_URL` / `BASETEN_MODEL` | Baseten-hosted Muse Spark Open slot (`meta-models/muse-spark-open`) |
| `LLM_FALLBACK_PROVIDERS` | Failover chain order after the primary (default `openrouter`; entries: `openrouter`, `baseten`, `local`) |
| `ENABLE_LLM_FAILOVER` | `false` disables the automatic failover chain entirely (default `true`) |
| `LOCAL_LLM_BASE_URL` / `LOCAL_LLM_MODEL` | Local OpenAI-compatible endpoint (`meta-models/Muse-Glimmer-30B` suggested) |
| `IMAGE_GEN_PROVIDER` | `off` (default) or `muse` — first-party Muse Image B-roll stills |
| `IMAGE_GEN_MAX_PER_JOB` / `IMAGE_GEN_DAILY_IMAGES` | B-roll image budget (default 6 / 60) |
| `TTS_PROVIDER` / `MMS_TTS_MODEL` / `MMS_TTS_LANG` | Meta MMS-TTS narration (`mms` / `facebook/mms-tts-eng` / `eng`) |
| `FIRESTORE_PROJECT_ID` | Enables Firestore persistence; plain JSON store otherwise |
| `PEXELS_API_KEY` / `PIXABAY_API_KEY` | Stock footage tiers |
| `DEFAULT_OUTPUT_PROFILES` | Comma-separated render profiles (default `youtube_landscape`) |
| `RENDER_DISPATCHER` | `local` in-process, `actions` GitHub Actions worker, `modal` Modal app (auto-selects `actions` when `GH_REPO`/`GH_DISPATCH_TOKEN` are set) |
| `STORAGE_BACKEND` | Render output store: `local`, `supabase`, `github_release` |
| `TEXT_OVERLAY_ENGINE` | `drawtext` (default) or `hyperframes` (opt-in, RAM-gated at render time) |
| `MAX_RENDER_RESOLUTION` | Longest-side ceiling in px (code default 1280; sample env 720) |
| `PER_JOB_COST_CAP_CENTS` | Per-job spend cap enforced by the governor (default 50) |
| `MAX_ACTIVE_JOBS` | Worker concurrency cap (default 3) |
| `CHRONOCUT_RESUME_STALE_JOBS` | `0` disables the startup re-queue sweep for stale jobs |
| `CHRONOCUT_DISABLE_FIRESTORE` | `1` forces the local JSON store even when Firestore is configured |
| `CHRONOCUT_TMP_DIR` | Override the working/temp directory root |

State is stored in Firestore when configured, with an automatic local-JSON fallback so a fresh clone works with zero external accounts. Transcripts, EDL revisions and render records all carry retention-aware cleanup so free-tier quotas are respected.

## Memory-aware rendering

The render path continuously guards its memory use: it logs available RAM before the heaviest stage, degrades the overlay engine and TTS batching when memory is tight, pads audio to match video, and deletes narration scratch right after render. Recovery is deliberate: a worker restart re-queues stale jobs (unless `CHRONOCUT_RESUME_STALE_JOBS=0`), and on hosts where even the guarded path is too tight, render dispatchers offload the whole pass to an external worker (`actions` or `modal`) that uploads the finished video through the configured storage backend.

## Deploying

Three independent pieces, all free-tier friendly:

1. **API (one web service).** Build the `backend/` image (`backend/Dockerfile`; `render.yaml` mirrors it for Render) and run it with a health check on `/health`. It never serves the frontend. Required variables: `LLM_PROVIDER`, `MODEL_API_KEY` (omit entirely for a keyless `LLM_PROVIDER=local` setup), `CORS_ORIGINS` (the static site origin), `APP_BASE_URL` (its own public URL, used by the keep-warm self-ping) or `KEEP_WARM=off`, and optionally `FIRESTORE_PROJECT_ID` plus credentials. Without Firestore it persists to a local JSON store, which is fine for a demo but not durable across restarts. The optional failover chain (`OPENROUTER_API_KEY`, `BASETEN_API_KEY`) retries a failed hosted call through the next configured Meta Muse-model slot before degrading to deterministic templates.
2. **Frontend (static build).** `cd frontend && npm ci && npm run build`, publish `dist/`. Set `VITE_API_BASE_URL` to the API origin at build time. `frontend/public/_redirects` already provides the SPA fallback so deep links such as `/studio/<id>/timeline` load; most static hosts honour it (or configure the equivalent rewrite).
3. **Render worker (GitHub Actions).** Set `RENDER_DISPATCHER=actions`, `GH_REPO`, and a fine-grained `GH_DISPATCH_TOKEN` with `actions:write` on the API, and add the repository secrets `FIRESTORE_PROJECT_ID`, `GOOGLE_APPLICATION_CREDENTIALS_JSON` (and `SUPABASE_URL` / `SUPABASE_SERVICE_KEY` when `STORAGE_BACKEND=supabase`). The API then dispatches `chronocut-render` to `.github/workflows/render-worker.yml`, which renders on the GitHub-hosted runner and writes the finished file through the configured storage backend. If the dispatch is unavailable the API falls back to an in-process render, so a single service can still produce output on a small job.

`.github/workflows/ci.yml` runs backend tests, frontend unit tests and the production build. `.github/workflows/keepalive.yml` pings `$KEEPALIVE_URL/health` every 14 minutes (outer cron net; the in-process self-ping carries the precise cadence — set the `KEEPALIVE_URL` repository variable or the workflow no-ops).

## License & attribution

Model badges on every telemetry row (e.g. `meta · muse-spark-1.3`, `openrouter · meta/muse-spark-open`) reflect exactly which model produced each decision — we consider that honest telemetry non-negotiable for an autonomous editor.
