"""Backfill the registry/store from pre-existing native run JSONs.

Targets the ``agentbeats.client_cli`` output schema (``{metadata, final_result}``)
— e.g. anything under ``output/**/*.json``. Each payload becomes a run with a
*deterministic* run_id (so re-running backfill is idempotent, never duplicating),
a minimal ``backfilled`` variant inferred from ``metadata.model`` + reasoning, and
a manifest whose provenance is marked ``backfilled`` (the native payload predates
the tracker, so image digests / git SHAs are unknown).
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

from . import ids, ingest, paths, registry, store


def _compact_ts_from_iso(value: str | None) -> str:
    if not value:
        return "00000000T000000Z"
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return dt.strftime("%Y%m%dT%H%M%SZ")
    except ValueError:
        return "00000000T000000Z"


def _looks_native(payload: dict[str, Any]) -> bool:
    fr = payload.get("final_result")
    return isinstance(fr, dict) and isinstance(fr.get("detailed_results_by_split"), dict)


def backfill_file(path: Path) -> str | None:
    """Ingest one native JSON. Returns the run_id, or None if not native format."""
    payload = ingest.load_payload(path)
    if not _looks_native(payload):
        return None

    md = payload.get("metadata", {}) or {}
    cfg = md.get("config", {}) or {}
    model = md.get("model") or "unknown-model"
    reasoning = md.get("reasoning_effort")
    variant_id = ids.slug(f"backfill-{model}" + (f"-{reasoning}" if reasoning else ""))

    identity = {
        "image_digest": None,
        "agent_llm": model,
        "agent_thinking": None,
        "agent_reasoning_effort": reasoning,
        "agent_interleaved_thinking": None,
        "agent_temperature": None,
        "system_prompt_sha256": None,
        "scaffold_kind": "backfilled",
        "harness_git_sha": None,
    }
    created_iso = md.get("started_at") or md.get("completed_at")
    variant_ref = registry.upsert_variant_version(
        variant_id=variant_id, identity=identity,
        created_at=created_iso or "1970-01-01T00:00:00+00:00",
        extra={"scaffold_kind": "backfilled", "source_dir": "backfill", "lifecycle": "validated"},
    )
    vid, _ = ids.split_variant_ref(variant_ref)

    cfg_hash = ids.config_hash(cfg)
    rand4 = ids.sha256_hex(str(path.resolve()))[:4]
    run_id = ids.new_run_id(
        timestamp_compact=_compact_ts_from_iso(created_iso),
        variant_id=vid, cfg_hash=cfg_hash, rand4=rand4,
    )

    run_dir = paths.run_dir(run_id)
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "result.json").write_text(json.dumps(payload), encoding="utf-8")

    task_trials = ingest._task_trial_rows(payload, run_id=run_id, variant_ref=variant_ref, variant_id=vid)
    headline = ingest.headline_from_payload(payload, task_trials)
    manifest = {
        "$schema": "../../schemas/run_manifest.schema.json",
        "manifest_version": 1,
        "run_id": run_id,
        "variant_ref": variant_ref,
        "variant_id": vid,
        "status": "completed",
        "created_at": created_iso,
        "started_at": md.get("started_at"),
        "completed_at": md.get("completed_at"),
        "config_hash": cfg_hash,
        "eval": cfg,
        "provenance": {"execution_mode": "backfilled", "dataset_split": cfg.get("task_split"),
                       "source_path": str(path)},
        "agent_metadata": md.get("agent_metadata", {}),
        "result_json_path": "result.json",
        "result_schema_version": md.get("schema_version"),
        "headline": headline,
        "tags": ["backfilled"],
        "hypothesis": None,
        "notes": f"backfilled from {path}",
    }
    registry.write_run_manifest(manifest)
    return run_id


def backfill_paths(roots: list[Path], *, refresh: bool = True) -> list[str]:
    """Backfill every native *.json found under the given files/dirs."""
    paths.ensure_tree()
    files: list[Path] = []
    for root in roots:
        root = Path(root)
        if root.is_dir():
            files.extend(sorted(root.rglob("*.json")))
        elif root.is_file():
            files.append(root)
    run_ids: list[str] = []
    for f in files:
        try:
            rid = backfill_file(f)
        except (json.JSONDecodeError, OSError):
            continue
        if rid:
            run_ids.append(rid)
    if refresh and run_ids:
        store.refresh()
    return run_ids
