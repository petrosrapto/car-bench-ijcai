"""Build, publish, promote, and package agent checkpoints for submission.

A *checkpoint* is a built, content-addressed agent image recorded against a
``variant_ref`` (digest = source of truth), with build provenance and links to
the validation runs that justify it. ``make_submission`` turns a promoted
checkpoint into the exact three artifacts the competition wants (see
docs/submission.md): a digest-pinned ``scenario.toml`` (env-var NAMES only),
a ``reproducibility.md``, and an auto-generated ``validation_table.md``.

build/publish shell out to docker and are environment-dependent; they degrade
gracefully (record what they can) when docker is unavailable.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from . import ids, paths, provenance, registry

EVALUATOR_IMAGE = "ghcr.io/car-bench/car-bench-evaluator:latest"
DEFAULT_DOCKERFILE = "src/track_1_agent_under_test/Dockerfile.track-1-agent-under-test"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


# --- build / publish ------------------------------------------------------

def record_build(variant_ref: str, *, image: str, dockerfile: str = DEFAULT_DOCKERFILE,
                 build_args: dict[str, str] | None = None) -> dict[str, Any]:
    """Capture a reproducibility-build record for a checkpoint (no docker call)."""
    root = paths.repo_root()
    lock = root / "uv.lock"
    build = {
        "image": image,
        "dockerfile": dockerfile,
        "build_git_sha": provenance.git_sha(root),
        "uv_lock_sha256": provenance.file_sha256(lock),
        "base_image": _dockerfile_base(root / dockerfile),
        "build_args": build_args or {},
        "built_at": _now_iso(),
        "image_digest": provenance.docker_image_digest(image),
    }
    ckpt_dir = paths.checkpoint_dir(variant_ref)
    ckpt_dir.mkdir(parents=True, exist_ok=True)
    (ckpt_dir / "build.json").write_text(json.dumps(build, indent=2, sort_keys=True), encoding="utf-8")
    registry.set_variant_lifecycle(variant_ref, "built", image=image,
                                   image_digest=build["image_digest"])
    _write_checkpoint(variant_ref, image=image, image_digest=build["image_digest"], build=build)
    return build


def record_publish(variant_ref: str, *, image: str) -> dict[str, Any]:
    """Record the pushed image digest (the value every scenario.toml pins)."""
    digest = provenance.docker_image_digest(image)
    _write_checkpoint(variant_ref, image=image, image_digest=digest)
    registry.set_variant_lifecycle(variant_ref, "built", image=image, image_digest=digest)
    return {"image": image, "image_digest": digest}


def promote(variant_ref: str) -> dict[str, Any]:
    """Mark a validated checkpoint as a submission candidate (gate: a test run)."""
    test_runs = [
        r for r in registry.runs_for_variant(variant_ref)
        if r.get("task_split") in ("test", "hidden") and r.get("status") != "failed"
    ]
    if not test_runs:
        raise ValueError(
            f"cannot promote {variant_ref}: no completed test/hidden run to justify it"
        )
    registry.set_variant_lifecycle(variant_ref, "promoted",
                                   promoted_run_ids=[r["run_id"] for r in test_runs])
    ckpt = _read_checkpoint(variant_ref) or {}
    ckpt.pop("variant_ref", None)  # avoid colliding with the positional arg below
    ckpt["validation_run_ids"] = [r["run_id"] for r in test_runs]
    _write_checkpoint(variant_ref, **ckpt)
    return _read_checkpoint(variant_ref) or {}


def _write_checkpoint(variant_ref: str, **fields: Any) -> None:
    ckpt_dir = paths.checkpoint_dir(variant_ref)
    ckpt_dir.mkdir(parents=True, exist_ok=True)
    path = ckpt_dir / "checkpoint.json"
    existing = _read_checkpoint(variant_ref) or {}
    existing.update({"variant_ref": variant_ref, **fields})
    path.write_text(json.dumps(existing, indent=2, sort_keys=True, default=str), encoding="utf-8")


def _read_checkpoint(variant_ref: str) -> dict[str, Any] | None:
    path = paths.checkpoint_dir(variant_ref) / "checkpoint.json"
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def _dockerfile_base(path: Path) -> str | None:
    try:
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.strip().upper().startswith("FROM "):
                return line.split()[1]
    except OSError:
        return None
    return None


# --- submission packaging -------------------------------------------------

def make_submission(variant_ref: str, *, team_image: str | None = None) -> Path:
    """Emit experiments/submissions/<id>/ with the three required artifacts."""
    version = registry.get_variant_version(variant_ref)
    if not version:
        raise KeyError(f"variant_ref not found: {variant_ref}")
    ckpt = _read_checkpoint(variant_ref) or {}
    image = team_image or ckpt.get("image") or version.get("image")
    digest = ckpt.get("image_digest") or version.get("image_digest")
    if not image:
        raise ValueError(f"{variant_ref} has no built image — run cbtrack build/publish first")
    pinned = _pin_image(image, digest)

    vid, ver = ids.split_variant_ref(variant_ref)
    submission_id = f"{ids.slug(vid)}__{ver}"
    out = paths.submission_dir(submission_id)
    out.mkdir(parents=True, exist_ok=True)

    env_contract = version.get("env_contract") or {"required": ["AGENT_LLM"], "optional": []}
    (out / "scenario.toml").write_text(_render_submission_toml(pinned, env_contract), encoding="utf-8")
    (out / "reproducibility.md").write_text(_render_reproducibility(variant_ref, version, ckpt, pinned), encoding="utf-8")
    (out / "validation_table.md").write_text(_render_validation_table(variant_ref), encoding="utf-8")
    manifest = {
        "submission_id": submission_id,
        "variant_ref": variant_ref,
        "image": pinned,
        "created_at": _now_iso(),
        "validation_run_ids": ckpt.get("validation_run_ids", []),
    }
    (out / "manifest.json").write_text(json.dumps(manifest, indent=2, sort_keys=True), encoding="utf-8")
    try:
        registry.set_variant_lifecycle(variant_ref, "submitted", submission_id=submission_id)
    except KeyError:
        pass
    return out


def _pin_image(image: str, digest: str | None) -> str:
    if "@sha256:" in image:
        return image
    if digest and digest.startswith("sha256:"):
        repo = image.split("@", 1)[0].split(":", 1)[0]
        return f"{repo}@{digest}"
    return image  # best effort; flagged in reproducibility.md if unpinned


def _render_submission_toml(image: str, env_contract: dict[str, Any]) -> str:
    req = env_contract.get("required", [])
    opt = env_contract.get("optional", [])
    lines = [
        "# Generated by cbtrack — env vars are NAMES ONLY (no secret values).",
        '[evaluator]',
        f'image = "{EVALUATOR_IMAGE}"',
        "",
        "[evaluator.env]",
        'GEMINI_API_KEY = "${GEMINI_API_KEY:?Set GEMINI_API_KEY}"',
        'LOGURU_LEVEL = "${LOGURU_LEVEL:-INFO}"',
        "",
        "[agent_under_test]",
        f'image = "{image}"',
        "",
        "[agent_under_test.env]",
    ]
    for name in req:
        lines.append(f'{name} = "${{{name}:?Set {name}}}"')
    for name in opt:
        lines.append(f'{name} = "${{{name}:-}}"')
    lines += [
        "",
        "[config]",
        "num_trials = 3",
        'task_split = "hidden"',
        "tasks_base_num_tasks = -1",
        "tasks_hallucination_num_tasks = -1",
        "tasks_disambiguation_num_tasks = -1",
        "max_steps = 50",
        "",
    ]
    return "\n".join(lines)


def _render_reproducibility(variant_ref: str, version: dict[str, Any], ckpt: dict[str, Any], pinned: str) -> str:
    build = ckpt.get("build", {}) or {}
    unpinned_warn = "" if "@sha256:" in pinned else (
        "\n> ⚠️ Image is NOT digest-pinned (build/publish to GHCR to capture a digest "
        "before official submission).\n"
    )
    return (
        f"# Reproducibility — `{variant_ref}`\n{unpinned_warn}\n"
        f"- **Agent image**: `{pinned}`\n"
        f"- **Evaluator image**: `{EVALUATOR_IMAGE}` (official, immutable)\n"
        f"- **Build git SHA**: `{build.get('build_git_sha')}`\n"
        f"- **Base image**: `{build.get('base_image')}`\n"
        f"- **uv.lock sha256**: `{build.get('uv_lock_sha256')}`\n"
        f"- **Model (AGENT_LLM)**: `{version.get('agent_llm')}`\n"
        f"- **Scaffold**: `{version.get('scaffold_kind')}`\n"
        f"- **Dockerfile**: `{build.get('dockerfile')}`\n\n"
        f"Rebuild: `cbtrack build {ids.split_variant_ref(variant_ref)[0]}` "
        f"at git `{build.get('build_git_sha')}` reproduces this image.\n"
    )


def _render_validation_table(variant_ref: str) -> str:
    """Pull headline numbers per validation run for the report's results table."""
    rows = registry.runs_for_variant(variant_ref)
    rows = [r for r in rows if r.get("task_split") in ("test", "hidden")]
    header = (
        "# Validation results — `%s`\n\n"
        "| run_id | split | Pass^3 | Pass@3 |\n|---|---|---|---|\n" % variant_ref
    )
    body = "".join(
        f"| `{r['run_id']}` | {r.get('task_split')} | "
        f"{_fmt(r.get('pass_power_3'))} | {_fmt(r.get('pass_at_3'))} |\n"
        for r in rows
    )
    return header + (body or "| _(no test runs)_ | | | |\n")


def _fmt(x: Any) -> str:
    return f"{x:.3f}" if isinstance(x, (int, float)) else "—"
