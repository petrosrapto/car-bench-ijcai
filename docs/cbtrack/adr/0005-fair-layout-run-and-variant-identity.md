# 0005 — FAIR layout + run/variant identity

- **Status:** Accepted
- **Date:** 2026-06-18

## Context

To compare many experiments over time (including heterogeneous agent
implementations) and reproduce any of them, we need stable identities and a
self-describing on-disk layout. The native harness records only model +
reasoning + config — no run ID, no method identity, no provenance.

## Decision

- **`run_id`** = `<UTCts>__<variant_id>__<config_hash8>__<rand4>`; **`config_hash`**
  hashes the evaluation-defining config.
- A **variant** is a stable idea (`variant_id`); each immutable configuration is a
  **version** identified by **`variant_ref = variant_id@ver_hash8`**, where
  `ver_hash` hashes the reproducible identity tuple (image digest, model,
  thinking/reasoning/temperature, system-prompt hash, scaffold kind, harness SHA).
- Runs reference a `variant_ref`; the variant registry is **decoupled from runs**.
- On-disk: `experiments/{registry,variants,runs,checkpoints,submissions,store,
  schemas}` with append-only `registry/{runs,variants}.jsonl` indexes; every
  artifact carries a `$schema` pointer.

## Consequences

- A "method" is a first-class, versioned, reproducible entity that many runs
  reference — enabling "watch a method improve over its run history" (Trends) and
  apples-to-apples Compare.
- A brand-new agent codebase later is just a new `variant_id` with its own
  `scaffold_kind`/`source_dir` — no schema change.
- FAIR: Findable (IDs + indexes), Accessible (open formats on disk),
  Interoperable (`$schema` + Parquet/DuckDB), Reusable (full provenance + verbatim
  `result.json`).

## Alternatives considered

- **Key runs by model string (as the native plots do):** cannot distinguish two
  methods using the same model, nor track a method across iterations. Rejected.
- **Couple variant identity into the run record only:** loses the decoupled,
  versioned method entity. Rejected.
