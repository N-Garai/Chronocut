# ChronoCut

Autonomous Documentary & Oral History Orchestrator

A multi-agent system that transforms raw audio interviews and scattered historical photos into fully scripted, synchronized, and rendered mini-documentary videos.

## Architecture

```
                    ┌─────────────────────┐
                    │   FastAPI Backend    │
                    │   (Render / Docker)  │
                    └──────────┬──────────┘
                               │
              ┌────────────────┼────────────────┐
              │                │                │
              ▼                ▼                ▼
     ┌────────────────┐ ┌──────────────┐ ┌──────────────┐
     │  ARCHIVIST     │ │ SCREENWRITER │ │   DIRECTOR   │
     │  (Parallel)    │ │ (Sequential) │ │ (Sequential) │
     │ • Audio trans  │ │ • Filler cut │ │ • Visual     │
     │ • Image tags   │ │ • Script     │ │   matching   │
     └────────────────┘ └──────────────┘ └──────────────┘
                               │
                               ▼
                    ┌─────────────────────┐
                    │      EDITOR          │
                    │  (Deterministic)     │
                    │ • Ken Burns effects  │
                    │ • Audio sync         │
                    │ • FFmpeg render      │
                    └─────────────────────┘
                               │
                               ▼
                    ┌─────────────────────┐
                    │   Google Firestore   │
                    │  (State & Memory)    │
                    └─────────────────────┘
```

## Tech Stack

- **Backend:** FastAPI, Python 3.11
- **Agent Framework:** Google ADK 2.0 (SequentialAgent, ParallelAgent, LlmAgent)
- **AI Model:** Gemini 3.5 Flash
- **Database:** Google Cloud Firestore
- **Media Processing:** FFmpeg, MoviePy
- **Frontend:** React, Vite, TailwindCSS, GSAP, Lenis

## Quick Start

### Prerequisites

- Python 3.10+
- Node.js 18+
- Google AI Studio API key
- Google Cloud project with Firestore enabled
- Pexels API key (optional)

### Backend Setup

```bash
cd backend
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env
```

Configure `.env`:
```env
GOOGLE_API_KEY=your_google_ai_studio_key
FIRESTORE_PROJECT_ID=your_project_id
PEXELS_API_KEY=your_pexels_key
```

Run the backend:
```bash
uvicorn app.main:app --reload --port 8000
```

### Frontend Setup

```bash
cd frontend
npm install
npm run dev
```

## Deploy to Render (Free Tier)

### Step 1: Prepare Your Code

1. Push this repository to GitHub (make sure `.gitignore` is in place)
2. Ensure these files exist:
   - `backend/Dockerfile`
   - `render.yaml`
   - `backend/requirements.txt`

### Step 2: Get Your API Keys

| Key | Where to Get | Purpose |
|-----|-------------|---------|
| `GOOGLE_API_KEY` | [Google AI Studio](https://aistudio.google.com/app/apikey) | Gemini model access |
| `FIRESTORE_PROJECT_ID` | [Google Cloud Console](https://console.cloud.google.com/firestore) | Firestore database ID |
| `GOOGLE_APPLICATION_CREDENTIALS` | Google Cloud IAM → Service Accounts | Firestore authentication |
| `PEXELS_API_KEY` | [Pexels API](https://www.pexels.com/api/) | Stock photo/video search (optional) |

### Step 3: Create Google Cloud Project

1. Go to [Google Cloud Console](https://console.cloud.google.com/)
2. Create a new project (or use existing)
3. Enable **Firestore API**:
   - Navigation → APIs & Services → Library
   - Search "Firestore" → Enable
4. Create Firestore database:
   - Go to Firestore → Create Database
   - Select **Native mode**
   - Choose any region (e.g., `us-central`)
   - Start in **test mode** (no security rules needed for demo)
5. Create a Service Account:
   - IAM & Admin → Service Accounts → Create Service Account
   - Name: `chronocut-service`
   - Grant role: **Cloud Datastore User**
   - Create key → JSON → Save as `service_account.json`
6. (Optional) Set up billing alerts to stay within free tier

### Step 4: Deploy on Render

1. Sign up at [render.com](https://render.com) (free tier available)
2. Click **New +** → **Web Service**
3. Connect your GitHub repository
4. Configure:
   - **Name:** `chronocut-api`
   - **Environment:** `Docker`
   - **Branch:** `main`
   - **Plan:** `Free`
   - **Region:** `Oregon` (or closest to you)
5. Under **Environment Variables**, add:
   ```
   ENV=production
   PORT=8000
   GOOGLE_API_KEY=your_key_here
    GEMINI_MODEL=gemini-3.5-flash
   FIRESTORE_PROJECT_ID=your_project_id
   PEXELS_API_KEY=your_pexels_key (optional)
   RENDER_MEMORY_LIMIT_MB=512
   MAX_RENDER_RESOLUTION=720
   ```
   > **Important:** For `GOOGLE_APPLICATION_CREDENTIALS`, you have two options:
   > - **Option A (Render Secret File):** Upload `service_account.json` as a Render Secret File and set path to `/secrets/service_account.json`
   > - **Option B (Base64):** Base64-encode the JSON and set as env var, decode in code
6. Click **Create Web Service**
7. Wait 3-5 minutes for first deploy
8. Your API will be live at `https://chronocut-api.onrender.com`

### Step 5: Verify Deployment

```bash
curl https://your-app.onrender.com/health
# Expected: {"status":"ok","service":"chronocut-api","env":"production"}
```

### Step 6: Connect Frontend

Update `frontend/vite.config.js` proxy or deploy frontend separately:

```bash
# Option A: Deploy frontend to Vercel/Netlify
cd frontend
npm run build
# Deploy dist/ folder

# Option B: Serve from Render (add to render.yaml)
# Add a second static site service pointing to frontend/dist
```

## API Endpoints

| Method | Path | Description |
|--------|------|-------------|
| GET | `/health` | Health check |
| POST | `/api/v1/jobs` | Create new processing job |
| GET | `/api/v1/jobs/{id}` | Get job status |
| GET | `/api/v1/jobs` | List recent jobs |
| POST | `/api/v1/agents/archivist/run` | Run archivist agent |
| POST | `/api/v1/agents/screenwriter/run` | Run screenwriter agent |
| POST | `/api/v1/agents/director/run` | Run director agent |
| POST | `/api/v1/agents/editor/run` | Run editor agent |

## ADK 2.0 Pipeline

The backend uses proper ADK 2.0 composition:

```
SequentialAgent("ChronoCutPipeline")
  ├── ParallelAgent("ArchivistParallel")
  │     ├── LlmAgent("AudioAnalyst")       → transcript
  │     └── LlmAgent("ImageAnalyst")        → image tags
  ├── LlmAgent("Screenwriter")              → script
  ├── LlmAgent("Director")                  → storyboard
  └── LlmAgent("Editor")                    → final render
```

Each agent has:
- **Structured instructions** defining its role
- **ADK function tools** for external API calls
- **`output_key`** for passing state to downstream agents
- **Proper session management** via `InMemorySessionService`

## Firestore Schema

```
/chronocut_jobs/{job_id}
├─ job_id: string
├─ user_id: string
├─ status: QUEUED | PROCESSING | COMPLETE | FAILED
├─ stage: archivist | screenwriter | director | editor | done
├─ progress_percent: 0-100
├─ created_at: timestamp
├─ updated_at: timestamp
├─ input_files: {audio_files, photo_files}
├─ archivist_output: {transcript, segments, image_tags}
├─ screenwriter_output: {script, total_duration_seconds}
├─ director_output: {storyboard}
├─ editor_output: {output_video_url, changelog}
└─ error_log: {stage, message, timestamp}
```

## Memory Optimization for Render Free Tier

- Docker image includes **1GB swap file** (prevents OOM on 512MB RAM)
- FFmpeg processes clips sequentially
- Resolution capped at 720p by default
- `RENDER_MEMORY_LIMIT_MB` env var controls memory guard

