# 0003 — Store = DuckDB over Parquet + file registry

- **Status:** Accepted
- **Date:** 2026-06-18

## Context

The native result JSON is deeply nested. The dashboard needs to slice by
`method × split × task_type × subscore × policy × tool × persona`, recompute
Pass^k on arbitrary subsets, and compute bootstrap CIs — over ~254 tasks × 3
trials × N runs. We also want FAIR-portable, local-first storage.

## Decision

Normalize runs into flat tables and persist them three ways: append-only JSONL
indexes (`registry/`), columnar Parquet (`store/*.parquet`), and a single DuckDB
file (`store/carbench.duckdb`) with typed tables + derived views. DuckDB reads
JSONL and writes Parquet natively, so the build needs no pyarrow and no server.

## Consequences

- `GROUP BY` aggregations run in milliseconds in-process (inside the API).
- Parquet stays portable (readable by Polars/pandas/DuckDB); the DuckDB file is
  rebuildable from the registry at any time (`cbtrack refresh`).
- Bootstrap CIs are a one-query pull + a seeded stdlib resample (no numpy dep).
- Data never leaves the machine.
- Trade-off: full-rebuild-on-refresh rather than incremental upsert — simple and
  correct at this scale; revisit if run counts reach 10k+.

## Alternatives considered

- **SQLite:** no native columnar scans or JSON/Parquet IO; forces row-by-row
  Python. Rejected.
- **MLflow / Weights & Biases:** metric-centric trackers with a UI, but trajectory
  replay + per-subscore/policy/tool slicing still need custom work, and W&B
  defaults to cloud storage (a FAIR/privacy concern). Rejected for a local-first
  research workflow; the bespoke store gives full control over the schema.
