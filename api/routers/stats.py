"""Statistics endpoints — the analytical core of the dashboard.

All slicing happens in DuckDB over the flat ``task_trials`` table plus the
``policy_violations`` / ``tool_errors`` views. Pass^k is recomputed from the
per-task-per-trial rows so any filtered subset (split, task_type, variant) is
correct, and headline bars carry bootstrap CIs (Pass^3 is high-variance on ~254
tasks).
"""

from __future__ import annotations

import sys
from pathlib import Path

from fastapi import APIRouter, Query

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))
from cbtrack import ingest  # noqa: E402

from .. import deps  # noqa: E402

router = APIRouter(prefix="/api", tags=["stats"])

SPLITS = ingest.SPLITS
SUBSCORES = ingest.SUBSCORE_KEYS


def _filters(run_id: str | None, variant_ref: str | None, split: str | None,
             task_type: str | None) -> tuple[str, list]:
    clauses, params = ["1=1"], []
    if run_id:
        clauses.append("run_id = ?"); params.append(run_id)
    if variant_ref:
        clauses.append("variant_ref = ?"); params.append(variant_ref)
    if split and split != "overall":
        clauses.append("split = ?"); params.append(split)
    if task_type:
        clauses.append("task_type = ?"); params.append(task_type)
    return " AND ".join(clauses), params


def _latest_run_per_variant() -> list[dict]:
    # Order by run_id (UTC-compact-timestamp prefix => chronological, never NULL)
    # rather than completed_at, which may be NULL for imported/baseline runs.
    return deps.query(
        """
        select variant_ref, variant_id, run_id, completed_at
        from runs r
        where variant_ref is not null
          and run_id = (
              select max(run_id) from runs r2 where r2.variant_ref = r.variant_ref
          )
        """
    )


@router.get("/stats/headline")
def headline(variant_ref: str | None = None, split: str = "overall",
             run_id: str | None = None):
    """Per-variant Pass^3 (+95% bootstrap CI) and Pass@3 for the latest run."""
    if run_id:
        targets = [{"variant_ref": variant_ref, "run_id": run_id, "variant_id": None}]
    elif variant_ref:
        rows = deps.query(
            "select variant_ref, variant_id, run_id from runs where variant_ref=? "
            "order by run_id desc limit 1", [variant_ref])
        targets = rows
    else:
        targets = _latest_run_per_variant()

    out = []
    for t in targets:
        where, params = _filters(t["run_id"], t.get("variant_ref"), split, None)
        flags_power = deps.task_pass_flags(where, params, level="power")
        flags_at = deps.task_pass_flags(where, params, level="at")
        out.append({
            "variant_ref": t.get("variant_ref"),
            "variant_id": t.get("variant_id"),
            "run_id": t["run_id"],
            "split": split,
            "pass_power_3": deps.bootstrap_ci(flags_power),
            "pass_at_3": deps.bootstrap_ci(flags_at),
        })
    out.sort(key=lambda r: (r["pass_power_3"]["mean"] or 0))
    return out


@router.get("/stats/subscores")
def subscores(variant_ref: str | None = None, split: str = "overall",
              task_type: str | None = None, run_id: str | None = None):
    """Among FAILED trials, how often each subscore was the culprit (==0)."""
    where, params = _filters(run_id, variant_ref, split, task_type)
    select = ", ".join(
        f"sum(case when {s} = 0 then 1 else 0 end) AS {s}" for s in SUBSCORES
    )
    rows = deps.query(
        f"select {select}, sum(case when not passed then 1 else 0 end) AS failed_trials "
        f"from task_trials where {where}", params)
    return rows[0] if rows else {}


@router.get("/stats/policies")
def policies(variant_ref: str | None = None, split: str = "overall",
             run_id: str | None = None):
    """Per-policy violation frequency (AUT vs LLM)."""
    clauses, params = ["1=1"], []
    if run_id:
        clauses.append("pv.run_id = ?"); params.append(run_id)
    if variant_ref:
        clauses.append("r.variant_ref = ?"); params.append(variant_ref)
    if split and split != "overall":
        clauses.append("pv.split = ?"); params.append(split)
    where = " AND ".join(clauses)
    return deps.query(
        f"""
        select pv.policy_id, pv.source, count(*) AS n
        from policy_violations pv join runs r on pv.run_id = r.run_id
        where {where}
        group by pv.policy_id, pv.source
        order by n desc
        """, params)


@router.get("/stats/tools")
def tools(variant_ref: str | None = None, split: str = "overall",
          run_id: str | None = None):
    """Per-tool error frequency (execution errors + missing-from-subset)."""
    clauses, params = ["1=1"], []
    if run_id:
        clauses.append("te.run_id = ?"); params.append(run_id)
    if variant_ref:
        clauses.append("r.variant_ref = ?"); params.append(variant_ref)
    if split and split != "overall":
        clauses.append("te.split = ?"); params.append(split)
    where = " AND ".join(clauses)
    return deps.query(
        f"""
        select te.detail, te.source, count(*) AS n
        from tool_errors te join runs r on te.run_id = r.run_id
        where {where}
        group by te.detail, te.source
        order by n desc
        """, params)


@router.get("/stats/economics")
def economics(variant_ref: str | None = None, split: str = "overall",
              run_id: str | None = None):
    """Cost / tokens / latency aggregates for the slice."""
    where, params = _filters(run_id, variant_ref, split, None)
    rows = deps.query(
        f"""
        select
          avg(total_agent_cost) AS mean_cost,
          avg(agent_input_tokens) AS mean_input_tokens,
          avg(agent_output_tokens) AS mean_output_tokens,
          avg(agent_total_tokens) AS mean_total_tokens,
          avg(a2a_task_time_s) AS mean_a2a_task_time_s,
          count(*) AS n
        from task_trials where {where}
        """, params)
    return rows[0] if rows else {}


@router.get("/compare")
def compare(variant_refs: str = Query(..., description="comma-separated variant_refs"),
            split: str = "overall"):
    """Side-by-side headline + per-task Pass^3 outcome for win/loss diffing."""
    refs = [r for r in variant_refs.split(",") if r]
    result = []
    for ref in refs:
        run = deps.query(
            "select run_id from runs where variant_ref=? order by run_id desc limit 1", [ref])
        run_id = run[0]["run_id"] if run else None
        where, params = _filters(run_id, ref, split, None)
        per_task = deps.query(
            f"""
            with per as (
              select split, task_id, min(case when passed then 1 else 0 end) AS p3
              from task_trials where {where} group by split, task_id)
            select split, task_id, p3 from per order by split, task_id
            """, params)
        flags = [r["p3"] for r in per_task]
        result.append({
            "variant_ref": ref,
            "run_id": run_id,
            "pass_power_3": deps.bootstrap_ci(flags),
            "tasks": {f'{r["split"]}/{r["task_id"]}': r["p3"] for r in per_task},
        })
    return result


@router.get("/trends")
def trends(variant_id: str):
    """Metric over a variant_id's run history (all its versions' runs)."""
    return deps.query(
        """
        select run_id, variant_ref, completed_at, task_split,
               pass_power_3, pass_at_3, consistency_gap_pass3, mean_cost
        from runs where variant_id = ?
        order by completed_at
        """, [variant_id])
