"""Render a scenario TOML for one run from a variant spec + run config.

Two execution modes:
  * ``local``  — evaluator + agent run as local python processes. We allocate a
    free ``(evaluator, agent)`` port pair per run so concurrent runs never clash
    on the hard-coded 8080/8081 of the stock scenarios (parallelism-ready now).
  * ``docker`` — official evaluator image + agent image (Phase 3 wiring lives in
    runner.py via ``docker compose -p``); here we just emit the table shape.

The rendered TOML matches ``agentbeats.run_scenario.parse_toml`` exactly:
``[evaluator]``/``[agent_under_test]`` carry ``endpoint`` + ``cmd`` (host/port are
derived from ``endpoint``), and ``[config]`` is passed through verbatim.
"""

from __future__ import annotations

import socket
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

try:  # tomli_w is in the dev group; degrade to a tiny writer if absent.
    import tomli_w  # type: ignore
    _HAVE_TOMLI_W = True
except Exception:  # pragma: no cover
    _HAVE_TOMLI_W = False


DEFAULT_AGENT_MODULE = "src/track_1_agent_under_test/server.py"
DEFAULT_EVALUATOR_MODULE = "src/evaluator/server.py"
EVALUATOR_IMAGE = "ghcr.io/car-bench/car-bench-evaluator:latest"
DOCKER_PORT = 9009  # internal container port used by generate_compose.py (isolated network)


@dataclass
class RunConfig:
    """The ``[config]`` block — which tasks/trials this run evaluates."""

    num_trials: int = 3
    task_split: str = "test"
    max_steps: int = 50
    tasks_base_num_tasks: int = -1
    tasks_hallucination_num_tasks: int = -1
    tasks_disambiguation_num_tasks: int = -1
    tasks_base_task_id_filter: list[str] | None = None
    tasks_hallucination_task_id_filter: list[str] | None = None
    tasks_disambiguation_task_id_filter: list[str] | None = None
    user_model: str | None = None
    policy_evaluator_model: str | None = None

    def to_toml_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {
            "num_trials": self.num_trials,
            "task_split": self.task_split,
            "max_steps": self.max_steps,
            "tasks_base_num_tasks": self.tasks_base_num_tasks,
            "tasks_hallucination_num_tasks": self.tasks_hallucination_num_tasks,
            "tasks_disambiguation_num_tasks": self.tasks_disambiguation_num_tasks,
        }
        for key in (
            "tasks_base_task_id_filter",
            "tasks_hallucination_task_id_filter",
            "tasks_disambiguation_task_id_filter",
            "user_model",
            "policy_evaluator_model",
        ):
            val = getattr(self, key)
            if val is not None:
                out[key] = val
        return out


@dataclass
class AgentSpec:
    """How to launch / identify the agent under test for one run."""

    name: str = "track_1_agent_under_test"
    # local mode
    agent_module: str = DEFAULT_AGENT_MODULE
    agent_llm: str | None = None
    extra_cli: list[str] = field(default_factory=list)
    # docker mode
    image: str | None = None
    env: dict[str, str] = field(default_factory=dict)


SMOKE = RunConfig(
    num_trials=1,
    task_split="train",
    tasks_base_num_tasks=1,
    tasks_hallucination_num_tasks=1,
    tasks_disambiguation_num_tasks=1,
)
TEST_SET = RunConfig(num_trials=3, task_split="test")
HIDDEN_SET = RunConfig(num_trials=3, task_split="hidden")


def find_free_port_pair(base: int = 18000) -> tuple[int, int]:
    """Bind-test for a free (evaluator, agent) pair starting near ``base``.

    Binding the sockets, reading the OS-assigned ports, then closing avoids the
    hard-coded 8080/8081 collision when multiple runs launch concurrently.
    """
    def _free() -> int:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
        s.close()
        return port

    evaluator_port = _free()
    agent_port = _free()
    while agent_port == evaluator_port:
        agent_port = _free()
    return evaluator_port, agent_port


def render_local(
    *,
    agent: AgentSpec,
    config: RunConfig,
    evaluator_port: int,
    agent_port: int,
    host: str = "127.0.0.1",
) -> dict[str, Any]:
    """Build the scenario dict for local-python execution."""
    agent_cmd = [
        "python", agent.agent_module,
        "--host", host, "--port", str(agent_port),
    ]
    if agent.agent_llm:
        agent_cmd += ["--agent-llm", agent.agent_llm]
    agent_cmd += list(agent.extra_cli)

    evaluator_cmd = [
        "python", DEFAULT_EVALUATOR_MODULE,
        "--host", host, "--port", str(evaluator_port),
    ]
    return {
        "evaluator": {
            "endpoint": f"http://{host}:{evaluator_port}",
            "cmd": " ".join(evaluator_cmd),
        },
        "agent_under_test": {
            "endpoint": f"http://{host}:{agent_port}",
            "cmd": " ".join(agent_cmd),
            "name": agent.name,
            "result_model": agent.agent_llm or agent.name,
        },
        "config": config.to_toml_dict(),
    }


def render_docker(*, agent: AgentSpec, config: RunConfig) -> dict[str, Any]:
    """Build the scenario dict for docker execution (image-based)."""
    if not agent.image:
        raise ValueError("docker mode requires AgentSpec.image")
    return {
        "evaluator": {
            "image": EVALUATOR_IMAGE,
            "env": {"GEMINI_API_KEY": "${GEMINI_API_KEY:?Set GEMINI_API_KEY}"},
        },
        "agent_under_test": {
            "image": agent.image,
            "name": agent.name,
            "env": agent.env or {},
        },
        "config": config.to_toml_dict(),
    }


def write_toml(data: dict[str, Any], path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    if _HAVE_TOMLI_W:
        with path.open("wb") as f:
            tomli_w.dump(data, f)
    else:  # pragma: no cover - fallback writer
        path.write_text(_dump_toml(data), encoding="utf-8")
    return path


def _dump_toml(data: dict[str, Any]) -> str:
    """Minimal TOML writer (only the shapes we emit): tables of scalars/lists."""
    import json as _json

    lines: list[str] = []
    for table, body in data.items():
        lines.append(f"[{table}]")
        for key, val in body.items():
            if isinstance(val, dict):
                inner = ", ".join(f'{k} = {_json.dumps(v)}' for k, v in val.items())
                lines.append(f"{key} = {{ {inner} }}")
            else:
                lines.append(f"{key} = {_json.dumps(val)}")
        lines.append("")
    return "\n".join(lines)
