"""Normalize a native CAR-bench run payload into flat rows.

Input: the JSON written by ``agentbeats.client_cli`` — ``{metadata, final_result,
...}`` where ``final_result.detailed_results_by_split[split]`` is a list of
per-task-per-trial rows (schema verified against
``evaluator.car_bench_evaluator._detailed_result_row``).

Output: three row lists — ``runs`` (1), ``task_trials`` (one per task x trial),
``turns`` (one per trajectory message) — using the *literal native field names*
so the store/dashboard schema mirrors the source.

Token/latency parsing reuses the official ``outputs/plot_results.py`` extractors
(loaded by path, since it is a script not a package) so numbers match the
organizer tooling byte-for-byte; if that import fails we fall back to reading the
row keys directly (they are already present in the native row).
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from typing import Any

from . import paths

SPLITS = ("base", "hallucination", "disambiguation")
PASS_THRESHOLD = 0.99  # evaluator treats reward >= 0.99 as a pass

# Subscore keys verified in reward_calculators.py / a real result's reward_info.info
SUBSCORE_KEYS = (
    "r_actions",
    "r_actions_final",
    "r_actions_intermediate",
    "r_tool_subset",
    "r_tool_execution",
    "r_policy",
    "r_user_end_conversation",
)
LIST_DIAG_KEYS = (
    "tool_subset_missing_tools",
    "tool_execution_errors",
    "policy_llm_errors",
    "policy_aut_errors",
)
TOKEN_KEYS = (
    "agent_input_tokens",
    "agent_output_tokens",
    "agent_prompt_tokens",
    "agent_completion_tokens",
    "agent_thinking_tokens",
    "agent_total_tokens",
)

# --- optional reuse of the official extractors ---------------------------

_plot = None


def _plot_results():
    global _plot
    if _plot is not None:
        return _plot
    try:
        spec = importlib.util.spec_from_file_location(
            "cbtrack_vendored_plot_results",
            paths.repo_root() / "outputs" / "plot_results.py",
        )
        mod = importlib.util.module_from_spec(spec)  # type: ignore[arg-type]
        spec.loader.exec_module(mod)  # type: ignore[union-attr]
        _plot = mod
    except Exception:
        _plot = False  # sentinel: tried and failed
    return _plot


def _num(value: Any) -> float | None:
    if isinstance(value, bool):
        return float(value)
    if isinstance(value, (int, float)):
        return float(value)
    return None


def _a2a_task_time_s(row: dict[str, Any]) -> float | None:
    plot = _plot_results()
    if plot:
        ms = plot.a2a_task_time_from_row(row)
        return ms / 1000.0 if ms is not None else None
    ms = _num(row.get("total_a2a_time_ms"))
    return ms / 1000.0 if ms is not None else None


# --- payload loading ------------------------------------------------------

def load_payload(path: Path) -> dict[str, Any]:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def final_result_of(payload: dict[str, Any]) -> dict[str, Any]:
    fr = payload.get("final_result")
    return fr if isinstance(fr, dict) else {}


# --- row builders ---------------------------------------------------------

def _task_trial_rows(
    payload: dict[str, Any], *, run_id: str, variant_ref: str | None, variant_id: str | None
) -> list[dict[str, Any]]:
    fr = final_result_of(payload)
    detailed = fr.get("detailed_results_by_split", {}) or {}
    rows: list[dict[str, Any]] = []
    for split in SPLITS:
        for row in detailed.get(split, []) or []:
            if not isinstance(row, dict):
                continue
            reward_info = row.get("reward_info", {}) or {}
            info = reward_info.get("info", {}) or {}
            task = row.get("task", {}) or {}
            out: dict[str, Any] = {
                "run_id": run_id,
                "variant_ref": variant_ref,
                "variant_id": variant_id,
                "split": split,
                "task_id": row.get("task_id"),
                "trial": row.get("trial"),
                "task_type": task.get("task_type"),
                "persona": task.get("persona"),
                "reward": _num(row.get("reward")),
                "passed": (_num(row.get("reward")) or 0.0) >= PASS_THRESHOLD,
                "error": row.get("error"),
            }
            for key in SUBSCORE_KEYS:
                out[key] = info.get(key)  # bool | float | None (None = not applicable)
            for key in LIST_DIAG_KEYS:
                val = info.get(key)
                out[key] = list(val) if isinstance(val, list) else []
            out["end_conversation_keyword"] = info.get("end_conversation_keyword")
            for key in TOKEN_KEYS:
                out[key] = _num(row.get(key))
            out["total_agent_cost"] = _num(row.get("total_agent_cost"))
            out["total_llm_latency_ms"] = _num(row.get("total_llm_latency_ms"))
            out["total_a2a_time_ms"] = _num(row.get("total_a2a_time_ms"))
            out["a2a_task_time_s"] = _a2a_task_time_s(row)
            out["num_turns"] = len(row.get("trajectory", []) or [])
            rows.append(out)
    return rows


def _turn_rows(payload: dict[str, Any], *, run_id: str) -> list[dict[str, Any]]:
    fr = final_result_of(payload)
    detailed = fr.get("detailed_results_by_split", {}) or {}
    rows: list[dict[str, Any]] = []
    for split in SPLITS:
        for row in detailed.get(split, []) or []:
            if not isinstance(row, dict):
                continue
            task_id = row.get("task_id")
            trial = row.get("trial")
            for idx, msg in enumerate(row.get("trajectory", []) or []):
                if not isinstance(msg, dict):
                    continue
                tm = msg.get("turn_metrics", {}) or {}
                em = msg.get("evaluator_metrics", {}) or {}
                tool_calls = msg.get("tool_calls")
                rows.append({
                    "run_id": run_id,
                    "split": split,
                    "task_id": task_id,
                    "trial": trial,
                    "turn_idx": idx,
                    "role": msg.get("role"),
                    "content": msg.get("content"),
                    "name": msg.get("name"),
                    "tool_call_id": msg.get("tool_call_id"),
                    "tool_calls": json.dumps(tool_calls) if tool_calls is not None else None,
                    "prompt_tokens": _num(tm.get("prompt_tokens")),
                    "completion_tokens": _num(tm.get("completion_tokens")),
                    "thinking_tokens": _num(tm.get("thinking_tokens")),
                    "cost": _num(tm.get("cost")),
                    "model": tm.get("model"),
                    "num_llm_calls": _num(tm.get("num_llm_calls")),
                    "avg_llm_call_time_ms": _num(tm.get("avg_llm_call_time_ms")),
                    "quota_wait_time_ms": _num(tm.get("quota_wait_time_ms")),
                    "a2a_turn_time_ms": _num(em.get("a2a_turn_time_ms")),
                })
    return rows


def recompute_pass_scores(task_trials: list[dict[str, Any]]) -> dict[str, Any]:
    """Recompute Pass^k / Pass@k per split + overall from task_trial rows.

    Pass^k = every trial of a task passes; Pass@k = at least one trial passes.
    Grouping by (split, task_id). Returned as fractions in [0, 1].
    """
    by_task: dict[tuple[str, str], list[bool]] = {}
    for r in task_trials:
        key = (r["split"], r["task_id"])
        by_task.setdefault(key, []).append(bool(r["passed"]))

    def agg(keys: list[tuple[str, str]]) -> dict[str, float | int]:
        n = len(keys)
        if n == 0:
            return {"n_tasks": 0, "pass_power_k": None, "pass_at_k": None}
        pp = sum(1 for k in keys if all(by_task[k])) / n
        pa = sum(1 for k in keys if any(by_task[k])) / n
        return {"n_tasks": n, "pass_power_k": round(pp, 4), "pass_at_k": round(pa, 4)}

    out: dict[str, Any] = {"overall": agg(list(by_task.keys()))}
    for split in SPLITS:
        out[split] = agg([k for k in by_task if k[0] == split])
    return out


def headline_from_payload(payload: dict[str, Any], task_trials: list[dict[str, Any]]) -> dict[str, Any]:
    """Headline metrics for the run manifest — native scores + a recompute."""
    fr = final_result_of(payload)
    recomputed = recompute_pass_scores(task_trials)
    costs = [r["total_agent_cost"] for r in task_trials if r.get("total_agent_cost") is not None]
    toks = [r["agent_total_tokens"] for r in task_trials if r.get("agent_total_tokens") is not None]
    times = [r["a2a_task_time_s"] for r in task_trials if r.get("a2a_task_time_s") is not None]
    pp = fr.get("pass_power_k_scores", {}) or {}
    pa = fr.get("pass_at_k_scores", {}) or {}
    gap = None
    if isinstance(pa.get("Pass@3"), (int, float)) and isinstance(pp.get("Pass^3"), (int, float)):
        gap = round(pa["Pass@3"] - pp["Pass^3"], 4)
    return {
        "pass_power_k": pp,
        "pass_at_k": pa,
        "by_split": fr.get("pass_power_k_scores_by_split", {}) or {},
        "pass_at_k_by_split": fr.get("pass_at_k_scores_by_split", {}) or {},
        "recomputed": recomputed,
        "consistency_gap_pass3": gap,
        "mean_cost": round(sum(costs) / len(costs), 6) if costs else None,
        "mean_total_tokens": round(sum(toks) / len(toks), 1) if toks else None,
        "mean_a2a_task_time_s": round(sum(times) / len(times), 2) if times else None,
        "n_task_trials": len(task_trials),
        "n_tasks_by_split": {s: recomputed[s]["n_tasks"] for s in SPLITS},
    }


def normalize(
    payload: dict[str, Any],
    *,
    run_id: str,
    variant_ref: str | None = None,
    variant_id: str | None = None,
    manifest: dict[str, Any] | None = None,
) -> dict[str, list[dict[str, Any]]]:
    """Return {'task_trials': [...], 'turns': [...], 'runs': [row]}."""
    task_trials = _task_trial_rows(payload, run_id=run_id, variant_ref=variant_ref, variant_id=variant_id)
    turns = _turn_rows(payload, run_id=run_id)
    runs_row = _run_row(run_id=run_id, payload=payload, task_trials=task_trials, manifest=manifest)
    return {"task_trials": task_trials, "turns": turns, "runs": [runs_row]}


def _run_row(
    *, run_id: str, payload: dict[str, Any], task_trials: list[dict[str, Any]], manifest: dict[str, Any] | None
) -> dict[str, Any]:
    md = payload.get("metadata", {}) or {}
    headline = (manifest or {}).get("headline") or headline_from_payload(payload, task_trials)
    prov = (manifest or {}).get("provenance", {}) or {}
    eval_cfg = (manifest or {}).get("eval") or md.get("config", {}) or {}
    pp = headline.get("pass_power_k", {}) or {}
    pa = headline.get("pass_at_k", {}) or {}
    by_split = headline.get("by_split", {}) or {}
    return {
        "run_id": run_id,
        "variant_ref": (manifest or {}).get("variant_ref"),
        "variant_id": (manifest or {}).get("variant_id"),
        "status": (manifest or {}).get("status", "completed"),
        "started_at": md.get("started_at"),
        "completed_at": md.get("completed_at"),
        "config_hash": (manifest or {}).get("config_hash"),
        "task_split": eval_cfg.get("task_split"),
        "num_trials": eval_cfg.get("num_trials"),
        "max_steps": eval_cfg.get("max_steps"),
        "model": md.get("model"),
        "reasoning_effort": md.get("reasoning_effort"),
        "agent_image_digest": prov.get("agent_image_digest"),
        "evaluator_image_digest": prov.get("evaluator_image_digest"),
        "dataset_version": prov.get("dataset_version"),
        "harness_git_sha": prov.get("harness_git_sha"),
        "wall_time_seconds": md.get("wall_time_seconds"),
        "quota_wait_seconds": md.get("quota_wait_seconds"),
        "pass_power_3": pp.get("Pass^3"),
        "pass_at_3": pa.get("Pass@3"),
        "pass_power_3_base": (by_split.get("base", {}) or {}).get("Pass^3"),
        "pass_power_3_hall": (by_split.get("hallucination", {}) or {}).get("Pass^3"),
        "pass_power_3_disamb": (by_split.get("disambiguation", {}) or {}).get("Pass^3"),
        "consistency_gap_pass3": headline.get("consistency_gap_pass3"),
        "mean_cost": headline.get("mean_cost"),
        "mean_total_tokens": headline.get("mean_total_tokens"),
        "tags": json.dumps((manifest or {}).get("tags", [])),
        "hypothesis": (manifest or {}).get("hypothesis"),
    }
