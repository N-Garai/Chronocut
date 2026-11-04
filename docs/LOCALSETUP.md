# Local setup

Everything we need to run ChronoCut end to end on one machine: the API, the browser studio, and a rendered video. We keep this walkthrough verified against the current code — every command below is the one the tests and CI exercise.

## What you need

| Requirement | Notes |
|---|---|
| Python 3.11+ | `python -m uvicorn app.main:app` is the launch path |
| FFmpeg + ffprobe | The render path shells out by bare name. On Windows, `backend/bin/ffmpeg.exe` is picked up automatically (we prepend that folder to `PATH` in `app/__init__.py`, so the launch must go through Python, not a direct binary call). `ffprobe` still needs to be on `PATH` for media probing. |
| Node.js 18+ | Frontend dev server and build |
| ~4 GB free RAM | Keeps the deterministic pipeline comfortable; the render path self-degrades on tighter hosts |

Optional accounts/keys (everything below degrades gracefully without them):

- Meta Model API key — `MODEL_API_KEY` (dev.meta.ai → Model API). This is the primary model provider.
- Pexels / Pixabay keys — better stock-footage tiers.
- Firestore (`FIRESTORE_PROJECT_ID` + credentials) — durable state; a local JSON store is used otherwise.

## Step 1 — Backend

```bash
cd backend
python -m venv .venv
source .venv/bin/activate            # Windows PowerShell: .venv\Scripts\Activate.ps1
pip install -r requirements.txt
cp .env.example .env                 # Windows: Copy-Item .env.example .env
python -m uvicorn app.main:app --reload --port 8000
```

Check `http://localhost:8000/health` — it probes the configured providers and returns the capability snapshot.

### Editing `.env`

The template ships with safe defaults: `LLM_PROVIDER=meta` and the samples for every slot commented. Minimal useful setups, in the order we recommend trying them:

1. **First-party only.** Set `MODEL_API_KEY=…`. Everything (text, vision, ASR, optional B-roll) runs on `api.meta.ai`.
2. **None.** Delete/blank every key. The pipeline still runs — scripts, edit plans and narration degrade to deterministic templates and local Meta MMS-TTS. Good for a no-network demo.
3. **Fully local.** Set `LLM_PROVIDER=local` and point `LOCAL_LLM_BASE_URL` at any OpenAI-compatible server (LM Studio, Ollama, vLLM) serving `meta-models/Muse-Glimmer-30B`. Keyless by design.
4. **With failover.** Fill `OPENROUTER_API_KEY` (and/or `BASETEN_API_KEY`). If the primary errors mid-job, the call is retried through the configured chain automatically.

Useful local-mode switches (all optional):

| Variable | Effect |
|---|---|
| `CHRONOCUT_RESUME_STALE_JOBS=0` | Skips the startup sweep that re-queues stale jobs — recommended for a demo on a shared local store |
| `CHRONOCUT_DISABLE_FIRESTORE=1` | Forces the local JSON store even with Firestore configured — useful after the daily free quota is gone |
| `CHRONOCUT_TMP_DIR=path` | Redirects the scratch/media root |
| `IMAGE_GEN_PROVIDER=muse` | Turns on generated B-roll stills (budget-capped: 6 per job, 60 per day) |

Note the env-file order: we load `backend/.env` first, then the repo-root `.env`, and later values win — keep the file you actually maintain at the repo root.

## Step 2 — Frontend

```bash
cd frontend
npm install
npm run dev        # http://localhost:5173
```

Routes: `/` (landing), `/studio` (intake), `/studio/:jobId/timeline` (editor). The dev server talks to `http://localhost:8000` by default; set `VITE_API_BASE_URL` when the API lives elsewhere.

## Step 3 — Run a job

1. Open `/studio`, drop media (audio, video, photos — up to 200 files, 500 MB total), or just type a brief for a `from_prompt` run.
2. Watch the progress stream; every agent action appears in the telemetry feed with its provider + model badge.
3. The job lands in the timeline editor at `/studio/<jobId>/timeline`. Chat edits ("tighten the middle, add captions") apply as one validated operation batch per message, with revision history and undo.
4. Queue a preview or final render. In `RENDER_DISPATCHER=local` the API renders in-process (memory-guarded); otherwise it dispatches to the external worker (see `architecture.md`).
5. Download the MP4 — and grab `GET …/edl.otio` for an OpenTimelineIO export if you want to hand the cut to a professional editor.

## Step 4 — Verify the install

```bash
# backend tests (byte-compiles + behavior, mirrors CI)
cd backend && pip install -r requirements-dev.txt && python -m pytest tests -q

# frontend unit tests + production build
cd frontend && npm test && npm run build
```

CI (`.github/workflows/ci.yml`) runs exactly these stages, plus `python -m compileall app`.

## Troubleshooting

| Symptom | Fix |
|---|---|
| `ffmpeg: WinError 2` on Windows | Launch via `python -m uvicorn app.main:app …` (not a direct `uvicorn` console script without the package import) so `backend/bin` is prepended to `PATH`; or install ffmpeg system-wide |
| Job re-runs an old job at startup | Set `CHRONOCUT_RESUME_STALE_JOBS=0` |
| 429 / quota errors crash calls | Set `CHRONOCUT_DISABLE_FIRESTORE=1`, or add a failover slot key (`OPENROUTER_API_KEY`) |
| Tall profiles render tiny | `MAX_RENDER_RESOLUTION` clamps the longest side (code default 1280, sample env 720) — raise it on a host with headroom |
| Port conflicts | `PORT` (API) and the Vite default 5173 are independent; set `VITE_API_BASE_URL` to reconnect them |

Deeper system behavior lives in [`docs/architecture.md`](docs/architecture.md) and [`docs/pipeline.md`](docs/pipeline.md); rendered diagrams are in [`docs/diagram/`](docs/diagram).
