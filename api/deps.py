"""Shared dependencies for the cbtrack FastAPI backend.

Opens the DuckDB store read-only and exposes small query helpers. Keeps cbtrack
importable whether or not the package is pip-installed by adding ``src`` to the
path. Bootstrap CIs use the stdlib (seeded) so there is no numpy requirement.
"""

from __future__ import annotations

import random
import sys
from functools import lru_cache
from pathlib import Path
from typing import Any

# Ensure `import cbtrack` works when running `uvicorn api.main:app` from repo root.
_REPO_ROOT = Path(__file__).resolve().parents[1]
_SRC = _REPO_ROOT / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from cbtrack import paths, store  # noqa: E402


def get_con():
    """A fresh read-only DuckDB connection (DuckDB allows many readers)."""
    return store.connect(read_only=True)


def store_exists() -> bool:
    return paths.duckdb_path().exists()


def rows_to_dicts(cur) -> list[dict[str, Any]]:
    cols = [d[0] for d in cur.description]
    return [dict(zip(cols, row)) for row in cur.fetchall()]


def query(sql: str, params: list[Any] | None = None) -> list[dict[str, Any]]:
    con = get_con()
    try:
        cur = con.execute(sql, params or [])
        return rows_to_dicts(cur)
    finally:
        con.close()


# --- bootstrap CI for Pass^k --------------------------------------------

def bootstrap_ci(pass_flags: list[int], *, n_boot: int = 2000, seed: int = 12345,
                 alpha: float = 0.05) -> dict[str, float | None]:
    """95% bootstrap CI for the mean of a 0/1 task-level pass vector.

    pass_flags is one value per *task* (1 if the task passed the consistency
    criterion, else 0). Deterministic via a fixed seed so the dashboard is stable.
    """
    n = len(pass_flags)
    if n == 0:
        return {"mean": None, "lo": None, "hi": None, "n": 0}
    mean = sum(pass_flags) / n
    rng = random.Random(seed)
    means = []
    for _ in range(n_boot):
        s = 0
        for _ in range(n):
            s += pass_flags[rng.randrange(n)]
        means.append(s / n)
    means.sort()
    lo = means[int((alpha / 2) * n_boot)]
    hi = means[min(n_boot - 1, int((1 - alpha / 2) * n_boot))]
    return {"mean": round(mean, 4), "lo": round(lo, 4), "hi": round(hi, 4), "n": n}


def task_pass_flags(run_filter_sql: str, params: list[Any], *, level: str = "power") -> list[int]:
    """Per-task pass flags for a filtered set of task_trials.

    level='power' -> Pass^k (all trials pass); level='at' -> Pass@k (any pass).
    """
    agg = "min" if level == "power" else "max"
    sql = f"""
        with per as (
            select split, task_id, {agg}(case when passed then 1 else 0 end) AS p
            from task_trials
            where {run_filter_sql}
            group by split, task_id
        )
        select p from per
    """
    return [r["p"] for r in query(sql, params)]
