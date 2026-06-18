"""cbtrack — CAR-bench experiment tracking, store, and submission packaging.

A FAIR experiment layer that wraps the in-repo CAR-bench evaluation harness
(``agentbeats.run_scenario`` + ``agentbeats.client_cli``) without touching the
evaluator boundary (``src/evaluator`` / ``third_party/car-bench``).

Layout produced under ``experiments/`` (see ``cbtrack.paths``):

    registry/{variants,runs}.jsonl   append-only indexes (git-tracked)
    variants/<variant_id>/           variant manifests + cards + prompts
    runs/<run_id>/                   per-run manifest + verbatim result.json
    checkpoints/<variant_ref>/       built+validated agent images + provenance
    submissions/<submission_id>/     ready-to-submit scenario.toml + bundle
    store/                           normalized Parquet + carbench.duckdb

See ``docs/cbtrack/`` for the plan, data-model, runbook, and ADRs.
"""

from __future__ import annotations

__all__ = ["__version__"]

__version__ = "0.1.0"
