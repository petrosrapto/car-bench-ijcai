"""Run + registry listing endpoints."""

from __future__ import annotations

import sys
from pathlib import Path

from fastapi import APIRouter, HTTPException

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))
from cbtrack import registry  # noqa: E402

from .. import deps  # noqa: E402

router = APIRouter(prefix="/api", tags=["runs"])


@router.get("/runs")
def list_runs():
    return registry.list_runs()


@router.get("/runs/{run_id}")
def get_run(run_id: str):
    manifest = registry.get_run(run_id)
    if not manifest:
        raise HTTPException(404, f"run not found: {run_id}")
    return manifest


@router.get("/variants")
def list_variants():
    return registry.list_variant_versions()


@router.get("/variants/{variant_id}")
def get_variant(variant_id: str):
    manifest = registry.get_variant(variant_id)
    if not manifest:
        raise HTTPException(404, f"variant not found: {variant_id}")
    # attach per-version run history for the Trends view
    for version in manifest.get("versions", []):
        version["runs"] = registry.runs_for_variant(version["variant_ref"])
    return manifest
