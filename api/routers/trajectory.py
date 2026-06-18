"""Trajectory replay — inspect a single past interaction turn-by-turn.

Reads the verbatim ``result.json`` (full fidelity), returning the ordered turns,
the trial verdict (each subscore pass/fail + the specific policy/tool errors),
and a ground-truth-actions-vs-taken-tool-calls diff — the most useful artifact
for debugging Pass^3 failures.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))
from cbtrack import ingest, paths, registry  # noqa: E402

router = APIRouter(prefix="/api/trajectory", tags=["trajectory"])


def _load_result(run_id: str) -> dict[str, Any]:
    manifest = registry.get_run(run_id)
    if not manifest:
        raise HTTPException(404, f"run not found: {run_id}")
    result_path = paths.run_dir(run_id) / (manifest.get("result_json_path") or "result.json")
    if not result_path.exists():
        raise HTTPException(404, f"result.json missing for {run_id}")
    return json.loads(result_path.read_text(encoding="utf-8"))


def _find_row(payload: dict, split: str, task_id: str, trial: int) -> dict | None:
    detailed = (payload.get("final_result", {}) or {}).get("detailed_results_by_split", {}) or {}
    for row in detailed.get(split, []) or []:
        if row.get("task_id") == task_id and int(row.get("trial", -1)) == int(trial):
            return row
    return None


@router.get("/{run_id}/index")
def index(run_id: str):
    """List every (split, task_id, trial) in the run for the selector."""
    payload = _load_result(run_id)
    detailed = (payload.get("final_result", {}) or {}).get("detailed_results_by_split", {}) or {}
    out = []
    for split in ingest.SPLITS:
        for row in detailed.get(split, []) or []:
            out.append({
                "split": split,
                "task_id": row.get("task_id"),
                "trial": row.get("trial"),
                "task_type": (row.get("task") or {}).get("task_type"),
                "reward": row.get("reward"),
                "passed": (row.get("reward") or 0) >= ingest.PASS_THRESHOLD,
            })
    return out


def _taken_actions(trajectory: list[dict]) -> list[dict]:
    taken = []
    for msg in trajectory:
        if msg.get("role") == "assistant":
            for tc in msg.get("tool_calls") or []:
                fn = tc.get("function", {}) or {}
                taken.append({"name": fn.get("name"), "arguments": fn.get("arguments")})
            if msg.get("content"):
                taken.append({"name": "respond", "arguments": msg.get("content")})
    return taken


@router.get("/{run_id}/{split}/{task_id}/{trial}")
def detail(run_id: str, split: str, task_id: str, trial: int):
    payload = _load_result(run_id)
    row = _find_row(payload, split, task_id, trial)
    if row is None:
        raise HTTPException(404, f"trial not found: {split}/{task_id}/{trial}")

    reward_info = row.get("reward_info", {}) or {}
    info = reward_info.get("info", {}) or {}
    task = row.get("task", {}) or {}
    trajectory = row.get("trajectory", []) or []

    verdict = {k: info.get(k) for k in ingest.SUBSCORE_KEYS}
    verdict_diagnostics = {k: info.get(k) for k in ingest.LIST_DIAG_KEYS}
    verdict_diagnostics["end_conversation_keyword"] = info.get("end_conversation_keyword")

    return {
        "run_id": run_id,
        "split": split,
        "task_id": task_id,
        "trial": trial,
        "task_type": task.get("task_type"),
        "persona": task.get("persona"),
        "instruction": task.get("instruction"),
        "reward": row.get("reward"),
        "passed": (row.get("reward") or 0) >= ingest.PASS_THRESHOLD,
        "verdict": verdict,
        "verdict_diagnostics": verdict_diagnostics,
        "ground_truth_actions": reward_info.get("actions", []),
        "taken_actions": _taken_actions(trajectory),
        "trajectory": trajectory,
        "economics": {
            "total_agent_cost": row.get("total_agent_cost"),
            "total_llm_latency_ms": row.get("total_llm_latency_ms"),
            "total_a2a_time_ms": row.get("total_a2a_time_ms"),
            "agent_total_tokens": row.get("agent_total_tokens"),
        },
    }
