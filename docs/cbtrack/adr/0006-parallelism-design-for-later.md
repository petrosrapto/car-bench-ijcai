# 0006 — Parallelism-ready schema now, orchestrator later

- **Status:** Accepted
- **Date:** 2026-06-18

## Context

The user wants to eventually run experiments in parallel across heterogeneous
agent variants, but not yet. The stock scenarios hard-bind ports 8080/8081, share
one `output/` dir, and use a default docker-compose project name — all of which
collide under concurrency. Shared Gemini quota (user simulator + judge) is another
contention point.

## Decision

Build sequential execution now, but make every run **self-isolating** and bake
parallelism-ready fields into the schema from v1 so the orchestrator adds with
zero migration:

- `scenario_gen.find_free_port_pair()` allocates a free `(evaluator, agent)` pair
  per run (never 8080/8081); ports are recorded in `manifest.provenance.ports`.
- Each run writes to its own `experiments/runs/<run_id>/` (no shared `output/`).
- `registry/runs.jsonl` is append-only (O_APPEND), so concurrent runs never
  contend on a shared mutable file.
- `manifest` carries `status`, `compose_project`, and `ports` from day one.

The future orchestrator = a queue of `RunSpec`s + `ProcessPoolExecutor(N)` + a
separate `max_evaluator_concurrency` semaphore; docker mode adds
`docker compose -p cb_<run_id8>` + per-run output mounts.

## Consequences

- Two sequential runs already prove isolation (distinct ports + run dirs).
- Adding the orchestrator requires no store/schema migration.
- Quota contention is observable (`quota_wait_seconds` is captured) and can be
  throttled later without schema changes.

## Alternatives considered

- **Build the full orchestrator now:** more upfront work before there are many
  variants to run; deferred per the "in the future" requirement.
- **Ignore parallelism until needed:** would force a schema migration later
  (run IDs, output partitioning, append-only registry). Rejected — cheap to design
  in now.
