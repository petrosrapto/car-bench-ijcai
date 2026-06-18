"""Build the queryable store: JSONL (portable) + Parquet (columnar) + DuckDB.

``refresh()`` is a full rebuild from the registry — simple and always-correct at
this scale (hundreds of runs). It:
  1. iterates every run that has a ``result.json`` + ``manifest.json``,
  2. normalizes via ``ingest.normalize``,
  3. writes ``store/{task_trials,turns,runs,variants}.jsonl``,
  4. loads them into a fresh ``carbench.duckdb`` with typed tables (stable schema
     even when empty), copies each to Parquet, and creates the derived
     ``policy_violations`` / ``tool_errors`` views.

Only dependency is ``duckdb`` (it reads JSONL and writes Parquet natively, so we
avoid pyarrow schema-inference headaches on the list columns).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from . import ingest, paths, registry

TABLES = ("task_trials", "turns", "runs", "variants")

# Explicit DDL → stable schema even with zero rows. Subscores are DOUBLE
# (ingest coerces bool/float→float, None→NULL); diagnostics are VARCHAR[].
_DDL: dict[str, str] = {
    "task_trials": """
        CREATE TABLE task_trials (
            run_id VARCHAR, variant_ref VARCHAR, variant_id VARCHAR,
            split VARCHAR, task_id VARCHAR, trial INTEGER,
            task_type VARCHAR, persona VARCHAR,
            reward DOUBLE, passed BOOLEAN, error VARCHAR,
            r_actions DOUBLE, r_actions_final DOUBLE, r_actions_intermediate DOUBLE,
            r_tool_subset DOUBLE, r_tool_execution DOUBLE, r_policy DOUBLE,
            r_user_end_conversation DOUBLE,
            tool_subset_missing_tools VARCHAR[], tool_execution_errors VARCHAR[],
            policy_llm_errors VARCHAR[], policy_aut_errors VARCHAR[],
            end_conversation_keyword VARCHAR,
            agent_input_tokens DOUBLE, agent_output_tokens DOUBLE,
            agent_prompt_tokens DOUBLE, agent_completion_tokens DOUBLE,
            agent_thinking_tokens DOUBLE, agent_total_tokens DOUBLE,
            total_agent_cost DOUBLE, total_llm_latency_ms DOUBLE,
            total_a2a_time_ms DOUBLE, a2a_task_time_s DOUBLE, num_turns INTEGER
        )
    """,
    "turns": """
        CREATE TABLE turns (
            run_id VARCHAR, split VARCHAR, task_id VARCHAR, trial INTEGER,
            turn_idx INTEGER, role VARCHAR, content VARCHAR, name VARCHAR,
            tool_call_id VARCHAR, tool_calls VARCHAR,
            prompt_tokens DOUBLE, completion_tokens DOUBLE, thinking_tokens DOUBLE,
            cost DOUBLE, model VARCHAR, num_llm_calls DOUBLE,
            avg_llm_call_time_ms DOUBLE, quota_wait_time_ms DOUBLE,
            a2a_turn_time_ms DOUBLE
        )
    """,
    "runs": """
        CREATE TABLE runs (
            run_id VARCHAR, variant_ref VARCHAR, variant_id VARCHAR, status VARCHAR,
            started_at VARCHAR, completed_at VARCHAR, config_hash VARCHAR,
            task_split VARCHAR, num_trials INTEGER, max_steps INTEGER,
            model VARCHAR, reasoning_effort VARCHAR,
            agent_image_digest VARCHAR, evaluator_image_digest VARCHAR,
            dataset_version VARCHAR, harness_git_sha VARCHAR,
            wall_time_seconds DOUBLE, quota_wait_seconds DOUBLE,
            pass_power_3 DOUBLE, pass_at_3 DOUBLE,
            pass_power_3_base DOUBLE, pass_power_3_hall DOUBLE, pass_power_3_disamb DOUBLE,
            consistency_gap_pass3 DOUBLE, mean_cost DOUBLE, mean_total_tokens DOUBLE,
            tags VARCHAR, hypothesis VARCHAR
        )
    """,
    "variants": """
        CREATE TABLE variants (
            variant_ref VARCHAR, variant_id VARCHAR, scaffold_kind VARCHAR,
            agent_llm VARCHAR, image_digest VARCHAR, lifecycle VARCHAR,
            created_at VARCHAR
        )
    """,
}

_DERIVED_VIEWS = """
    CREATE OR REPLACE VIEW policy_violations AS
        SELECT run_id, split, task_id, trial, unnest(policy_aut_errors) AS policy_id, 'AUT' AS source
        FROM task_trials WHERE length(policy_aut_errors) > 0
        UNION ALL
        SELECT run_id, split, task_id, trial, unnest(policy_llm_errors) AS policy_id, 'LLM' AS source
        FROM task_trials WHERE length(policy_llm_errors) > 0;

    CREATE OR REPLACE VIEW tool_errors AS
        SELECT run_id, split, task_id, trial, unnest(tool_execution_errors) AS detail, 'execution' AS source
        FROM task_trials WHERE length(tool_execution_errors) > 0
        UNION ALL
        SELECT run_id, split, task_id, trial, unnest(tool_subset_missing_tools) AS detail, 'missing_subset' AS source
        FROM task_trials WHERE length(tool_subset_missing_tools) > 0;
"""


def _coerce_subscores(rows: list[dict[str, Any]]) -> None:
    """In-place: subscores -> float|None so the DOUBLE column infers cleanly."""
    for r in rows:
        for k in ingest.SUBSCORE_KEYS:
            v = r.get(k)
            if isinstance(v, bool):
                r[k] = float(v)
            elif v is None or isinstance(v, (int, float)):
                r[k] = None if v is None else float(v)


def _write_jsonl(rows: list[dict[str, Any]], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, default=str) + "\n")


def collect_rows() -> dict[str, list[dict[str, Any]]]:
    """Normalize every completed run in the registry into the four row sets."""
    acc: dict[str, list[dict[str, Any]]] = {t: [] for t in TABLES}
    for manifest in registry.iter_run_manifests():
        run_id = manifest["run_id"]
        result_path = paths.run_dir(run_id) / (manifest.get("result_json_path") or "result.json")
        if not result_path.exists():
            continue
        payload = ingest.load_payload(result_path)
        norm = ingest.normalize(
            payload,
            run_id=run_id,
            variant_ref=manifest.get("variant_ref"),
            variant_id=manifest.get("variant_id"),
            manifest=manifest,
        )
        acc["task_trials"].extend(norm["task_trials"])
        acc["turns"].extend(norm["turns"])
        acc["runs"].extend(norm["runs"])
    acc["variants"].extend(registry.list_variant_versions())
    _coerce_subscores(acc["task_trials"])
    return acc


def refresh() -> dict[str, int]:
    """Full rebuild of JSONL + Parquet + DuckDB. Returns per-table row counts."""
    import duckdb  # local import: only needed when building the store

    paths.ensure_tree()
    store = paths.store_dir()
    rows = collect_rows()

    for table in TABLES:
        _write_jsonl(rows[table], store / f"{table}.jsonl")

    db_path = paths.duckdb_path()
    if db_path.exists():
        db_path.unlink()
    con = duckdb.connect(str(db_path))
    try:
        for table in TABLES:
            con.execute(_DDL[table])
            jsonl = store / f"{table}.jsonl"
            if rows[table]:
                con.execute(
                    f"INSERT INTO {table} BY NAME "
                    f"SELECT * FROM read_json_auto('{jsonl.as_posix()}', maximum_object_size=104857600)"
                )
            con.execute(
                f"COPY {table} TO '{(store / f'{table}.parquet').as_posix()}' (FORMAT parquet)"
            )
        con.execute(_DERIVED_VIEWS)
    finally:
        con.close()

    return {t: len(rows[t]) for t in TABLES}


def connect(read_only: bool = True):
    """Open the built DuckDB store (read-only by default)."""
    import duckdb

    db_path = paths.duckdb_path()
    if not db_path.exists():
        raise FileNotFoundError(
            f"store not built yet: {db_path} — run `cbtrack refresh` (or cbtrack.store.refresh())"
        )
    return duckdb.connect(str(db_path), read_only=read_only)
