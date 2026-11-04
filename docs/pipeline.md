# Pipeline

The life of a job, in the order and order-of-magnitude the orchestrator actually emits. Every percentage below is a real `_emit()` value in `backend/app/agents/orchestrator.py` (`run_job`) — we document the pipeline with the same numbers the UI shows. The matching visual is `docs/diagram/02-generation-pipeline.png` (source: `docs/code/02-generation-pipeline.mmd`).

## Modes

One endpoint, three modes — chosen at `POST /api/v1/jobs`:

| Mode | What starts the run |
|---|---|
| `from_media` | Uploaded files (audio / video / photos, plus any text-ish files folded into the brief); up to 200 files, 500 MB total |
| `from_prompt` | A written brief only; the footage chain supplies visuals beat by beat |
| `from_reference` | A reference video URL — analyzed first (fetch, scene detection, keyframes) and its structure informs the script (`reference`, 10–15%) |

## Stage by stage

### Intake (4–6%)
The job runner submits the job into a dedicated child process. `ingest` merges the prompt with whatever documents the user dropped into a single brief (4%), then reports mode + whether the model layer is available after a `validate_model` probe (5%). The `CapabilityDiscoveryAgent` snapshot of the tool registry lands at 6% (no model call — it reads the live registry).

### Understand the material (20–38%)
- **Archivist (20–35%)** — `ArchivistAgent.process`: chunked speech-to-text (≤570 s windows; merged turns with speaker/word timing), whole-clip video summaries (Files-API upload when ≤100 MB, probed keyframes otherwise), and vision tagging of photos. A partial failure degrades that modality instead of failing the job (35% as partial failure).
- **Filler analysis (36%)** — `FillerAnalyzerAgent` counts disfluencies with a deterministic regex pass; the later "cut the pauses" edit uses this map.
- **RAG recall (38%, `ENABLE_RAG`)** — retrieval of similar past projects so recurring briefs inherit what worked.

### Write (42–53%)
- **Script (42–52%)** — `tools/script` picks the mode: `script_from_transcript`, `script_from_reference`, or `script_from_prompt`. The output is beat segment with tone/emotion, cached by prompt hash so a re-run reuses it (52% as cache recovery).
- **Narrative arc (53%)** — the `NarrativeArcSpecialist` shapes the three-act outline deterministically from beats.
- **B-roll keywords** — extracted from the script to seed the footage chain.

### Direct the cut (58–66%)
Gated on `ENABLE_DIRECTOR` + model availability + cancellation (checked every few seconds; 66% as cancelled):
- **Storyboard composer (58–64%)** — builds the shot list (shot id, duration per beat, visual source) and resolves each shot's visuals through the tiered footage chain: local media corpus → Pexels → Pixabay → Wikimedia → archive.org → NASA → optional generated stills (`muse-image-1.0`, when `IMAGE_GEN_PROVIDER=muse`) → deterministic matte. A wall-clock budget (`FOOTAGE_BUDGET_SECONDS`) stops slow providers from stalling the job.
- **Director decisions (64%)** — `DirectorAgent` proposes cut/grade/motion/transition/sound choices grounded in the skill files (`backend/app/skills/{cuts,grade,motion,sound}.md`), validated against strict allow-lists; anything invalid falls back to the hardcoded mapping, so the output is either valid or conservative.
- **Storyboard ready (66%)** — a context record pairs the director plan with the casting notes for the editor pass.

### Edit and assemble (68–92%)
- **Editor supervisor (68%)** — `EditorAgent` refines the storyboard (drop weak shots, regrade, retransition) through a static plan application; the actual cutting stays deterministic.
- **Narration (70–72%)** — per-shot TTS with **local Meta MMS-TTS open weights** (`facebook/mms-tts-eng`) and cooperative cancellation. Memory-gated: below 700 MB free we skip local TTS entirely and write the narration text into the EDL for the external render worker to voice; below 1000 MB the batch size drops to 1. Already-synthesized shots are skipped on re-runs (resumability).
- **EDL build (88%)** — `build_edl_from_storyboard` + `save_edl` persist the first revision (source `pipeline`), and `reframe_sources` recomputes focus crops per profile — subject boxes from vision grounding with a center-crop fallback.
- **Caching (92%)** — editor outputs are recovered from cache on unchanged re-runs.

### Render and review (90–100%)
- **Render dispatch (90–91%)** — when Firestore + `GH_REPO` + `GH_DISPATCH_TOKEN` are configured, a render document is created per profile and dispatched externally (`repository_dispatch: chronocut-render` → Actions worker → ffmpeg → upload → `READY`, see `docs/code/04-render-dispatch.mmd`); profiles not covered by the worker are rendered in-process (92%). Without the external setup the whole pass runs locally, memory-clamped.
- **Post-render hygiene** — narration scratch and render tmp are deleted immediately (memory release).
- **Self-review (95–97%, `ENABLE_SELF_REVIEW`)** — frame sampling, audio levels and the duration promise; failures mark the job `NEEDS_REVIEW` rather than failing it.
- **Budget report (98%)** — `BudgetGovernorAgent` closes the ledger against the per-job cap; RAG memory persists the run.
- **Done (100%)** — final status: `COMPLETE`, `NEEDS_REVIEW`, `FAILED`, or `CANCELLED`; the job doc carries the archivist/screenwriter/director/editor outputs and the review report.

## What every stage shares

- **Resumability** — scripts, storyboards and editor outputs are cached by content hash; a crashed worker re-queues the job and skipped stages complete from cache instead of re-billing.
- **Cancellation** — checked cooperatively at every heavy boundary; a cancelled job lands `CANCELLED` at the next check, never mid-ffmpeg.
- **Specialist context** — each stage records per-job agent context (transcription map, script beats, b-roll coverage, editor pass, framing/QA). Later stages and the timeline agent read the context instead of re-deriving it.
- **Honest telemetry** — every model call inside every stage flows through the governed seam, so the UI's agent-activity feed names the provider + model that answered (e.g. `meta · muse-spark-1.3`), the tokens and the cost.

## Failure philosophy

We designed the pipeline so that no single external dependency is load-bearing: stock APIs can fail (matte fallback), the model can be down (deterministic script/direction pairs), ASR can be offline (media still tags, narration still cuts on scene boundaries), and render OTAs can be unavailable (in-process render takes over). The worst realistic state is `NEEDS_REVIEW` with a report explaining what degraded — not a silent garbage video.
