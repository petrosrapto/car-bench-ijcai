"""Canonical filesystem layout for the cbtrack experiment tree.

Everything lives under ``<repo_root>/experiments`` by default. The repo root is
detected by walking up from this file until a ``pyproject.toml`` with the
``car-bench-ijcai`` project is found; it can be overridden with the
``CBTRACK_EXPERIMENTS_DIR`` environment variable (useful for tests).
"""

from __future__ import annotations

import os
from pathlib import Path


def repo_root() -> Path:
    """Return the car-bench-ijcai repo root (the dir containing pyproject.toml)."""
    here = Path(__file__).resolve()
    for parent in here.parents:
        if (parent / "pyproject.toml").exists() and (parent / "src" / "agentbeats").exists():
            return parent
    # Fallback: src/cbtrack/paths.py -> repo root is two levels up from src/.
    return here.parents[2]


def experiments_dir() -> Path:
    override = os.environ.get("CBTRACK_EXPERIMENTS_DIR")
    if override:
        return Path(override).expanduser().resolve()
    return repo_root() / "experiments"


# --- subtrees -------------------------------------------------------------

def registry_dir() -> Path:
    return experiments_dir() / "registry"


def runs_dir() -> Path:
    return experiments_dir() / "runs"


def variants_dir() -> Path:
    return experiments_dir() / "variants"


def checkpoints_dir() -> Path:
    return experiments_dir() / "checkpoints"


def submissions_dir() -> Path:
    return experiments_dir() / "submissions"


def store_dir() -> Path:
    return experiments_dir() / "store"


def schemas_out_dir() -> Path:
    return experiments_dir() / "schemas"


# --- specific files -------------------------------------------------------

def runs_index() -> Path:
    return registry_dir() / "runs.jsonl"


def variants_index() -> Path:
    return registry_dir() / "variants.jsonl"


def duckdb_path() -> Path:
    return store_dir() / "carbench.duckdb"


def run_dir(run_id: str) -> Path:
    return runs_dir() / run_id


def variant_dir(variant_id: str) -> Path:
    return variants_dir() / variant_id


def checkpoint_dir(variant_ref: str) -> Path:
    # variant_ref contains '@'; keep it filesystem-safe.
    return checkpoints_dir() / variant_ref.replace("/", "_")


def submission_dir(submission_id: str) -> Path:
    return submissions_dir() / submission_id


def ensure_tree() -> None:
    """Create the full experiments/ tree (idempotent)."""
    for d in (
        registry_dir(),
        runs_dir(),
        variants_dir(),
        checkpoints_dir(),
        submissions_dir(),
        store_dir(),
        schemas_out_dir(),
    ):
        d.mkdir(parents=True, exist_ok=True)
