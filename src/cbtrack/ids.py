"""Stable, content-addressed identifiers for runs and agent variants.

These IDs are the backbone of FAIR-Findability: every run and every variant
version is referenced by a deterministic, collision-resistant key.

  run_id      = <UTCcompactTs>__<variant_id>__<config_hash8>__<rand4>
  config_hash = sha256(canonical(resolved [config] + task_split + filters))[:8]
  variant_ref = <variant_id>@<ver_hash8>
  ver_hash    = sha256(canonical(reproducible identity tuple))[:8]

Determinism note: we never call Date.now()/random implicitly inside hashing.
``new_run_id`` takes an explicit timestamp + an explicit random suffix so the
caller controls all non-determinism (important for reproducible/resumable runs).
"""

from __future__ import annotations

import hashlib
import json
import re
from typing import Any, Mapping

_SLUG_RE = re.compile(r"[^a-z0-9]+")


def slug(text: str, default: str = "x") -> str:
    """Lowercase, hyphenated, filesystem-safe slug."""
    s = _SLUG_RE.sub("-", str(text).strip().lower()).strip("-")
    return s or default


def _canonical(obj: Any) -> str:
    """Stable JSON serialization for hashing (sorted keys, no whitespace drift)."""
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), default=str)


def sha256_hex(obj: Any) -> str:
    return hashlib.sha256(_canonical(obj).encode("utf-8")).hexdigest()


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


# --- config hash ----------------------------------------------------------

# The keys from a scenario [config] block that define "which evaluation" ran.
CONFIG_HASH_KEYS = (
    "num_trials",
    "task_split",
    "max_steps",
    "tasks_base_num_tasks",
    "tasks_hallucination_num_tasks",
    "tasks_disambiguation_num_tasks",
    "tasks_base_task_id_filter",
    "tasks_hallucination_task_id_filter",
    "tasks_disambiguation_task_id_filter",
    "user_model",
    "policy_evaluator_model",
)


def config_hash(config: Mapping[str, Any]) -> str:
    """8-hex hash over the evaluation-defining config fields (order-independent)."""
    canonical = {k: config[k] for k in CONFIG_HASH_KEYS if k in config and config[k] is not None}
    return sha256_hex(canonical)[:8]


# --- variant identity -----------------------------------------------------

# The orthogonal axes that make two agent implementations "different".
VARIANT_IDENTITY_KEYS = (
    "image_digest",
    "agent_llm",
    "agent_thinking",
    "agent_reasoning_effort",
    "agent_interleaved_thinking",
    "agent_temperature",
    "system_prompt_sha256",
    "scaffold_kind",
    "harness_git_sha",
)


def variant_version_hash(identity: Mapping[str, Any]) -> str:
    """8-hex hash over the reproducible identity tuple of one variant version."""
    canonical = {k: identity.get(k) for k in VARIANT_IDENTITY_KEYS}
    return sha256_hex(canonical)[:8]


def variant_ref(variant_id: str, identity: Mapping[str, Any]) -> str:
    return f"{slug(variant_id)}@{variant_version_hash(identity)}"


def split_variant_ref(ref: str) -> tuple[str, str]:
    """('planner-x@7c1d9a02') -> ('planner-x', '7c1d9a02')."""
    if "@" not in ref:
        return ref, ""
    vid, ver = ref.rsplit("@", 1)
    return vid, ver


# --- run identity ---------------------------------------------------------

def new_run_id(*, timestamp_compact: str, variant_id: str, cfg_hash: str, rand4: str) -> str:
    """Compose a run_id from explicit parts (caller supplies ts + randomness).

    timestamp_compact: e.g. "20260618T142233Z" (UTC, no separators in fields).
    rand4: 4 hex chars of randomness (caller-provided -> deterministic on resume).
    """
    return f"{timestamp_compact}__{slug(variant_id)}__{cfg_hash}__{rand4}"
