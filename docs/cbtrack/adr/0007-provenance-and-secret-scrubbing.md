# 0007 — Provenance capture + secret scrubbing

- **Status:** Accepted
- **Date:** 2026-06-18

## Context

Reproducing and fairly comparing runs across heterogeneous variants requires more
than the native metadata. We must record image digests, git SHAs, dataset/
evaluator versions, the scenario hash, and seeds. At the same time, FAIR-Accessible
artifacts on disk must never leak API keys.

## Decision

`provenance.capture()` records, from sources the wrapper controls:
- agent + evaluator **image digests** (`docker inspect` RepoDigests);
- **scenario sha256** of the rendered `scenario.resolved.toml`;
- **dataset version** = `git -C third_party/car-bench rev-parse HEAD` + split;
  evaluator version = its pinned image digest;
- **git SHAs** for the fork (harness + tracker) and the vendored env; a `repo_dirty`
  flag;
- **seeds** = `agent_seed` + the configured user/judge models (the stochastic
  surfaces).

`provenance.scrub_env()` snapshots only an allowlist of `AGENT_*`/`CONFIG_*`/
`CBTRACK_*`/`LOGURU_*`/`CAR_BENCH_*` vars and **redacts** anything matching
`*_API_KEY|*_TOKEN|*_SECRET|*_PASSWORD|*KEY` to `<redacted>` before writing
`env.captured.json`.

## Consequences

- `result.json` (verbatim) + `manifest.json` together fully re-render and re-run a
  scenario.
- No secret values are ever persisted (verification: grep `env.captured.json`).
- Submission env contracts are rendered from declared NAMES, never captured values
  (see ADR 0008).

## Alternatives considered

- **Snapshot the full environment:** simplest but leaks secrets. Rejected.
- **Record nothing beyond native metadata:** non-reproducible, non-comparable.
  Rejected.
