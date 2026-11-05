# Project documentation

Verified, code-backed documentation and Mermaid diagrams. Every node, endpoint, stage
percentage and model id in these pages and diagrams was checked against the source
before writing — nothing is aspirational.

## Reading order

| Document | What it covers |
|---|---|
| [`../README.md`](../README.md) | Product overview, verified model inventory, API surface, config reference |
| [`LOCALSETUP.md`](LOCALSETUP.md) | Run the whole stack on one machine, troubleshooting |
| [`architecture.md`](architecture.md) | The four planes, the governed model seam, render dispatch, data plane |
| [`pipeline.md`](pipeline.md) | A job's full lifecycle stage by stage, with the real telemetry percentages |

## Layout

```
docs/
  code/          Mermaid sources (.mmd) — the editable truth
  diagram/       Rendered PNG exports (generated from code/)
```

## Diagrams

| File | Type | What it covers |
|---|---|---|
| `01-system-architecture` | system architecture | The four planes: static client (Cloudflare Pages in the shipped deployment), FastAPI API service, Meta model layer with the failover slots, GitHub Actions render worker, plus Firestore / Supabase data plane |
| `02-generation-pipeline` | data pipeline | The full job run (`run_job`) with the real telemetry stage percentages (ingest 4–5% → archivist 20–36% → screenwriter 42–53% → director 58–66% → editor 68–92% → review 95–97% → done 100%) |
| `03-agentic-workflow` | agentic workflow | The agent team: orchestrator, archivist children, screenwriter stage, director + storyboard + B-roll sourcing, editor supervisor and its six batched specialists, quality/budget gates — all wired through the governed model seam |
| `04-render-dispatch` | sequence | `POST /render` → Firestore render doc → GitHub `repository_dispatch` → Actions worker → ffmpeg `render_edl` → Supabase upload → `READY` status → 307-redirect playback → OTIO export |
| `05-model-failover` | decision/flow | The Meta-model-only chain: cache → budget → coalesce → `muse-spark-1.3/1.2/1.1` → openrouter → baseten → local Muse Glimmer → deterministic templates, with honest telemetry bookkeeping |

## Rendering the PNGs

No manifests are checked in — install the renderer anywhere (a local folder or globally is equivalent):

```bash
npm install @mermaid-js/mermaid-cli   # local, or: npm i -g @mermaid-js/mermaid-cli
```

Rebuild any diagram after editing its `.mmd` source:

```bash
mmdc -i code/01-system-architecture.mmd -o diagram/01-system-architecture.png -b white -s 2 --size 2400
```

(`-b white` background, `-s 2` two-x scale for crisp text, `--size 2400`
maximum output width/height — raise it if a diagram wraps awkwardly.
The target directory `diagram/` must exist before running the CLI.
The CLI (v12.2.0 at time of writing) downloads its own headless Chromium —
nothing else to configure; re-rendered output should match the checked-in
PNGs because the `.mmd` sources carry the full geometry.)

## Sources

Each `.mmd` file carries a header comment naming the backend files it was
verified against. If a module changes, update the diagram in the same edit
and re-render — the diagram and the code must never drift apart.
