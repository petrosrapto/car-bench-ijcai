# cbtrack — CAR-bench experiment tracking & visualization

`cbtrack` is a FAIR experiment layer integrated into this fork of
`car-bench-ijcai`. It wraps the native evaluation harness, persists every run
with full provenance, normalizes results into a queryable store, serves an
interactive dashboard (stats + trajectory replay), and packages reproducible
competition submissions — all without touching the evaluator boundary.

## Documentation index

| Doc | What it covers |
|---|---|
| [PLAN.md](PLAN.md) | The living design doc: architecture, schemas, frontend, parallelism, submission flow, phased build order. |
| [data-model.md](data-model.md) | Canonical reference for the run/variant manifests and the normalized store tables (field names + types). |
| [runbook.md](runbook.md) | How to run, backfill, refresh the store, start the dashboard, build/submit, and verify. |
| [adr/](adr/) | Architecture Decision Records — one per major decision, MADR format. |

## ADRs

| # | Decision |
|---|---|
| [0001](adr/0001-fork-and-integrate-in-repo.md) | Fork `car-bench-ijcai` and integrate the tracker in-repo (vs a sibling wrapper). |
| [0002](adr/0002-evaluator-boundary-immutable.md) | Never modify the evaluator boundary (`src/evaluator/`, `third_party/car-bench/`). |
| [0003](adr/0003-store-duckdb-over-parquet.md) | Store = DuckDB over Parquet + a file registry. |
| [0004](adr/0004-frontend-fastapi-react.md) | Frontend = FastAPI + React. |
| [0005](adr/0005-fair-layout-run-and-variant-identity.md) | FAIR layout + run/variant identity scheme. |
| [0006](adr/0006-parallelism-design-for-later.md) | Parallelism-ready schema now, orchestrator later. |
| [0007](adr/0007-provenance-and-secret-scrubbing.md) | Provenance capture + secret scrubbing. |
| [0008](adr/0008-checkpoints-and-submission-packaging.md) | Checkpoints + one-command submission packaging. |

## TL;DR

```bash
# one-time: install the tracker extra
uv sync --extra tracker            # or: uv pip install duckdb fastapi tomli-w

# run an evaluation and land it in the FAIR registry
cbtrack run --variant my-method --config smoke --agent-llm gemini/gemini-2.5-flash

# (or) ingest pre-existing native results, then (re)build the store
cbtrack backfill output/
cbtrack refresh

# launch the dashboard backend, then the frontend
cbtrack serve                       # FastAPI on :8099
cd web && npm install && npm run dev # React on :5173 (proxies /api -> :8099)
```

See [runbook.md](runbook.md) for the full workflow including build/publish/submission.
