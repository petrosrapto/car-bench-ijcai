"""Provenance capture — the metadata the native harness does NOT record.

Everything here is sourced from things the wrapper controls: the git repos, the
docker CLI, the rendered scenario file, and the process environment. Secrets are
never persisted: ``scrub_env`` drops anything that looks like a credential.

These fields are what make a run reproducible and comparable across
heterogeneous agent variants (image digest, git SHAs, dataset/evaluator version,
scenario hash, seeds).
"""

from __future__ import annotations

import os
import re
import subprocess
from pathlib import Path
from typing import Any

from . import ids
from .paths import repo_root

# Env vars matching these are NEVER written to disk.
_SECRET_RE = re.compile(r"(_API_KEY|_TOKEN|_SECRET|_PASSWORD|_CREDENTIAL)s?$", re.IGNORECASE)
# Env vars we DO snapshot (allowlist prefixes) — the knobs that define a run.
_ALLOW_PREFIXES = ("AGENT_", "CONFIG_", "CBTRACK_", "LOGURU_", "CAR_BENCH_")


def is_secret_key(key: str) -> bool:
    return bool(_SECRET_RE.search(key)) or key.upper().endswith("KEY")


def scrub_env(env: dict[str, str] | None = None) -> dict[str, str]:
    """Return an allowlisted, secret-free snapshot of the environment.

    Keeps AGENT_*/CONFIG_*/CBTRACK_*/LOGURU_*/CAR_BENCH_* vars, minus anything
    that looks like a credential.
    """
    env = dict(os.environ if env is None else env)
    out: dict[str, str] = {}
    for k, v in env.items():
        if not k.startswith(_ALLOW_PREFIXES):
            continue
        if is_secret_key(k):
            out[k] = "<redacted>"
            continue
        out[k] = v
    return out


def _run(cmd: list[str], cwd: Path | None = None) -> str | None:
    try:
        res = subprocess.run(
            cmd, cwd=str(cwd) if cwd else None,
            capture_output=True, text=True, timeout=30, check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if res.returncode != 0:
        return None
    out = res.stdout.strip()
    return out or None


def git_sha(repo_dir: Path) -> str | None:
    if not (repo_dir / ".git").exists():
        return None
    return _run(["git", "rev-parse", "HEAD"], cwd=repo_dir)


def git_dirty(repo_dir: Path) -> bool | None:
    if not (repo_dir / ".git").exists():
        return None
    out = _run(["git", "status", "--porcelain"], cwd=repo_dir)
    if out is None:
        return None
    return bool(out)


def docker_image_digest(image: str) -> str | None:
    """Return the repo-digest (sha256:...) of a local docker image, if present.

    Tries RepoDigests first (the pushed/pulled digest), falls back to the local
    image Id. Returns None if docker is unavailable or the image is absent.
    """
    if not image:
        return None
    digest = _run(["docker", "inspect", "--format", "{{index .RepoDigests 0}}", image])
    if digest and "@" in digest:
        return digest.split("@", 1)[1]
    if digest and digest.startswith("sha256:"):
        return digest
    image_id = _run(["docker", "inspect", "--format", "{{.Id}}", image])
    return image_id


def file_sha256(path: Path) -> str | None:
    try:
        return ids.sha256_bytes(Path(path).read_bytes())
    except OSError:
        return None


def vendored_car_bench_dir() -> Path:
    return repo_root() / "third_party" / "car-bench"


def capture(
    *,
    scenario_path: Path,
    execution_mode: str,
    evaluator_image: str | None,
    agent_image: str | None,
    task_split: str,
    seeds: dict[str, Any] | None,
    compose_project: str | None = None,
    ports: dict[str, int] | None = None,
) -> dict[str, Any]:
    """Assemble the ``provenance`` block for a run manifest."""
    root = repo_root()
    car_bench = vendored_car_bench_dir()
    return {
        "scenario_resolved_path": str(scenario_path.name),
        "scenario_sha256": file_sha256(scenario_path),
        "execution_mode": execution_mode,
        "agent_image": agent_image,
        "agent_image_digest": docker_image_digest(agent_image) if agent_image else None,
        "evaluator_image": evaluator_image,
        "evaluator_image_digest": docker_image_digest(evaluator_image) if evaluator_image else None,
        "dataset_split": task_split,
        "dataset_version": (
            f"car-bench@{git_sha(car_bench)}" if git_sha(car_bench) else None
        ),
        "harness_git_sha": git_sha(root),
        "tracker_git_sha": git_sha(root),  # tracker lives in the same repo as the harness
        "car_bench_git_sha": git_sha(car_bench),
        "repo_dirty": git_dirty(root),
        "seeds": seeds or {},
        "compose_project": compose_project,
        "ports": ports or {},
    }
