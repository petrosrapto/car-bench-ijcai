"""Static report export — thin wrapper over the official outputs/plot_results.py.

We do not reimplement plotting; we point the existing organizer script at a
directory of native result JSONs (e.g. the per-run result.json files this tracker
stores) and let it render the publication-grade PNG/PDF figures. Useful for paper
figures and a "download static report" button in the dashboard.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from . import paths


def export(input_dir: Path | None = None, report_dir: Path | None = None,
           extra_args: list[str] | None = None) -> int:
    """Invoke plot_results.py over ``input_dir`` (default: experiments/runs)."""
    root = paths.repo_root()
    script = root / "outputs" / "plot_results.py"
    if not script.exists():
        raise FileNotFoundError(script)
    input_dir = input_dir or paths.runs_dir()
    cmd = [sys.executable, str(script), "--input-dir", str(input_dir)]
    if report_dir:
        cmd += ["--report-dir", str(report_dir)]
    cmd += extra_args or []
    return subprocess.run(cmd, cwd=str(root), check=False).returncode
