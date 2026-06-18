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


def import_carbench_baselines(
    set_dirs: list[Path], *, set_label: str = "test", refresh: bool = True
) -> list[str]:
    """Import official car-bench `results/` baselines into the registry.

    The env-repo result format (`analyze_results.py`) is a flat list of per-trial
    records: ``{task_id, reward, trial, info{task, reward_info, total_agent_cost,
    total_llm_induced_latency_ms}, traj}``. This adapter groups every record by
    model (filename prefix) across the given split directories, rebuilds the
    native ``detailed_results_by_split`` shape, synthesizes Pass^k scores, and
    writes one run per model — so the dashboard shows real reference data.

    ``set_dirs`` should be the directories that together form ONE evaluation set
    (e.g. ``results/base_test``, ``results/hallucination_test``,
    ``results/disambiguation_test``).
    """
    paths.ensure_tree()
    # group files by model, remembering each file's split (from its directory)
    by_model: dict[str, list[tuple[Path, str | None]]] = {}
    for d in set_dirs:
        d = Path(d)
        if not d.is_dir():
            continue
        dir_split = _split_from_dirname(d.name)
        for f in sorted(d.rglob("*.json")):
            by_model.setdefault(_model_from_relpath(str(f.relative_to(d))), []).append((f, dir_split))

    run_ids: list[str] = []
    for model, file_splits in by_model.items():
        payload = _baseline_payload(model, file_splits, set_label)
        if payload is None:
            continue
        run_id = _ingest_native_payload(
            payload, source=f"car-bench-baseline:{model}:{set_label}",
            variant_id=ids.slug(f"baseline-{model}"),
            tags=["baseline", f"set:{set_label}"],
            run_seed=f"{model}|{set_label}",
        )
        run_ids.append(run_id)
    if refresh and run_ids:
        store.refresh()
    return run_ids


_SPLIT_PREFIXES = ("base", "hallucination", "disambiguation")


def _split_from_dirname(name: str) -> str | None:
    """The task split a results subdir belongs to (its leading split word)."""
    for split in _SPLIT_PREFIXES:
        if name == split or name.startswith(split + "_"):
            return split
    return None


def _set_label_from_dirname(name: str) -> str | None:
    """Derive an evaluation-set label from a results subdir name, normalizing the
    upstream naming drift (base_v2 / hallucination_train_v2 / disambiguation_v2
    all map to 'v2'). Returns None for non-split dirs."""
    for split in _SPLIT_PREFIXES:
        if name == split:
            rest = ""
        elif name.startswith(split + "_"):
            rest = name[len(split) + 1:]
        else:
            continue
        if "v2" in rest:
            return "v2"
        if "test" in rest:
            return "test"
        if "train" in rest:
            return "train"
        return rest or "main"
    return None


def _model_from_relpath(rel: str) -> str:
    """Agent-model id from a result file's path relative to its split dir.

    Handles the upstream quirk where the user-model string
    ``gemini/gemini-2.5-flash`` put a ``/`` in the filename, nesting the result
    one directory deep (so the model lives before ``_range``/``_tasks``/``_user-``).
    """
    for sep in ("_tasks", "_range", "_user-"):
        if sep in rel:
            return rel.split(sep)[0]
    return Path(rel).stem


def import_all_baselines(results_root: Path, *, refresh: bool = True) -> list[str]:
    """Import every author-published result set under a car-bench ``results/`` root.

    Files across all split dirs are grouped by ``(set_label, model)`` so the three
    splits of a model's evaluation reconstruct into one run. One run per
    (set, model).
    """
    results_root = Path(results_root)
    groups: dict[tuple[str, str], list[tuple[Path, str | None]]] = {}
    for d in sorted(results_root.iterdir()):
        if not d.is_dir():
            continue
        set_label = _set_label_from_dirname(d.name)
        if set_label is None:
            continue
        dir_split = _split_from_dirname(d.name)
        for f in sorted(d.rglob("*.json")):
            groups.setdefault((set_label, _model_from_relpath(str(f.relative_to(d)))), []).append((f, dir_split))

    run_ids: list[str] = []
    for (set_label, model), file_splits in sorted(groups.items()):
        payload = _baseline_payload(model, file_splits, set_label)
        if payload is None:
            continue
        run_ids.append(_ingest_native_payload(
            payload, source=f"car-bench-baseline:{model}:{set_label}",
            variant_id=ids.slug(f"baseline-{model}"),
            tags=["baseline", f"set:{set_label}"],
            run_seed=f"{model}|{set_label}",
        ))
    if refresh and run_ids:
        store.refresh()
    return run_ids


def _baseline_payload(model: str, file_splits: list[tuple[Path, str | None]], set_label: str) -> dict | None:
    detailed: dict[str, list] = {"base": [], "hallucination": [], "disambiguation": []}
    for f, dir_split in file_splits:
        records = ingest.load_payload(f)
        if not isinstance(records, list):
            continue
        for rec in records:
            info = rec.get("info", {}) or {}
            # Prefer a split encoded in the task_id (e.g. "base_0"); else the dir.
            prefix = str(rec.get("task_id", "")).split("_")[0]
            split = prefix if prefix in detailed else dir_split
            if split not in detailed:
                continue
            detailed[split].append({
                "task_id": str(rec.get("task_id")),
                "reward": rec.get("reward"),
                "trial": rec.get("trial"),
                "reward_info": info.get("reward_info", {}),
                "task": info.get("task", {}),
                "trajectory": [m for m in (rec.get("traj") or []) if isinstance(m, dict) and m.get("role") != "system"],
                "error": info.get("error"),
                "total_agent_cost": info.get("total_agent_cost", 0),
                "total_llm_latency_ms": info.get("total_llm_induced_latency_ms", 0),
            })
    if not any(detailed.values()):
        return None
    # synthesize final_result pass scores from the rows we just built
    flat = [{"split": s, "task_id": r["task_id"], "passed": (r.get("reward") or 0) >= ingest.PASS_THRESHOLD}
            for s, rows in detailed.items() for r in rows]
    rec = ingest.recompute_pass_scores(flat)
    by_split = {s: {"Pass^3": rec[s]["pass_power_k"]} for s in ingest.SPLITS}
    return {
        "metadata": {
            "schema_version": 1, "model": model, "reasoning_effort": None,
            "config": {"num_trials": 3, "task_split": set_label, "max_steps": 50},
        },
        "final_result": {
            "pass_power_k_scores": {"Pass^3": rec["overall"]["pass_power_k"]},
            "pass_at_k_scores": {"Pass@3": rec["overall"]["pass_at_k"]},
            "pass_power_k_scores_by_split": by_split,
            "pass_at_k_scores_by_split": {},
            "detailed_results_by_split": detailed,
        },
    }


def _ingest_native_payload(payload: dict, *, source: str, variant_id: str,
                           tags: list[str], run_seed: str) -> str:
    """Shared path: register variant, write run dir + manifest from a native payload."""
    md = payload.get("metadata", {}) or {}
    cfg = md.get("config", {}) or {}
    identity = {
        "image_digest": None, "agent_llm": md.get("model"), "agent_thinking": None,
        "agent_reasoning_effort": md.get("reasoning_effort"), "agent_interleaved_thinking": None,
        "agent_temperature": None, "system_prompt_sha256": None,
        "scaffold_kind": "baseline", "harness_git_sha": None,
    }
    variant_ref = registry.upsert_variant_version(
        variant_id=variant_id, identity=identity, created_at="1970-01-01T00:00:00+00:00",
        extra={"scaffold_kind": "baseline", "source_dir": "car-bench/results", "lifecycle": "validated"},
    )
    vid, _ = ids.split_variant_ref(variant_ref)
    cfg_hash = ids.config_hash(cfg)
    rand4 = ids.sha256_hex(run_seed)[:4]
    run_id = ids.new_run_id(timestamp_compact="00000000T000000Z", variant_id=vid, cfg_hash=cfg_hash, rand4=rand4)
    run_dir = paths.run_dir(run_id)
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "result.json").write_text(json.dumps(payload), encoding="utf-8")
    task_trials = ingest._task_trial_rows(payload, run_id=run_id, variant_ref=variant_ref, variant_id=vid)
    headline = ingest.headline_from_payload(payload, task_trials)
    registry.write_run_manifest({
        "$schema": "../../schemas/run_manifest.schema.json", "manifest_version": 1,
        "run_id": run_id, "variant_ref": variant_ref, "variant_id": vid, "status": "completed",
        "created_at": None, "started_at": None, "completed_at": None,
        "config_hash": cfg_hash, "eval": cfg,
        "provenance": {"execution_mode": "imported", "dataset_split": cfg.get("task_split"), "source": source},
        "agent_metadata": {}, "result_json_path": "result.json", "result_schema_version": 1,
        "headline": headline, "tags": tags, "hypothesis": None, "notes": f"imported from {source}",
    })
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
