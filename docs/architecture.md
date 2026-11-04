# Architecture

How ChronoCut is built: four planes, one governed model seam, and a versioned EDL as the contract between them. This page describes the deployed system; the rendered diagrams live in [`docs/diagram/`](docs/diagram) with their Mermaid sources in [`docs/code/`](docs/code). We keep each diagram verified against the source it depicts (the header comment in every `.mmd` names the files it was checked against).

## The four planes

### 1. Client — static SPA (+ any static host)

Vite build: `Landing` (`/`), `Studio` (`/studio`), `Timeline` (`/studio/:jobId/timeline`). All three talk to the API through one client module (`frontend/src/lib/api.js`) over REST and `EventSource` for the SSE streams (`/events`, agent activity). The static host serves `frontend/public/_redirects` as the SPA fallback so deep links load directly.

### 2. API — FastAPI service

One container (Dockerfile in `backend/`, mirrored in `render.yaml`) that:

- owns the public REST surface (see the API table in the README) — jobs, EDL, agent chat, renders, assets, ledger, review;
- persists state (Firestore when configured, a local JSON store otherwise) and matches SSE consumers through an in-process event fan-out;
- runs the **job runner**: one child process per QUEUED job (`MAX_ACTIVE_JOBS` cap), with stale-job reclaim at startup and on a 60 s sweep (both suppressed by `CHRONOCUT_RESUME_STALE_JOBS=0`);
- proxies rendered artifacts — playback requests 307-redirect to the storage backend's public URL, so the API never streams large files itself.

The API deliberately never serves a frontend and (by default) never renders video itself — see the render plane.

### 3. Models — the governed seam

One entrypoint, `tools/llm/call.py:scored_llm_call`, is the only way an agent reaches a model. The flow for every call:

```
cache lookup (key = provider + system + prompt + temp + model + media hashes)
  → rate-limiter acquire (token-bucket, provider budget)
  → budget check (estimated cost against the job's remaining cap)
  → in-flight coalescing (identical concurrent prompts share one request)
  → primary provider (meta: muse-spark-1.3 → 1.2 → 1.1 in-family retry)
  → failover chain: openrouter → baseten → local (configured slots; keyless ones skipped; hops drop json_mode/media)
  → deterministic templates (planner/director owned fallback)
```

Every hop is recorded in the cost ledger with the provider + model that answered, the token estimate and the cost. Governance knobs live in `config.py` (`PER_JOB_COST_CAP_CENTS`, `LLM_CACHE_TTL_DAYS=7`, `ENABLE_LLM_FAILOVER`, `LLM_FALLBACK_PROVIDERS`). Provider slots are classes in `tools/llm/provider.py`: `MetaProvider`, `OpenRouterProvider`, `BasetenProvider`, `LocalOpenWeightProvider` — each an OpenAI-compatible chat client the moment its key exists, never before.

The seam also hosts the non-text capabilities: chunked ASR (`muse-voice-transcribe`, ≤570 s windows against the 600 s cap, 0.5 s overlap, merged turns), video understanding (Files upload when ≤100 MB, keyframe fallback otherwise), and the optional Images-endpoint B-roll (`muse-image-1.0`, per-job 6 / per-day 60 budget, graceful per-beat degradation).

### 4. Render — where the video is actually made

Three dispatch modes, selected by `RENDER_DISPATCHER` (auto-selects `actions` when `GH_REPO`/`GH_DISPATCH_TOKEN` exist):

| Mode | Mechanism | Where it fits |
|---|---|---|
| `local` | In-process ffmpeg pass inside the job's process, memory-clamped | Development, small jobs, fallback when dispatch is unavailable |
| `actions` | `repository_dispatch: chronocut-render` → `.github/workflows/render-worker.yml` spins up, installs backend requirements + ffmpeg, and runs `app.workers.render_worker` with the render document id; the worker fetches the EDL revision from the state store, marks `RENDERING`, renders, runs `quick_render_check` (duration/audio/black-frames), uploads the artifact, and marks `READY` with the public URL | The hosted default — keeps ffmpeg off the API container entirely |
| `modal` | Modal function spawn (`modal_render.py`) | Optional third slot |

Artifacts upload through `STORAGE_BACKEND`: local paths, Supabase Storage (`renders` public bucket, `{jobId}/{renderId}/{profile}.mp4`), or GitHub releases. An OpenTimelineIO JSON export is written alongside the video; the EDL store's `/edl.otio` endpoint exports any revision on demand.

## Data plane

- **State store** (`services/firestore_service.py`): Firestore collections — jobs, events (SSE + replay), ledger, corpus, assets, renders — with a transparent JSON-file fallback for zero-account local runs, retention-aware cleanup (`DATA_RETENTION_HOURS`, `CORPUS_RETENTION_HOURS`), and a hard kill switch (`CHRONOCUT_DISABLE_FIRESTORE=1`).
- **EDL store** (`edl/store.py`): versioned EDL revisions. Every write validates the operation batch (`MAX_OPS=200`, allow-listed op vocabulary, per-field allow-lists for grades/motions/transitions), bumps the revision, and appends to immutable history. The frontend reconciles against `base_revision` and surfaces `409` conflicts instead of silently overwriting.
- **Cost ledger**: per job — every model call (cached or not), image job, and provider hop lands as a row; the self-review and budget stages read it.

## Memory-aware rendering

Rendering is the heaviest thing the product does, so we guard it continuously: log available RAM before the heaviest stages, degrade the caption overlay engine (`TEXT_OVERLAY_ENGINE` — `drawtext` default, `hyperframes` opt-in, gated by free RAM at render time), batch TTS conservatively, pad audio to match video, and delete narration scratch immediately after muxing. The bundled `backend/bin/ffmpeg.exe` keeps Windows runs working without a global install (it is prepended to `PATH` on import; `ffprobe` still needs to be installed). On memory-tight hosts the whole pass moves to the external worker via render dispatch.
