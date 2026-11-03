# ChronoCut

Autonomous Documentary & Oral History Orchestrator

ChronoCut turns raw interview audio, videos and scattered historical photos into fully scripted, synchronized and rendered mini-documentaries — with every AI decision applied through a versioned, reviewable Edit Decision List (EDL) that you can refine by hand in a browser timeline and re-render.

## Highlights

- **Multi-agent production pipeline** — an archivist, screenwriter, director and editor supervisor cooperate under a deterministic lead orchestrator, each stage crash-safe and resumable.
- **EDL as the single source of truth** — every cut, caption, grade, transition and speed ramp is a validated, versioned operation on a persistent EDL document, never a side effect of an LLM response.
- **Browser timeline studio** — real clip blocks with waveform/thumbnail previews, box-select and multi-select, edge-drag trims, snapping, ripple deletes, undo history, live playhead transport and an inspector, all editing the server EDL with optimistic local mirroring. Below 1024 px the same page is a read-only review surface.
- **Any file in** — audio, photos and video go to their pipeline stages; any other file (notes, script, subtitle, PDF, export) is read as text and folded into the director's brief, so a written brief can drive the cut.
- **Conversational edit agent** — a chat-driven planner maps natural-language requests ("cut the pauses", "make it feel warmer") onto the same structured operation vocabulary as the UI.
- **Live telemetry** — job progress, agent activity and EDL revisions stream to the frontend over Server-Sent Events.
- **Free-tier first** — every external provider has a deterministic or graceful fallback; the whole product runs with zero paid APIs.

## Architecture

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
   ┌──────────┐ ┌─────────────┐ ┌─────────┐ ┌──────────────┐
   │Archivist │ │ Screenwriter│ │ Director│ │Editor Supervisor│
   │transcribe│ │ 3 script    │ │ edit-   │ │refine the    │
   │ingest,   │ │ modes       │ │ decision│ │composed shots│
   │tag media │ │ (A/B/C)     │ │ list    │ │(drop/regrade)│
   └──────────┘ └─────────────┘ └─────────┘ └──────────────┘
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
                │ agent, re-render │     │ social/space wires │
                └──────────────────┘     └───────────────────┘
                          │
                          ▼
              Memory store (RAG recall + budget ledger)
```

### The production pipeline

1. **Ingest & capability discovery** — the orchestrator probes assigned providers and reports available tools before any media work begins.
2. **Archivist** — transcribes audio, ingests video, tags photos, and analyzes filler words for later cutting.
3. **Screenwriter** — builds the narration script in any of three modes: from your media, from a prompt-only brief, or by analyzing a reference video, with a narrative-arc specialist shaping structure and RAG recall of past successful scripts informing tone.
4. **Director** — when a language model is available it proposes an edit-decision plan (shot choices, grades, motions, transitions); a deterministic storyboard composer then applies the plan over its guaranteed fallback mapping, with strict allow-lists so a malformed plan can never inject invalid values.
5. **Editor supervisor** — a second LLM pass refines the composed shots (drop weak ones, regrade, re-transition) while all actual cutting stays in the render tool path.
6. **Render** — narration is synthesized per shot, then the EDL revision is persisted and the video is rendered into multiple format profiles with crossfade transitions, music/sfx mixing and whichever overlay engine is safe for the host's memory.
7. **Quality gate** — a self-review agent checks the output against the declared duration and media coverage and can mark the job `NEEDS_REVIEW`; a budget governor reports spend against the free-tier cap.

Each stage also records a specialist decision in a per-job agent context document (archivist transcription map, screenwriter beats, director b-roll/coverage, editor pass, render framing/QA). Later stages and the timeline agent read that context instead of re-deriving it, and every specialist call appears in the telemetry feed under its parent agent.

Framing is per export profile: a 16:9 cut rendered to 9:16 or 1:1 gets an aspect-correct crop per clip, shifted toward the detected subject when a vision provider is available and centred otherwise. Video clips additionally get a whole-clip summary through the provider's Files API before the storyboard is composed.

## The EDL contract

The EDL is a versioned JSON document with fixed track order (`v1` video, `c1` captions, `a1` narration, `m1` music, `s1` sfx) and a bounded operation vocabulary:

`split` · `split_every` · `trim` · `delete` · `move` · `set_effect` · `set_grade_all` · `set_motion_all` · `set_transition_all` · `set_speed` · `add_caption` · `update_caption` · `replace_music` · `ensure_captions` · `remove_silence` · `set_profile`

Every write goes through validation, bumping a revision number and keeping a full revision history so the frontend can diff, pulse changed clips and revert. Past the final render an OpenTimelineIO JSON export is written alongside the video for interchange with other editors.

## Project layout

```
backend/
  app/
    agents/            orchestrator + domain agents and sub-agents
    api/               timeline/EDL/render and agent-command routers
    edl/               schema, operations, store, storyboard bridge, compiler
    services/          state store, render records, storage, cleanup, RAG
    tools/
      audio/           transcription, TTS, silence detection
      footage/         tiered visual resolution (corpus → stock → matte)
      llm/             provider abstraction, caching, scoring, governor
      render/          profiles, compiler, ffmpeg assembler
      storyboard/      shot composer
    workers/           render worker entrypoints
  tests/               unit tests (pytest)

frontend/
  src/
    pages/             landing page, intake studio, timeline workspace
    components/        marketing surfaces + timeline workspace parts
    studio/            shared job-state context
    timeline/          time scale, commands, history, snapping, controllers
    hooks/             data hooks: jobs, agent, timeline, shortcuts
    lib/               API client, EDL helpers
```

## Quick start

### Prerequisites

- Python 3.11+ and FFmpeg on the backend host (`ffmpeg` / `ffprobe` on PATH)
- Node.js 18+ for the frontend
- Optional: a language-model API key (the first-party Meta Model API at `api.meta.ai`, or an OpenAI-compatible endpoint serving a Meta open-weight model such as Muse Spark Open via `LLM_PROVIDER=local`). Pexels key for stock footage.

### Backend

```bash
cd backend
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env               # then edit .env
uvicorn app.main:app --reload --port 8000
```

Without any API keys the backend still boots and runs the full pipeline deterministically (graceful fallbacks everywhere). With no Firestore configured it persists state transparently to a local JSON store.

### Frontend

```bash
cd frontend
npm install
npm run dev        # http://localhost:5173
```

The frontend talks to `http://localhost:8000` by default (override with `VITE_API_BASE_URL`).

### Tests

```bash
# backend (pytest; install the test extras first)
cd backend && pip install -r requirements-dev.txt && python -m pytest

# frontend (vitest: timeline math, commands, history, snapping, agent bridge,
# telemetry, EDL helpers)
cd frontend && npm test
```

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
| GET | `/api/v1/jobs/{job_id}/assets/{asset_id}/thumb` | Cached 320 px thumbnail (FFmpeg, generated once) |
| GET | `/api/v1/jobs/{job_id}/waveform?asset_id=` | Cached waveform PNG for an audio source |
| GET | `/api/v1/jobs/{job_id}/ledger` | Budget/cost ledger |
| GET | `/api/v1/jobs/{job_id}/review` | Self-review report |
| GET | `/api/v1/jobs/{job_id}/edl` | Current EDL document |
| PUT | `/api/v1/jobs/{job_id}/edl` | Replace the EDL draft (validated) |
| POST | `/api/v1/jobs/{job_id}/edl/operations` | Apply a batch of structured ops |
| POST | `/api/v1/jobs/{job_id}/timeline/command` | Apply exactly one validated op (keyboard fast path) |
| GET | `/api/v1/jobs/{job_id}/edl/silence` | Silence ranges for the `remove_silence` recipe |
| GET | `/api/v1/jobs/{job_id}/edl/revisions[/{rev}]` | Revision history |
| GET | `/api/v1/jobs/{job_id}/edl.otio` | OpenTimelineIO export |
| POST | `/api/v1/jobs/{job_id}/render` | Queue preview_480 or final render of a revision |
| GET | `/api/v1/jobs/{job_id}/renders` / …/{render_id}[/video] | Render records and output |
| POST | `/api/v1/jobs/{job_id}/agent` | Chat-apply an NL edit as one validated op batch |
| GET | `/api/v1/jobs/{job_id}/agent/activity` | Cold-load agent activity replay |

## Models in use

Every runtime model in ChronoCut is a Meta model — the hosted Muse family plus Meta's open-weight releases — and every generation call goes through one provider layer. Each agent-activity row in the telemetry feed carries the provider and model that produced it (for example `meta · muse-spark-1.3`, or `local · <LOCAL_LLM_MODEL>` when `LLM_PROVIDER=local`), so the model actually answering is never a guess.

**Which Meta models run where:**

- **`muse-spark-1.3`** (with `muse-spark-1.2` / `muse-spark-1.1` as in-family fallbacks) — script, direction, edit decisions, vision tagging. Runs on the first-party **Meta Model API** (`api.meta.ai`).
- **`muse-voice-transcribe-1.0`** — speech-to-text for uploaded footage. Runs on the first-party **Meta Model API**.
- **`muse-image-1.0`** — optional generated B-roll stills. Runs on the first-party **Meta Model API** (Images endpoint), off by default.
- **`sam-3.1`** — optional media segmentation. Runs on the first-party **Meta Model API**.
- **Meta MMS-TTS** (`facebook/mms-tts-eng`) — narration. Open weights, runs **locally**.
- **`muse-spark-open`** (open weights) — the failover host for hosted slots: **Baseten**, **OpenRouter** (every slot serves Meta Muse-family models; Llama is not used). Runs on your own `LLM_PROVIDER=local` endpoint or via OpenRouter.
- **`meta-models/Muse-Glimmer-30B`** (open weights, Apache 2.0) — optional `LLM_PROVIDER=local` slot, self-hosted on consumer hardware.

| Role | Default model | Where it shows up |
|------|---------------|-------------------|
| Script, direction, edit decisions, vision tagging | `muse-spark-1.3` via `META_BASE_URL` — the first-party Meta Model API | `provider` / `model` on each telemetry row |
| Speech-to-text | Muse Voice Transcribe, chunked to 10-minute requests | Archivist telemetry rows |
| Generated B-roll stills | `muse-image-1.0` on the Model API Images endpoint, per-beat, optional, off by default | `scene_caster` telemetry rows |
| Narration | Meta MMS-TTS open weights (`facebook/mms-tts-eng`), local | Narrator agent rows |
| Hosted failover | one chain of Meta-model slots: OpenRouter → Baseten (`muse-spark-open` open weights / mirrored first-party Muse), tried in that order when the primary provider errors | Same rows, `provider` names the slot that answered |
| Fallback text provider | None beyond the failover chain — deterministic templates when no slot is configured | Same rows, `provider: meta`/`openrouter`/`baseten`/`local` |

## Output profiles

`preview_480` heads timeline previews. Final profiles: `youtube_landscape`, `youtube_1080`, `youtube_4k`, `youtube_portrait`, `instagram_portrait`, `instagram_square`, `shorts`, `reels`, `tiktok`, `square`, `square_1080`, `twitter_landscape`, `linkedin`, `cinematic`. A `MAX_RENDER_RESOLUTION` ceiling clamps the tallest profiles on memory-constrained hosts.

## Configuration

Key environment variables (see `backend/.env.example` for the full set):

| Variable | Purpose |
|----------|---------|
| `LLM_PROVIDER` | `meta` (default, first-party Meta Model API) or `local` (OpenAI-compatible endpoint serving a Meta open-weight model) |
| `MODEL_API_KEY` / `META_API_KEY` | Meta Model API key (get one at https://dev.meta.ai) |
| `META_BASE_URL` | `https://api.meta.ai/v1` (first-party Meta Model API; Baseten endpoint on request) |
| `META_TEXT_MODEL` | `muse-spark-1.3` |
| `BASETEN_API_KEY` / `BASETEN_BASE_URL` / `BASETEN_MODEL` | Baseten-hosted Muse Spark Open slot (own key; used as a failover hop, or primary via `LLM_PROVIDER=baseten`) |
| `OPENROUTER_API_KEY` / `OPENROUTER_TEXT_MODEL` | OpenRouter-hosted Muse slot (at provider rates; failover hop). Get a key at https://openrouter.ai/keys |
| `LLM_FALLBACK_PROVIDERS` | Failover chain order after the primary (default `openrouter`) |
| `ENABLE_LLM_FAILOVER` | Master switch for the automatic failover chain (default `true`) |
| `LOCAL_LLM_BASE_URL` | `http://localhost:11434/v1` |
| `LOCAL_LLM_MODEL` | `meta-models/Muse-Glimmer-30B` (open weights, local server) |
| `IMAGE_GEN_PROVIDER` | `off` (default) or `muse` — first-party Muse Image B-roll stills |
| `TTS_PROVIDER` | `mms` (Meta MMS-TTS open weights) |
| `MMS_TTS_LANG` | `eng` |
| `FIRESTORE_PROJECT_ID` | Enables Firestore persistence; plain JSON file otherwise |
| `PEXELS_API_KEY` / `PIXABAY_API_KEY` | Stock footage tiers |
| `DEFAULT_OUTPUT_PROFILES` | Comma-separated render profiles (default `youtube_landscape`) |
| `RENDER_DISPATCHER` | `local` in-process, `actions` GitHub Actions worker, `modal` Modal app |
| `STORAGE_BACKEND` | Render output store: `local`, `supabase`, `github_release` |
| `TEXT_OVERLAY_ENGINE` | `drawtext` (default) or `hyperframes` (opt-in, RAM-gated) |
| `MAX_RENDER_RESOLUTION` | Height ceiling in px (default 720) |
| `MAX_ACTIVE_JOBS` | Worker concurrency cap |

State is stored in Firestore when configured, with an automatic local-JSON fallback so a fresh clone works with zero external accounts. Transcripts, EDL revisions and render records all carry retention-aware cleanup so free-tier quotas are respected.

## Memory-aware rendering

The render path continuously guards its memory use: it logs available RAM before the heaviest stage, degrades the overlay engine and TTS batching when memory is tight, pads audio to match video, and deletes narration scratch right after render. On hosts where even this is too tight, render dispatchers can offload the whole pass to an external worker (`actions` or `modal`) that uploads the finished video through the configured storage backend.

## Deploying

Three independent pieces, all free-tier friendly:

1. **API (one web service).** Build the `backend/` image (`backend/Dockerfile`) and run it with a health check on `/health`. It never serves the frontend. Required variables: `LLM_PROVIDER`, `MODEL_API_KEY` (Meta Model API key; omit entirely for a keyless `LLM_PROVIDER=local` setup), `CORS_ORIGINS` (the static site origin), `APP_BASE_URL` (its own public URL, used by the keep-warm self-ping) or `KEEP_WARM=off`, and optionally `FIRESTORE_PROJECT_ID` plus credentials. Without Firestore it persists to a local JSON store, which is fine for a demo but not durable across restarts. The optional failover chain (`BASETEN_API_KEY`, `OPENROUTER_API_KEY`) retries a failed hosted call through the next configured Meta Muse-model slot before degrading to deterministic templates.
2. **Frontend (static build).** `cd frontend && npm ci && npm run build`, publish `dist/`. Set `VITE_API_BASE_URL` to the API origin at build time. `frontend/public/_redirects` already provides the SPA fallback so deep links such as `/studio/<id>/timeline` load; most static hosts honour it (or configure the equivalent rewrite).
3. **Render worker (GitHub Actions).** Set `RENDER_DISPATCHER=actions`, `GH_REPO`, and a fine-grained `GH_DISPATCH_TOKEN` with `actions:write` on the API, and add the repository secrets `FIRESTORE_PROJECT_ID`, `GOOGLE_APPLICATION_CREDENTIALS_JSON` (and `SUPABASE_URL` / `SUPABASE_SERVICE_KEY` when `STORAGE_BACKEND=supabase`). The API then dispatches `chronocut-render` to `.github/workflows/render-worker.yml`, which renders on the GitHub-hosted runner and writes the finished file through the configured storage backend. If the dispatch is unavailable the API falls back to an in-process render, so a single service can still produce output on a small job.

`.github/workflows/ci.yml` runs backend tests, frontend unit tests and the production build; `keepalive.yml` pings the API every 14 minutes so a free instance does not idle into a cold start.
