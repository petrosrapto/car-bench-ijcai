# CAR-bench Experiment Tracking + Visualization (FAIR)

## Context

You are building an agent for the **CAR-bench IJCAI Open Track** (goal: maximize Pass^3 on a hidden test set). You will run **many** evaluation experiments over time and need to (a) **persist every run with full metadata** so it is reproducible, (b) **visualize past interaction trajectories** in a frontend, and (c) **see per-method statistics** to compare approaches. In the future you want to run experiments **in parallel across heterogeneous agent variants** (different code/scaffold/model). Everything should follow **FAIR** (Findable, Accessible, Interoperable, Reusable).

**What the cloned kit already does (verified against source):**
- Run flow: `uv run car-bench-run <scenario.toml> [output_dir]` → [run_scenario.py](repos/car-bench-ijcai/src/agentbeats/run_scenario.py) spawns evaluator + agent-under-test + an A2A client ([client_cli.py](repos/car-bench-ijcai/src/agentbeats/client_cli.py)) that drives the eval and writes **one JSON** per run to `output/<agent>/<ts>__<scenario>__<task-selection>__<model>__<reasoning>.json`. `output/` is **gitignored**.
- That JSON ([client_cli.py:462](repos/car-bench-ijcai/src/agentbeats/client_cli.py#L462)) has `metadata` (schema_version 1, timestamps, scenario, model, reasoning_effort, config) + `final_result` (Pass^k/Pass@k overall & by-split, plus `detailed_results_by_split` with full per-task/per-trial trajectories and per-subscore `reward_info`).
- Visualization today = [plot_results.py](repos/car-bench-ijcai/outputs/plot_results.py): **static** matplotlib PNG/PDF, grouped by `model`/`reasoning_effort`, 2×2 panels (overall + 3 splits) for Pass^3 / latency / tokens. No interactive frontend, no trajectory replay, no per-subscore/policy/tool stats.

**The gaps this plan fills:** no run ID, no git SHA / image digest / dataset+evaluator version / seeds, no tags/hypothesis, no first-class "method" identity beyond a model string; results are overwrite-only and not tracked; no interactive stats or trajectory viewer; not parallelism-ready.

## Integration approach — fork `car-bench-ijcai`, integrate the tracker in-repo

We **fork** the competition kit (`repos/car-bench-ijcai` becomes your repo: add your own remote, keep upstream as a remote for future pulls) and add the tracker as first-class subpackages **inside** it. This is the natural home: you already edit `src/track_1_agent_under_test/` to build agent variants and you build/push agent images from this repo. Forking simplifies everything — direct Python imports of `plot_results.py` extractors (no `sys.path`/subprocess hacks), the ability to **close the metadata gap at the source** in `client_cli.py`, and one repo to version code + experiments together.

**The one invariant we keep:** do **not** modify the **evaluator boundary** — `src/evaluator/` and the vendored `car-bench` environment (`third_party/car-bench/`, fetched by [setup_car_bench.sh](repos/car-bench-ijcai/scripts/setup_car_bench.sh)). Scoring, the simulated user, the tools, and the reward logic must stay byte-for-byte identical to the official evaluator image, or local results stop being comparable to the official scoring used at submission. We record the vendored `car-bench` version for provenance; we never patch it. Everything else in the fork is fair game.

**Decisions (confirmed):** Fork the kit (not a sibling wrapper). Frontend = **FastAPI + React**. Store = **local file registry + DuckDB/Parquet**. Parallelism = **design-for-later** (sequential now, schema parallelism-ready so the orchestrator adds with zero migration).

---

## Directory layout (everything inside the fork)

```
repos/car-bench-ijcai/               # YOUR FORK (upstream tracked as a remote)
├── src/
│   ├── evaluator/                   # UNTOUCHED (evaluator boundary invariant)
│   ├── agentbeats/                  # client_cli.py / run_scenario.py — light, additive edits only
│   ├── track_1_agent_under_test/    # your agent variants live/grow here
│   └── cbtrack/                     # NEW tracker package
│       ├── ids.py                   # run_id / config_hash / variant_ref hashing
│       ├── provenance.py            # git SHA, docker image digest, env scrub, dataset/evaluator version, seeds
│       ├── scenario_gen.py          # render scenario TOML from variant + run-config; dynamic ports
│       ├── runner.py                # `cbtrack run`: call run_scenario in-process; write manifest; ingest
│       ├── ingest.py                # native JSON -> normalized Parquet (imports plot_results extractors directly)
│       ├── store.py                 # build/refresh DuckDB views over Parquet
│       ├── registry.py              # variants + runs index (append-only JSONL)
│       ├── plot_export.py           # wraps outputs/plot_results.py for static report export
│       └── schemas/*.schema.json    # JSON Schema for manifests + normalized tables
├── api/                             # NEW FastAPI backend (read API over DuckDB + run files)
│   ├── main.py  deps.py
│   └── routers/{runs,variants,stats,trajectory}.py
├── web/                             # NEW React (Vite + TS) frontend
│   └── src/{pages,components,api}/
├── outputs/plot_results.py          # reused (imported by ingest + plot_export)
├── docs/                            # upstream docs (a2a-introduction.md, ...) — left as-is
│   └── cbtrack/                     # NEW: all our docs, namespaced to avoid upstream merge noise
│       ├── PLAN.md                  # this plan, committed into the repo (living design doc)
│       ├── README.md                # docs index: links the plan + every ADR + topic doc
│       ├── data-model.md            # manifest/variant/normalized-table schemas, FAIR mapping
│       ├── runbook.md               # how to run cbtrack, backfill, start api/web, verify
│       └── adr/                     # Architecture Decision Records (MADR format)
│           ├── 0001-fork-and-integrate-in-repo.md
│           ├── 0002-evaluator-boundary-immutable.md
│           ├── 0003-store-duckdb-over-parquet.md
│           ├── 0004-frontend-fastapi-react.md
│           ├── 0005-fair-layout-run-and-variant-identity.md
│           ├── 0006-parallelism-design-for-later.md
│           └── 0007-provenance-and-secret-scrubbing.md
├── experiments/                     # NEW FAIR data tree (lives in the fork)
│   ├── registry/{variants,runs}.jsonl          # tracked in git (small, the index)
│   ├── variants/<variant_id>/{variant.json, CARD.md, prompt_<hash>.txt}
│   ├── runs/<run_id>/{manifest.json, scenario.resolved.toml, result.json, env.captured.json, logs/}
│   ├── checkpoints/<variant_ref>/{checkpoint.json, build.json, artifacts/}   # built+validated agent images (+ optional baked artifacts)
│   ├── submissions/<submission_id>/{scenario.toml, reproducibility.md, validation_table.md, manifest.json}  # ready-to-submit bundles
│   ├── store/{runs,variants,task_trials,turns}.parquet + carbench.duckdb   # gitignored (rebuildable)
│   └── schemas/                     # copied JSON Schemas (self-describing -> Interoperable)
└── pyproject.toml                   # add deps: duckdb, pyarrow, fastapi, uvicorn, pydantic, tomli-w, jsonschema; add `cbtrack` console script
```

**FAIR mapping:** Findable = stable `run_id`/`variant_id` + the two `.jsonl` indexes (git-tracked); Accessible = plain JSON/JSONL/TOML/Parquet on disk; Interoperable = every artifact carries a `$schema` pointer + Parquet/DuckDB are tool-agnostic; Reusable = `manifest.json` carries full provenance and `result.json` is the **verbatim** native payload. Large/rebuildable artifacts (`store/`, per-run `result.json`) are gitignored or LFS — the registry index stays tracked so runs are findable from git.

---

## 1. Identity, RUN manifest, VARIANT registry

**IDs** ([src/cbtrack/ids.py](repos/car-bench-ijcai/src/cbtrack/ids.py)):
- `run_id = <UTCcompactTs>__<variant_id>__<config_hash8>__<rand4>` — time-sortable, filesystem-safe.
- `config_hash` = sha256(canonical JSON of resolved `[config]` + `task_split` + task-id filters) → groups "same eval, different method".
- `variant_id` = human slug for the *idea* (stable). `variant_ref = <variant_id>@<ver_hash8>` where `ver_hash` = sha256 of the reproducible identity tuple `{image_digest, agent_llm, agent_thinking, agent_reasoning_effort, agent_interleaved_thinking, agent_temperature, system_prompt_sha, scaffold_kind, harness_git_sha}`. Change any axis → new version, same idea. **Runs reference a `variant_ref`; the variant evolves independently** — this is what makes a heterogeneous "method" first-class and powers "watch a method improve over its run history".

**RUN manifest** (`experiments/runs/<run_id>/manifest.json`) — key blocks:
- identity: `run_id, variant_ref, variant_id, status` (`queued|running|completed|failed|partial`), `config_hash`, timestamps.
- `eval`: the resolved `[config]` verbatim (`num_trials, task_split, tasks_*_num_tasks|*_task_id_filter, max_steps`).
- `provenance` (the gap-filler): `scenario_sha256, agent_image_digest, evaluator_image_digest, dataset_version (+split), harness_git_sha, car_bench_git_sha, tracker_git_sha, seeds{agent_seed,user_model,policy_evaluator_model}, execution_mode, compose_project, ports{evaluator,agent_under_test}`.
- `result_json_path` (→ verbatim copy), `headline` (computed: `pass_power_k`, `pass_at_k`, `by_split`, `consistency_gap_pass3 = Pass@3−Pass^3`, mean cost/tokens/latency), and `tags` / `hypothesis` / `notes`.

**VARIANT manifest** (`experiments/variants/<variant_id>/variant.json`): a `versions[]` array, each entry = one `variant_ref` with `scaffold_kind` (`bare|planner_executor|multipass|ensemble|...`), `image(+digest)`, `agent_llm`, thinking/reasoning/temperature, `system_prompt_sha256(+path)`, `harness_git_sha`, `source_dir`, plus three submission-facing blocks: `lifecycle` (`draft → built → validated → promoted → submitted`), `build` (Dockerfile path, base-image digest, `uv.lock` hash, build git SHA, build args — the **reproducibility build** record), and `env_contract` (declared `required`/`optional` env-var **names** with defaults, e.g. `AGENT_LLM` required, `AGENT_TEMPERATURE` optional — names only, never values). A brand-new agent codebase later = just a new `variant_id` with its own `scaffold_kind`/`source_dir` — no schema change.

**In-repo integration** ([src/cbtrack/runner.py](repos/car-bench-ijcai/src/cbtrack/runner.py)): a `cbtrack run` console command renders the TOML, **calls `agentbeats.run_scenario.main()` in-process** (direct import, no subprocess) pointed at `experiments/runs/<run_id>/`, then reads the native `metadata`/`final_result`, merges `provenance.py` output, writes `manifest.json`, appends to `registry/runs.jsonl`, and triggers `ingest.py` + `store.py`. **Optional source-level fix (recommended, light touch):** add a `--run-id`/provenance pass-through in [client_cli.py](repos/car-bench-ijcai/src/agentbeats/client_cli.py) so `run_id` + provenance are stamped directly into the native `metadata` block at write time — closing the gap at the source instead of only post-hoc. Kept additive so upstream merges stay clean.

---

## 2. Ingestion + queryable store (DuckDB over Parquet)

**Reuse, don't reimplement:** [src/cbtrack/ingest.py](repos/car-bench-ijcai/src/cbtrack/ingest.py) now **directly imports** from [outputs/plot_results.py](repos/car-bench-ijcai/outputs/plot_results.py) (`token_components_from_row`, `a2a_turn_times_from_row`, `a2a_task_time_from_row`, the per-turn fallbacks) — same in-repo package, no path hacks — so token/latency parsing is byte-identical to the official tooling.

**Normalized Parquet tables** (DuckDB exposes them as views; Parquet stays source of truth):
- `runs.parquet` — one row/run: identity + provenance + headline metrics + tags/hypothesis.
- `variants.parquet` — one row/variant version.
- `task_trials.parquet` — **one row per task × trial** (analytical core). Columns reuse the literal native keys from [reward_calculators.py](repos/car-bench/car_bench/envs/reward_calculators.py): `run_id, variant_ref, split, task_id, trial, task_type, persona, reward, r_actions_final, r_actions_intermediate, r_actions, r_tool_subset, r_tool_execution, r_policy, r_user_end_conversation` (nullable — hallucination tasks NULL the action/tool_subset/policy scores), list cols `tool_subset_missing_tools, tool_execution_errors, policy_llm_errors, policy_aut_errors, end_conversation_keyword`, and economics `agent_{input,output,prompt,completion,thinking,total}_tokens, total_agent_cost, total_llm_latency_ms, total_a2a_time_ms, a2a_task_time_s`.
- `turns.parquet` — **one row per trajectory turn** (powers replay): `run_id, split, task_id, trial, turn_idx, role, content, tool_calls(json), name, tool_call_id` + per-turn `turn_metrics` + `evaluator_metrics.a2a_turn_time_ms`.

**Derived DuckDB views** ([src/cbtrack/store.py](repos/car-bench-ijcai/src/cbtrack/store.py)): `policy_violations(run_id,split,task_id,trial,policy_id,source)` (unnest AUT/LLM policy errors) and `tool_errors(...)` (unnest tool errors / missing tools). Pass^3/Pass@3 are recomputed from `task_trials` by grouping over the 3 trials per `task_id` (`Pass^3 = MIN(reward)=1`, `Pass@3 = MAX(reward)=1`) so the dashboard can recompute on any filtered subset, not just trust the precomputed scores.

Why DuckDB+Parquet (not SQLite/MLflow/W&B): single local file, zero server, columnar `GROUP BY method × split × task_type × subscore × policy × tool × persona` in ms over ~254 tasks × 3 trials × N runs; Parquet stays portable; bootstrap CIs are a one-query pull + NumPy resample; data never leaves the machine.

---

## 3. Frontend — FastAPI + React

**Backend** ([api/main.py](repos/car-bench-ijcai/api/main.py)) — thin read API over DuckDB + the run files:
- `GET /api/runs`, `GET /api/runs/{run_id}`, `GET /api/variants`, `GET /api/variants/{id}` (version history).
- `GET /api/stats/headline?variant_ref=&split=` — Pass^3/Pass@3 + **bootstrap 95% CI** (resample task-level pass vectors; matters given high Pass^3 variance on ~254 tasks).
- `GET /api/stats/subscores?...` — among failed trials, culprit subscore breakdown, sliceable by split/task_type.
- `GET /api/stats/policies?...` (from `policy_violations`, split AUT-POL vs LLM-POL), `GET /api/stats/tools?...` (from `tool_errors`), `GET /api/stats/economics?...` (cost/tokens input-vs-output/latency).
- `GET /api/compare?variant_refs=a,b` — side-by-side headline + per-task win/loss diff + Pass^3-vs-Pass@3 consistency gap.
- `GET /api/trends?variant_id=` — metric across that variant's run history.
- `GET /api/trajectory/{run_id}/{split}/{task_id}/{trial}` — ordered turns + the trial verdict (each subscore pass/fail + the specific policy/tool errors) + ground-truth `actions` from `reward_info.info` for the diff view.

**React app** ([web/src](repos/car-bench-ijcai/web/src)) — Vite + TS, a small chart lib (Recharts/Plotly):
- **Methods** page — per-method headline bars with CIs; subscore failure breakdown; per-policy and per-tool violation charts; economics.
- **Compare** page — pick 2+ `variant_ref`s → headline side-by-side, per-task win/loss table, consistency-gap chart.
- **Trends** page — one `variant_id`'s metric over time (x = `completed_at`).
- **Trajectory** page — select `run_id → split → task_id → trial`; chat-style stream (system/user/assistant/`tool_calls`/tool results); per-turn token/latency/cost panel; a **verdict panel** (which subscore + which `policy_aut_errors`/`policy_llm_errors`/`tool_execution_errors` failed); and a **GT-actions diff** (expected `reward_info.info.actions` vs taken `tool_calls`) — the single most useful artifact for debugging Pass^3 failures.

**Static export still available:** [src/cbtrack/plot_export.py](repos/car-bench-ijcai/src/cbtrack/plot_export.py) wraps the existing `plot_results.py` to regenerate publication PNG/PDF figures on demand.

---

## 4. Parallelism-ready now, orchestrator later (design-for-later)

Built sequential now, but every run is **self-isolating** so the orchestrator adds with zero migration:
- [src/cbtrack/scenario_gen.py](repos/car-bench-ijcai/src/cbtrack/scenario_gen.py) never hardcodes 8080/8081 — it bind-tests a free port pair (e.g. `18000 + 2*slot`) and writes them into the rendered TOML `endpoint`/`cmd` and into `manifest.provenance.ports` (today's smoke/test TOMLs hard-bind those ports → concurrent local runs would collide).
- Docker mode (Phase 3): now that we own the repo, edit [generate_compose.py](repos/car-bench-ijcai/generate_compose.py) (or invoke `docker compose -p cb_<run_id8>`) to set a unique project name + per-run output mount at `experiments/runs/<run_id>/` instead of the shared `output/`. Distinct project + mount → no container/result clashes.
- `status`, `compose_project`, `ports` are in the manifest schema from v1; `registry/runs.jsonl` is **append-only**, so parallel runs land in the unified registry regardless of finish order.
- Later orchestrator = a `Queue` of `RunSpec`s + `ProcessPoolExecutor(max_workers=N)`, plus a separate `max_evaluator_concurrency` semaphore (the evaluator's Gemini user-simulator + policy-judge share quota; native payload already records `quota_wait_seconds` so the dashboard can flag quota-starved runs).

---

## 5. Provenance capture (exact mechanism)

[src/cbtrack/provenance.py](repos/car-bench-ijcai/src/cbtrack/provenance.py), all from sources we control:
- Image digests: `docker inspect --format '{{index .RepoDigests 0}}' <image>` for AUT + evaluator (local mode records `cmd` + harness SHA instead).
- Scenario hash: sha256 of the rendered `scenario.resolved.toml`.
- Dataset / env version: `git -C third_party/car-bench rev-parse HEAD` (the vendored, untouched env) + `task_split`; evaluator version = its pinned image digest.
- Seeds: set/record `agent_seed` + the configured `user_model`/`policy_evaluator_model` (the stochastic surfaces).
- Git SHAs for the fork (harness/tracker = one repo now) and the vendored `car-bench`.
- Env snapshot **scrubbed** to an `AGENT_*`/`CONFIG_*` allowlist, dropping anything matching `*_API_KEY|*_TOKEN|*_SECRET` → `env.captured.json`. Never persist secrets.

`result.json` (verbatim) + `manifest.json` together fully re-render and re-run the scenario.

---

## 6. Documentation & ADRs (decision provenance)

All project documentation lives under [docs/cbtrack/](repos/car-bench-ijcai/docs/cbtrack/) in the fork — namespaced so it never collides with upstream `docs/*.md` on future pulls. This is itself a FAIR-Reusable practice: every major decision is captured, dated, and linked, so the *why* survives next to the *what*.

- **The plan is a living doc:** this plan is committed to the repo as [docs/cbtrack/PLAN.md](repos/car-bench-ijcai/docs/cbtrack/PLAN.md) (kept in sync with the design as it evolves), with [docs/cbtrack/README.md](repos/car-bench-ijcai/docs/cbtrack/README.md) as the index that links the plan, the data-model doc, the runbook, and every ADR.
- **Topic docs:** `data-model.md` (the manifest/variant/normalized-table schemas + FAIR mapping, the canonical reference the JSON Schemas mirror) and `runbook.md` (run/backfill/serve/verify commands).
- **ADRs (one file per major decision)** in [docs/cbtrack/adr/](repos/car-bench-ijcai/docs/cbtrack/adr/), **MADR format** (`Status` · `Context` · `Decision` · `Consequences` · `Alternatives considered`), numbered `NNNN-title.md`:
  1. `0001-fork-and-integrate-in-repo` — fork `car-bench-ijcai` and host the tracker in-repo (vs a sibling wrapper); rationale: you already edit `src/` and build images from this repo, and direct imports beat `sys.path`/subprocess.
  2. `0002-evaluator-boundary-immutable` — never modify `src/evaluator/` or vendored `third_party/car-bench/`; rationale: keep local scoring identical to the official evaluator image (competition rule + comparability).
  3. `0003-store-duckdb-over-parquet` — DuckDB + Parquet + file registry (vs SQLite / MLflow / W&B); rationale: local-first, columnar slicing, portable, data stays on machine.
  4. `0004-frontend-fastapi-react` — FastAPI + React (vs Streamlit / static / notebooks); rationale: chosen for a polished, shareable interactive app.
  5. `0005-fair-layout-run-and-variant-identity` — the `run_id`/`config_hash` scheme and the **variant registry decoupled from runs**; rationale: makes a "method" a first-class, versioned, reproducible entity.
  6. `0006-parallelism-design-for-later` — parallelism-ready schema now (ports/compose_project/status, append-only registry), orchestrator later; rationale: zero-migration path, matches the "in the future" need.
  7. `0007-provenance-and-secret-scrubbing` — what provenance is recorded for reproducibility and the `*_API_KEY|*_TOKEN|*_SECRET` scrub rule; rationale: reproducible + FAIR-Accessible without leaking secrets.
  8. `0008-checkpoints-and-submission-packaging` — checkpoints = digest-pinned images keyed by `variant_ref` with build provenance + validation evidence, and `cbtrack submission` generates the digest-pinned `scenario.toml` + reproducibility bundle + validation table; rationale: the registry's identity already equals the submission identity, so packaging is a registry operation, not hand-assembly.

New ADRs are added for any future major decision (e.g. adopting a different agent scaffold, changing the scoring-comparison baseline). Superseded ADRs are marked `Status: Superseded by NNNN`, never deleted.

---

## 7. Submission reproducibility & agent checkpoints

Per [submission.md](submission.md), an official submission is exactly three things: a **public GHCR agent image pinned by digest**, a **`scenario.toml`** (official evaluator image + your agent image/config, env-var **names** only — `${VAR:?}`/`${VAR:-}`, never secret values), and a **4-page report with validation results/ablations**. This is precisely the registry's reproducible identity — a `variant_ref` already *is* `{image digest + config + env contract}`. So the tracker generates the submission instead of you hand-assembling it, and stores agent "checkpoints" as first-class registry objects.

**A "checkpoint" = a built, content-addressed agent image** (optionally plus baked artifacts) recorded against a `variant_ref`. The immutable source of truth is the **GHCR image digest**; any model artifacts a variant bakes in or references (a fine-tuned LoRA adapter, a frozen system-prompt file, a few-shot bank — fine-tuning is one of the suggested approaches) are stored under `experiments/checkpoints/<variant_ref>/artifacts/` with sha256 hashes, large/binary ones gitignored or in LFS. `checkpoint.json` links: the image ref+digest, the `build.json` provenance, the artifact hashes, and the **validation runs** (`run_id`s + their Pass^3/Pass@3 + CIs) that justify promotion. This is the "store checkpoints after validation, organized" the workflow needs — organized by `variant_ref`, evidenced by the runs that validated them.

**New CLI verbs** (in [src/cbtrack/](repos/car-bench-ijcai/src/cbtrack/), reusing the existing [Track-1 Dockerfile](repos/car-bench-ijcai/src/track_1_agent_under_test/Dockerfile.track-1-agent-under-test) and the [publish-ghcr workflow template](repos/car-bench-ijcai/.github/workflows/publish-ghcr.yml.disabled)):
- `cbtrack build <variant_id>` — build the agent image from the repo (frozen `uv.lock`), capture `build.json` provenance (git SHA, base-image digest, lock hash, build args); lifecycle `draft → built`.
- `cbtrack publish <variant_ref>` — push to GHCR (local `docker buildx`, or trigger the workflow), record the **digest** into the variant version; this digest is what every `scenario.toml` pins.
- `cbtrack promote <variant_ref>` — mark a validated checkpoint as a submission candidate, recording the justifying `run_id`s (gate: require a completed `task_split="test"` run); lifecycle `validated → promoted`.
- `cbtrack submission <variant_ref>` — emit `experiments/submissions/<submission_id>/`: (a) the digest-pinned **`scenario.toml`** (official evaluator + `agent@sha256:…` + `task_split="hidden"` + the variant's `env_contract` rendered as `${VAR:?}`/`${VAR:-}`, secret-scrubbed); (b) **`reproducibility.md`** (image digest, build git SHA, base image, `uv.lock` hash, build command — enough to rebuild bit-for-bit); (c) **`validation_table.md`** auto-generated from the store (Pass^3/Pass@3 per split + bootstrap CIs + the key ablations) to drop straight into the report; (d) `manifest.json` tying it to the `variant_ref` and runs. Lifecycle `promoted → submitted`.

This makes the experiment registry the single source from which a reproducible submission is produced with one command, and guarantees the submitted image/config is exactly the validated checkpoint (same digest the dashboard scored).

---

## Files to create / touch
- **New:** `src/cbtrack/{ids,provenance,scenario_gen,runner,ingest,store,registry,plot_export,build,publish,submission}.py` + `src/cbtrack/schemas/*.schema.json`; `api/main.py`, `api/deps.py`, `api/routers/{runs,variants,stats,trajectory,submissions}.py`; `web/` (Vite scaffold + pages/components above). `experiments/` is created at runtime.
- **Docs (committed):** `docs/cbtrack/{PLAN.md, README.md, data-model.md, runbook.md}` + `docs/cbtrack/adr/0001..0008-*.md` (eight ADRs).
- **Light additive edits (fork):** [pyproject.toml](repos/car-bench-ijcai/pyproject.toml) (deps + `cbtrack` console script); optionally [client_cli.py](repos/car-bench-ijcai/src/agentbeats/client_cli.py) (`--run-id`/provenance pass-through into native metadata); Phase 3 [generate_compose.py](repos/car-bench-ijcai/generate_compose.py) (project name + per-run mount). `.gitignore`: track `experiments/registry/` + `experiments/runs/**/manifest.json`, ignore `experiments/store/` and large `result.json` (or LFS).
- **Do NOT touch:** `src/evaluator/`, `third_party/car-bench/` (evaluator boundary invariant).

## Existing artifacts reused
- [outputs/plot_results.py](repos/car-bench-ijcai/outputs/plot_results.py) — token/latency/metric extractors (imported by `ingest.py`; wrapped by `plot_export.py`).
- [client_cli.py:462](repos/car-bench-ijcai/src/agentbeats/client_cli.py#L462) — native `metadata`/`final_result` schema we read (and optionally extend).
- [run_scenario.py](repos/car-bench-ijcai/src/agentbeats/run_scenario.py) — `main()` called in-process by `cbtrack run`.
- [reward_calculators.py](repos/car-bench/car_bench/envs/reward_calculators.py) — authoritative subscore key names.
- [local_test_set.toml](repos/car-bench-ijcai/scenarios/track_1_agent_under_test/local_test_set.toml) — template `scenario_gen.py` renders from.

---

## Phased build order
- **Phase 0 (docs skeleton, first):** create `docs/cbtrack/` with `PLAN.md` (this plan), `README.md` index, and ADRs `0001`–`0007` recording the decisions already made. Each subsequent phase updates the relevant ADR/topic doc as it lands — docs are written alongside code, not after.
- **Phase 1 (immediate value):** fork hygiene (add your remote, keep upstream remote, deps in `pyproject.toml`) → `provenance/ids/scenario_gen/runner` (sequential, local) → `ingest`+`store` (Parquet + DuckDB) → **backfill** the store from any existing `output/**/*.json` → FastAPI `stats/headline`, `subscores`, `trajectory` routes + React **Methods** and **Trajectory** pages (highest debugging value first).
- **Phase 2:** `registry.py` (variant versioning, CARD.md, tags/hypothesis) → **Compare** + **Trends** pages, policy/tool charts, bootstrap CIs, `plot_export` static button; optional `client_cli.py` source-level provenance stamping.
- **Phase 2.5 (submission pipeline):** `build.py`/`publish.py`/`submission.py` + `cbtrack {build,publish,promote,submission}` + the `submissions` API route and a small **Submission** panel in the web app (pick a promoted `variant_ref` → preview the generated `scenario.toml` + validation table). Delivers a one-command, reproducible hidden-set submission from a validated checkpoint.
- **Phase 3 (deferred):** Docker mode in `generate_compose.py` (`-p cb_<run_id>` + per-run mount + dynamic ports) → `Queue` + `ProcessPoolExecutor` + evaluator-concurrency semaphore + quota-wait surfacing. No schema migration (fields already present).

---

## Verification
1. **End-to-end single run:** `cbtrack run --variant <id> --config smoke` → confirm `experiments/runs/<run_id>/{manifest.json,result.json,scenario.resolved.toml,env.captured.json}` exist; assert `manifest.provenance` has non-empty git SHAs + image/evaluator digests + ports; assert `env.captured.json` contains **no** `*_API_KEY`.
2. **Store correctness:** open `experiments/store/carbench.duckdb`; verify `runs/variants/task_trials/turns` row counts; recompute Pass^3 from `task_trials` and assert it equals `final_result.pass_power_k_scores["Pass^3"]` in `result.json`.
3. **Backfill:** run `ingest.py` against an existing `output/**/*.json` and confirm it appears as a run in the dashboard with correct headline numbers.
4. **API + frontend:** `uvicorn api.main:app` + `npm run dev`; load Methods (bars + CIs match DuckDB), open a Trajectory (turns render in order; verdict panel shows the failing subscore; GT-diff shows expected vs taken actions for a known-failing task).
5. **Evaluator-boundary invariant:** `git -C repos/car-bench-ijcai diff upstream/main -- src/evaluator third_party` is empty (proves scoring path unchanged → local results comparable to the official image).
6. **Reproducibility:** from a manifest, re-render the scenario and re-run; confirm same `config_hash` and `variant_ref`, and a comparable Pass^3 (allowing for stochastic user/judge).
7. **Parallelism-ready check (no orchestrator yet):** two `scenario_gen` renders pick **different** ports + `compose_project` names + run dirs.
8. **Docs present:** `docs/cbtrack/PLAN.md` + ADRs `0001`–`0008` exist and `docs/cbtrack/README.md` links each; ADR statuses are `Accepted`.
9. **Submission bundle:** `cbtrack submission <promoted variant_ref>` produces `experiments/submissions/<id>/scenario.toml` with the official evaluator image, `agent@sha256:<digest>` (matching the checkpoint), `task_split="hidden"`, and env vars rendered as **names only** (grep the file for any secret value → none); `reproducibility.md` lists digest + build git SHA + lock hash; `validation_table.md` numbers match the dashboard for that `variant_ref`.
