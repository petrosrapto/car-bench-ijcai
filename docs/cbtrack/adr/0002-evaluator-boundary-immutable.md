# 0002 — The evaluator boundary is immutable

- **Status:** Accepted
- **Date:** 2026-06-18

## Context

Forking the kit (ADR 0001) means everything is technically editable. But the
**evaluator** — `src/evaluator/` and the vendored environment
`third_party/car-bench/` — owns scoring, the simulated user, the 57 tools, the 19
policies, and the reward calculation. Official evaluation runs on the
organizer-published evaluator image; participants must not modify or self-host it.
If our local evaluator code drifts from that image, local Pass^3 stops being
comparable to the official score, silently invalidating every experiment we use to
choose a submission.

## Decision

Never modify `src/evaluator/` or `third_party/car-bench/`. The tracker only
*reads* their outputs and *launches* them unmodified. We record the vendored
`car-bench` git SHA as provenance; we never patch it.

## Consequences

- Local results remain a faithful proxy for official scoring.
- Verification step: `git diff upstream/main -- src/evaluator third_party` must be
  empty (PLAN verification §5, runbook §7).
- Any need to change evaluation behavior must be raised upstream, not patched
  locally.

## Alternatives considered

- **Patch the evaluator for richer logging/metrics:** tempting but poisons
  comparability and risks disqualification. Rejected — we capture extra metrics in
  the tracker layer (provenance, store) instead.
