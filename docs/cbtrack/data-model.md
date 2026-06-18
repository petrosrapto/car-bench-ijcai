# cbtrack data model

The canonical reference for cbtrack's identifiers, manifests, and the normalized
store. Field names mirror the **native CAR-bench result schema** (verified against
`src/evaluator/car_bench_evaluator.py` and `car_bench/envs/reward_calculators.py`)
so nothing is lost in translation. The JSON Schemas under
`src/cbtrack/schemas/` (copied to `experiments/schemas/` at runtime) are the
machine-readable form of this document.

## Identifiers (`src/cbtrack/ids.py`)

| ID | Form | Definition |
|---|---|---|
| `run_id` | `<UTCts>__<variant_id>__<config_hash8>__<rand4>` | Time-sortable, filesystem-safe, collision-proof. |
| `config_hash` | 8 hex | `sha256` over the evaluation-defining config (`num_trials`, `task_split`, `max_steps`, per-type counts/filters, user/judge models). Groups "same eval, different method". |
| `variant_ref` | `<variant_id>@<ver_hash8>` | A specific immutable configuration of a method. |
| `ver_hash` | 8 hex | `sha256` over the reproducible identity tuple: `image_digest, agent_llm, agent_thinking, agent_reasoning_effort, agent_interleaved_thinking, agent_temperature, system_prompt_sha256, scaffold_kind, harness_git_sha`. |

A **variant** is a stable idea (`variant_id`); each immutable config is a
**version** (`variant_ref`). Runs reference a `variant_ref`; the variant evolves
independently — this is what makes a heterogeneous "method" a first-class,
versioned, reproducible entity.

## RUN manifest — `experiments/runs/<run_id>/manifest.json`

```
run_id, variant_ref, variant_id, status            # status: queued|running|completed|failed|partial
created_at, started_at, completed_at, config_hash
eval { num_trials, task_split, max_steps, tasks_*_num_tasks, tasks_*_task_id_filter, user_model, policy_evaluator_model }
provenance {                                        # the gap the native harness does NOT record
  scenario_sha256, agent_image, agent_image_digest,
  evaluator_image, evaluator_image_digest,
  dataset_version, dataset_split,
  harness_git_sha, tracker_git_sha, car_bench_git_sha, repo_dirty,
  seeds { agent_seed, user_model, policy_evaluator_model },
  execution_mode, compose_project, ports { evaluator, agent_under_test }
}
agent_metadata { ... }                              # copied verbatim from native metadata
result_json_path                                    # -> verbatim copy of the native payload
headline { pass_power_k, pass_at_k, by_split, recomputed, consistency_gap_pass3,
           mean_cost, mean_total_tokens, mean_a2a_task_time_s, n_tasks_by_split }
tags[], hypothesis, notes, harness_returncode
```

Run dir siblings: `result.json` (verbatim native payload), `scenario.resolved.toml`,
`env.captured.json` (secret-scrubbed), `logs/`.

## VARIANT manifest — `experiments/variants/<variant_id>/variant.json`

```
variant_id, versions[ {
  variant_ref, created_at, lifecycle,               # lifecycle: draft|built|validated|promoted|submitted
  image, image_digest, agent_llm, agent_thinking, agent_reasoning_effort,
  agent_interleaved_thinking, agent_temperature, system_prompt_sha256,
  scaffold_kind, harness_git_sha, source_dir,
  env_contract { required[], optional[] },          # env-var NAMES only (for submission rendering)
  build { dockerfile, base_image, build_git_sha, uv_lock_sha256, build_args, image_digest }
} ]
```

## CHECKPOINT — `experiments/checkpoints/<variant_ref>/`

`checkpoint.json` links the built image ref+digest, `build.json` provenance, any
baked artifacts under `artifacts/` (sha256'd; LFS for binaries), and the
`validation_run_ids` that justify promotion. The GHCR **image digest** is the
source of truth.

## Normalized store tables (`src/cbtrack/store.py`)

DuckDB exposes typed tables (stable schema even when empty) + Parquet copies.

### `task_trials` — one row per task × trial (analytical core)

Keys: `run_id, variant_ref, variant_id, split, task_id, trial, task_type, persona`.
Outcome: `reward, passed` (`reward >= 0.99`), `error`.
Subscores (literal `reward_info.info` keys; `DOUBLE`, NULL = not applicable —
hallucination tasks NULL the action/tool_subset/policy scores):
`r_actions, r_actions_final, r_actions_intermediate, r_tool_subset,
r_tool_execution, r_policy, r_user_end_conversation`.
Diagnostics (`VARCHAR[]` / `VARCHAR`): `tool_subset_missing_tools,
tool_execution_errors, policy_llm_errors, policy_aut_errors,
end_conversation_keyword`.
Economics: `agent_{input,output,prompt,completion,thinking,total}_tokens,
total_agent_cost, total_llm_latency_ms, total_a2a_time_ms, a2a_task_time_s, num_turns`.

### `turns` — one row per trajectory message (powers replay)

`run_id, split, task_id, trial, turn_idx, role, content, name, tool_call_id,
tool_calls(json), prompt_tokens, completion_tokens, thinking_tokens, cost, model,
num_llm_calls, avg_llm_call_time_ms, quota_wait_time_ms, a2a_turn_time_ms`.

### `runs` — one row per run · `variants` — one row per variant version

Headline metrics + identity + provenance, flattened for fast leaderboard/trend queries.

### Derived views

- `policy_violations(run_id, split, task_id, trial, policy_id, source)` — unnest of `policy_aut_errors` (AUT) + `policy_llm_errors` (LLM).
- `tool_errors(run_id, split, task_id, trial, detail, source)` — unnest of `tool_execution_errors` (execution) + `tool_subset_missing_tools` (missing_subset).

### Pass^k / Pass@k

Recomputed from `task_trials` by grouping over the 3 trials per `(split, task_id)`:
`Pass^k = MIN(passed)`, `Pass@k = MAX(passed)`. Computed on any filtered subset so
the dashboard never has to trust only the precomputed scores.

## FAIR mapping

- **Findable** — stable `run_id`/`variant_id` + the append-only `registry/{runs,variants}.jsonl` indexes (git-tracked).
- **Accessible** — plain JSON/JSONL/TOML/Parquet on local disk; no server needed to read.
- **Interoperable** — every artifact carries a `$schema` pointer; Parquet/DuckDB are tool-agnostic.
- **Reusable** — `manifest.json` carries full provenance; `result.json` is the verbatim native payload.
