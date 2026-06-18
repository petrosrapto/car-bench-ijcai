# 0008 — Checkpoints + one-command submission packaging

- **Status:** Accepted
- **Date:** 2026-06-18

## Context

A CAR-bench submission (docs/submission.md) is exactly: a public GHCR agent image
**pinned by digest**, a `scenario.toml` (official evaluator + agent image/config,
env-var **names** only — no secret values), and a 4-page report with validation
results. This is the same reproducible identity the registry already tracks — a
`variant_ref` is `{image digest + config + env contract}`. We also want to store
agent "checkpoints" after validation in an organized way.

## Decision

- A **checkpoint** is a built, content-addressed agent image recorded against a
  `variant_ref` (GHCR **image digest** = source of truth), stored under
  `experiments/checkpoints/<variant_ref>/` with `build.json` (reproducibility
  build provenance), optional baked `artifacts/` (sha256'd; LFS for binaries), and
  the `validation_run_ids` that justify promotion.
- Variant **lifecycle**: `draft → built → validated → promoted → submitted`.
- CLI verbs: `cbtrack build` (record reproducibility build), `cbtrack publish`
  (record pushed digest), `cbtrack promote` (gate on a completed test/hidden run),
  `cbtrack submission` (emit the digest-pinned `scenario.toml` +
  `reproducibility.md` + auto-generated `validation_table.md` + `manifest.json`).

## Consequences

- The registry is the single source from which a reproducible submission is
  produced with one command; the submitted image/config is exactly the validated
  checkpoint (same digest the dashboard scored).
- The submission `scenario.toml` renders env vars from the variant's declared
  `env_contract` NAMES, guaranteeing no secret values leak.
- If no digest exists yet (not pushed), `reproducibility.md` flags the image as
  unpinned so it is caught before official submission.

## Alternatives considered

- **Hand-assemble the submission TOML/report each time:** error-prone, easy to pin
  the wrong image or leak a key. Rejected.
- **Treat checkpoints as opaque image tags:** loses build provenance and the link
  to validation evidence. Rejected — digest + `build.json` + `validation_run_ids`.
