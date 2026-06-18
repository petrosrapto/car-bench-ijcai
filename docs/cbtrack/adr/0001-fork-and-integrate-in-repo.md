# 0001 — Fork car-bench-ijcai and integrate the tracker in-repo

- **Status:** Accepted
- **Date:** 2026-06-18

## Context

We need an experiment-tracking + visualization layer over the CAR-bench
competition kit. Two structural options: (a) a *sibling wrapper* package that
shells out to the kit and never modifies it, or (b) *fork* the kit and add the
tracker as first-class subpackages inside it. The kit is the thing you build your
agent in — you already edit `src/track_1_agent_under_test/` and build/push agent
images from it — so it is inherently yours to modify. A submission is itself a
config + image built from this repo.

## Decision

Fork `car-bench-ijcai`. Add `src/cbtrack/` (tracker), `api/` (FastAPI), `web/`
(React), `docs/cbtrack/`, and `experiments/` (data tree) inside the fork. Keep
`upstream` as a git remote for future pulls.

## Consequences

- `ingest.py` imports the official `outputs/plot_results.py` extractors directly
  (loaded by path) — no `sys.path`/subprocess hacks, byte-identical numbers.
- We may close the native metadata gap at the source (`client_cli.py`) with light
  additive edits, kept minimal so upstream merges stay clean.
- One repo versions code + experiments + docs together.
- Trade-off: future upstream pulls can conflict; mitigated by namespacing our
  additions (`cbtrack`, `docs/cbtrack/`) and never editing the evaluator (ADR 0002).

## Alternatives considered

- **Sibling wrapper (no fork):** cleaner upstream hygiene, but forces brittle
  cross-package imports and a subprocess boundary for no real benefit, since the
  kit is already participant-owned. Rejected after the fork was confirmed
  acceptable.
