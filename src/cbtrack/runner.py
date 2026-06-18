"""`cbtrack run` — execute one evaluation and land it in the FAIR registry.

Flow (local mode, sequential — Phase 1):
  1. register/resolve the agent *variant version* -> variant_ref
  2. allocate a free port pair, render scenario.resolved.toml into the run dir
  3. invoke the native harness (`agentbeats.run_scenario`) as a subprocess,
     writing its result JSON under the run dir
  4. locate that JSON, copy it verbatim to result.json
  5. capture provenance (git/docker/scenario hash/seeds), compute headline,
     write manifest.json + env.captured.json, append to the registry
  6. refresh the DuckDB/Parquet store

Docker mode (compose project + dynamic ports + per-run mount) is Phase 3 and
raises NotImplementedError here so the seam is explicit.
"""

from __future__ import annotations

import os
import secrets
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from . import ids, ingest, paths, provenance, registry, scenario_gen, store
from .scenario_gen import AgentSpec, RunConfig

_RESERVED_JSON = {"manifest.json", "result.json", "env.captured.json", "a2a-scenario.toml"}


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _compact_ts(dt: datetime) -> str:
    return dt.strftime("%Y%m%dT%H%M%SZ")


def build_variant_identity(agent: AgentSpec, *, system_prompt_sha256: str | None,
                           scaffold_kind: str, image_digest: str | None) -> dict[str, Any]:
    env = agent.env or {}
    return {
        "image_digest": image_digest,
        "agent_llm": agent.agent_llm or env.get("AGENT_LLM"),
        "agent_thinking": env.get("AGENT_THINKING"),
        "agent_reasoning_effort": env.get("AGENT_REASONING_EFFORT"),
        "agent_interleaved_thinking": env.get("AGENT_INTERLEAVED_THINKING"),
        "agent_temperature": env.get("AGENT_TEMPERATURE"),
        "system_prompt_sha256": system_prompt_sha256,
        "scaffold_kind": scaffold_kind,
        "harness_git_sha": provenance.git_sha(paths.repo_root()),
    }


def _find_result_json(run_dir: Path) -> Path | None:
    """The native client writes <run_dir>/<agent_slug>/<file>.json. Pick newest."""
    candidates = [
        p for p in run_dir.rglob("*.json")
        if p.name not in _RESERVED_JSON and p.parent != run_dir.parent
    ]
    if not candidates:
        return None
    return max(candidates, key=lambda p: p.stat().st_mtime)


def _invoke_harness(scenario_path: Path, run_dir: Path, *, show_logs: bool, timeout: int) -> int:
    root = paths.repo_root()
    env = os.environ.copy()
    src = str(root / "src")
    env["PYTHONPATH"] = src + os.pathsep + env.get("PYTHONPATH", "")
    cmd = [
        sys.executable, "-m", "agentbeats.run_scenario",
        str(scenario_path), "--output", str(run_dir),
    ]
    if show_logs:
        cmd.append("--show-logs")
    proc = subprocess.run(cmd, cwd=str(root), env=env, timeout=timeout, check=False)
    return proc.returncode


def run(
    *,
    variant_id: str,
    agent: AgentSpec,
    config: RunConfig | None = None,
    scaffold_kind: str = "bare",
    system_prompt_sha256: str | None = None,
    image_digest: str | None = None,
    tags: list[str] | None = None,
    hypothesis: str | None = None,
    notes: str | None = None,
    seeds: dict[str, Any] | None = None,
    execution_mode: str = "local",
    show_logs: bool = False,
    timeout: int = 60 * 60,
) -> dict[str, Any]:
    """Execute one run; returns the written manifest dict."""
    if execution_mode != "local":
        raise NotImplementedError("docker execution is Phase 3 (see ADR 0006)")

    config = config or scenario_gen.TEST_SET
    paths.ensure_tree()
    created = _utc_now()

    # 1. variant version
    identity = build_variant_identity(
        agent, system_prompt_sha256=system_prompt_sha256,
        scaffold_kind=scaffold_kind, image_digest=image_digest,
    )
    variant_ref = registry.upsert_variant_version(
        variant_id=variant_id,
        identity=identity,
        created_at=created.isoformat(),
        extra={
            "scaffold_kind": scaffold_kind,
            "source_dir": str(Path(agent.agent_module).parent),
            "env_contract": _default_env_contract(agent),
        },
    )
    vid, _ = ids.split_variant_ref(variant_ref)

    # 2. run id + dir + rendered scenario
    cfg_hash = ids.config_hash(config.to_toml_dict())
    run_id = ids.new_run_id(
        timestamp_compact=_compact_ts(created),
        variant_id=vid,
        cfg_hash=cfg_hash,
        rand4=secrets.token_hex(2),
    )
    run_dir = paths.run_dir(run_id)
    run_dir.mkdir(parents=True, exist_ok=True)

    evaluator_port, agent_port = scenario_gen.find_free_port_pair()
    scenario = scenario_gen.render_local(
        agent=agent, config=config,
        evaluator_port=evaluator_port, agent_port=agent_port,
    )
    scenario_path = run_dir / "scenario.resolved.toml"
    scenario_gen.write_toml(scenario, scenario_path)

    # env snapshot (secret-free) up front, so a crashed run is still auditable
    env_snapshot = provenance.scrub_env()
    (run_dir / "env.captured.json").write_text(
        __import__("json").dumps(env_snapshot, indent=2, sort_keys=True), encoding="utf-8"
    )

    # 3. invoke harness
    rc = _invoke_harness(scenario_path, run_dir, show_logs=show_logs, timeout=timeout)

    # 4. locate + copy native result
    result_src = _find_result_json(run_dir)
    status = "completed"
    payload: dict[str, Any] = {}
    if rc != 0 or result_src is None:
        status = "failed"
    else:
        payload = ingest.load_payload(result_src)
        (run_dir / "result.json").write_text(
            result_src.read_text(encoding="utf-8"), encoding="utf-8"
        )

    completed = _utc_now()

    # 5. provenance + headline + manifest
    prov = provenance.capture(
        scenario_path=scenario_path,
        execution_mode=execution_mode,
        evaluator_image=None,
        agent_image=agent.image,
        task_split=config.task_split,
        seeds=seeds or {
            "user_model": config.user_model,
            "policy_evaluator_model": config.policy_evaluator_model,
        },
        ports={"evaluator": evaluator_port, "agent_under_test": agent_port},
    )
    task_trials = ingest._task_trial_rows(payload, run_id=run_id, variant_ref=variant_ref, variant_id=vid) if payload else []
    headline = ingest.headline_from_payload(payload, task_trials) if payload else {}
    md = payload.get("metadata", {}) if payload else {}

    manifest = {
        "$schema": "../../schemas/run_manifest.schema.json",
        "manifest_version": 1,
        "run_id": run_id,
        "variant_ref": variant_ref,
        "variant_id": vid,
        "status": status,
        "created_at": created.isoformat(),
        "started_at": md.get("started_at"),
        "completed_at": md.get("completed_at") or completed.isoformat(),
        "config_hash": cfg_hash,
        "eval": config.to_toml_dict(),
        "provenance": prov,
        "agent_metadata": md.get("agent_metadata", {}),
        "result_json_path": "result.json" if status == "completed" else None,
        "result_schema_version": md.get("schema_version"),
        "headline": headline,
        "tags": tags or [],
        "hypothesis": hypothesis,
        "notes": notes,
        "harness_returncode": rc,
    }
    registry.write_run_manifest(manifest)

    # mark the variant validated once a real test-split run completes
    if status == "completed" and config.task_split in ("test", "hidden"):
        try:
            registry.set_variant_lifecycle(variant_ref, "validated")
        except KeyError:
            pass

    # 6. refresh store (best-effort; store needs duckdb installed)
    try:
        store.refresh()
    except Exception as exc:  # pragma: no cover
        manifest["_store_refresh_error"] = str(exc)

    return manifest


def _default_env_contract(agent: AgentSpec) -> dict[str, Any]:
    """Declared env-var NAMES (no values) for submission rendering."""
    required = ["AGENT_LLM"]
    optional = ["AGENT_TEMPERATURE", "AGENT_API_BASE", "LOGURU_LEVEL"]
    for k in (agent.env or {}):
        if k not in required and k not in optional:
            optional.append(k)
    return {"required": required, "optional": optional}
