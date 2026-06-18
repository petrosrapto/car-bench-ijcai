"""The variant + run registry — append-only JSONL indexes plus per-entity dirs.

Design choices (see ADR 0005):
  * ``registry/runs.jsonl`` and ``registry/variants.jsonl`` are append-only, so
    parallel runs never contend on a shared mutable file (O_APPEND writes only).
  * A *variant* is a stable idea (``variant_id``); each immutable configuration is
    a *version* (``variant_ref = variant_id@verhash``). Runs reference a
    ``variant_ref``; the variant evolves independently.
  * Full objects live under ``variants/<id>/variant.json`` and
    ``runs/<run_id>/manifest.json``; the JSONL files are slim, queryable indexes.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Iterable

from . import ids, paths

LIFECYCLE = ("draft", "built", "validated", "promoted", "submitted")


# --- low-level JSONL helpers ---------------------------------------------

def _append_jsonl(path: Path, record: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(record, sort_keys=True, default=str) + "\n")


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    out: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            out.append(json.loads(line))
    return out


def _write_json(path: Path, obj: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, indent=2, sort_keys=True, default=str), encoding="utf-8")


def _read_json(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


# --- variants -------------------------------------------------------------

def variant_manifest_path(variant_id: str) -> Path:
    return paths.variant_dir(variant_id) / "variant.json"


def get_variant(variant_id: str) -> dict[str, Any] | None:
    return _read_json(variant_manifest_path(variant_id))


def get_variant_version(variant_ref: str) -> dict[str, Any] | None:
    variant_id, _ = ids.split_variant_ref(variant_ref)
    manifest = get_variant(variant_id)
    if not manifest:
        return None
    for version in manifest.get("versions", []):
        if version.get("variant_ref") == variant_ref:
            return version
    return None


def upsert_variant_version(
    *,
    variant_id: str,
    identity: dict[str, Any],
    created_at: str,
    extra: dict[str, Any] | None = None,
) -> str:
    """Register (idempotently) a variant version; returns its ``variant_ref``.

    ``identity`` must contain the VARIANT_IDENTITY_KEYS fields. ``extra`` may
    carry build/env_contract/source_dir/lifecycle and any human metadata.
    """
    variant_id = ids.slug(variant_id)
    ref = ids.variant_ref(variant_id, identity)
    manifest = get_variant(variant_id) or {
        "$schema": "../../schemas/variant.schema.json",
        "manifest_version": 1,
        "variant_id": variant_id,
        "versions": [],
    }
    versions = manifest.setdefault("versions", [])
    existing = next((v for v in versions if v.get("variant_ref") == ref), None)
    version_obj = {
        "variant_ref": ref,
        "created_at": created_at,
        "lifecycle": (extra or {}).get("lifecycle", "draft"),
        **identity,
        **(extra or {}),
    }
    if existing is None:
        versions.append(version_obj)
        _index_variant(version_obj, variant_id)
    else:
        # Preserve the earliest created_at + the furthest lifecycle stage.
        version_obj["created_at"] = existing.get("created_at", created_at)
        version_obj["lifecycle"] = _max_lifecycle(
            existing.get("lifecycle", "draft"), version_obj["lifecycle"]
        )
        versions[versions.index(existing)] = version_obj
    _write_json(variant_manifest_path(variant_id), manifest)
    return ref


def set_variant_lifecycle(variant_ref: str, lifecycle: str, **fields: Any) -> None:
    if lifecycle not in LIFECYCLE:
        raise ValueError(f"unknown lifecycle stage: {lifecycle}")
    variant_id, _ = ids.split_variant_ref(variant_ref)
    manifest = get_variant(variant_id)
    if not manifest:
        raise KeyError(f"variant not found: {variant_id}")
    for version in manifest.get("versions", []):
        if version.get("variant_ref") == variant_ref:
            version["lifecycle"] = _max_lifecycle(version.get("lifecycle", "draft"), lifecycle)
            version.update(fields)
            _write_json(variant_manifest_path(variant_id), manifest)
            _index_variant(version, variant_id)
            return
    raise KeyError(f"variant_ref not found: {variant_ref}")


def _max_lifecycle(a: str, b: str) -> str:
    ia = LIFECYCLE.index(a) if a in LIFECYCLE else 0
    ib = LIFECYCLE.index(b) if b in LIFECYCLE else 0
    return LIFECYCLE[max(ia, ib)]


def _index_variant(version: dict[str, Any], variant_id: str) -> None:
    _append_jsonl(paths.variants_index(), {
        "variant_ref": version["variant_ref"],
        "variant_id": variant_id,
        "scaffold_kind": version.get("scaffold_kind"),
        "agent_llm": version.get("agent_llm"),
        "image_digest": version.get("image_digest"),
        "lifecycle": version.get("lifecycle"),
        "created_at": version.get("created_at"),
    })


def list_variant_versions() -> list[dict[str, Any]]:
    """Latest indexed state per variant_ref (last write wins)."""
    by_ref: dict[str, dict[str, Any]] = {}
    for rec in _read_jsonl(paths.variants_index()):
        by_ref[rec["variant_ref"]] = rec
    return list(by_ref.values())


# --- runs -----------------------------------------------------------------

def run_manifest_path(run_id: str) -> Path:
    return paths.run_dir(run_id) / "manifest.json"


def get_run(run_id: str) -> dict[str, Any] | None:
    return _read_json(run_manifest_path(run_id))


def write_run_manifest(manifest: dict[str, Any]) -> Path:
    run_id = manifest["run_id"]
    path = run_manifest_path(run_id)
    _write_json(path, manifest)
    _index_run(manifest)
    return path


def _index_run(manifest: dict[str, Any]) -> None:
    headline = manifest.get("headline", {}) or {}
    pp = headline.get("pass_power_k", {}) or {}
    pa = headline.get("pass_at_k", {}) or {}
    _append_jsonl(paths.runs_index(), {
        "run_id": manifest["run_id"],
        "variant_ref": manifest.get("variant_ref"),
        "variant_id": manifest.get("variant_id"),
        "status": manifest.get("status"),
        "task_split": (manifest.get("eval", {}) or {}).get("task_split"),
        "config_hash": manifest.get("config_hash"),
        "completed_at": manifest.get("completed_at"),
        "pass_power_3": pp.get("Pass^3"),
        "pass_at_3": pa.get("Pass@3"),
        "tags": manifest.get("tags", []),
    })


def list_runs() -> list[dict[str, Any]]:
    """Latest indexed state per run_id (last write wins)."""
    by_id: dict[str, dict[str, Any]] = {}
    for rec in _read_jsonl(paths.runs_index()):
        by_id[rec["run_id"]] = rec
    return list(by_id.values())


def runs_for_variant(variant_ref: str) -> list[dict[str, Any]]:
    return [r for r in list_runs() if r.get("variant_ref") == variant_ref]


def iter_run_manifests() -> Iterable[dict[str, Any]]:
    for rec in list_runs():
        manifest = get_run(rec["run_id"])
        if manifest:
            yield manifest
