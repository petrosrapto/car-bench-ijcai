# cbtrack runbook

End-to-end commands for running experiments, building the store, launching the
dashboard, and packaging a submission. Run everything from the repo root
(`repos/car-bench-ijcai`).

## 0. Install

```bash
# tracker deps (duckdb, fastapi, tomli-w) as an extra of this repo
uv sync --extra tracker
# the cbtrack console script is installed by pyproject [project.scripts]
cbtrack --help
```

Without installing the package you can also run modules directly:
`PYTHONPATH=src python -m cbtrack.cli --help`.

## 1. Fork hygiene (one-time)

This clone's `origin` currently points at the upstream repo. To make it your
fork while keeping upstream for future pulls:

```bash
git remote rename origin upstream
git remote add origin git@github.com:<you>/car-bench-ijcai.git
git push -u origin main
```

The evaluator-boundary check (step 7) diffs against `upstream/main`.

## 2. Run an evaluation

```bash
# smoke (1 task/type, 1 trial, train split) — fast loop check
cbtrack run --variant my-method --config smoke --agent-llm gemini/gemini-2.5-flash

# full public test set (all tasks, 3 trials) — the real validation signal
cbtrack run --variant my-method --config test --agent-llm gemini/gemini-2.5-flash \
  --scaffold planner_executor --tag ablation:thinking --hypothesis "interleaved thinking helps disambiguation"
```

This renders `experiments/runs/<run_id>/scenario.resolved.toml`, invokes the
native harness (`agentbeats.run_scenario`) on a free port pair, copies the result
to `result.json`, writes `manifest.json` + `env.captured.json`, appends to the
registry, and refreshes the store. Requires the relevant API keys in `.env`
(e.g. `GEMINI_API_KEY` for the user simulator + judge, the agent provider key).

**Docker mode** (matches the official submission path — official evaluator image
+ your agent image, wired by `generate_compose.py`):

```bash
# dry run: generate the compose artifacts only (no daemon needed) to inspect them
cbtrack run --variant my-method --config smoke --execution docker --dry-run \
  --image ghcr.io/<you>/car-bench-agent:latest

# real run: needs Docker + a built/pulled agent image + keys in .env
cbtrack run --variant my-method --config test --execution docker \
  --image ghcr.io/<you>/car-bench-agent:latest
```

Each docker run uses a unique compose project (`-p cb-<run_id>`) and a per-run
results mount, so concurrent runs never collide. (Note: a repo path containing
spaces can break docker volume mounts — keep the checkout in a space-free path.)

## 3. Backfill pre-existing results

```bash
cbtrack backfill output/            # any native client_cli JSONs
cbtrack refresh                     # rebuild the DuckDB/Parquet store
```

`backfill` is idempotent (deterministic run_ids), so re-running never duplicates.

**Import the official author baselines** as reference runs to populate the
dashboard with the real leaderboard (one run per model × evaluation set):

```bash
cbtrack import-baselines third_party/car-bench/results --all
```

These land as `baseline-*` variants (scaffold `baseline`, `run_id` prefixed
`00000000T000000Z`, `provenance.execution_mode = "imported"`) so they never mix
with your own runs. Remove with `rm -rf experiments/runs/00000000* && cbtrack refresh`.

## 4. Dashboard

```bash
cbtrack serve                       # FastAPI on http://127.0.0.1:8099 (serves web/dist if built)
# dev frontend with hot reload:
cd web && npm install && npm run dev # http://localhost:5173 (proxies /api -> :8099)
# production build (then `cbtrack serve` serves it at /):
cd web && npm run build
```

Pages: **Methods** (headline Pass^3 + CIs, subscore/policy/tool/economics),
**Compare** (per-task win/loss), **Trends** (metric over a method's run history),
**Trajectory** (turn-by-turn replay + verdict + GT-vs-taken actions diff),
**Submission** (generate + preview bundles).

## 5. Build a checkpoint & package a submission

```bash
# build the agent image (records reproducibility-build provenance)
docker build -t ghcr.io/<you>/car-bench-agent:latest \
  -f src/track_1_agent_under_test/Dockerfile.track-1-agent-under-test .
cbtrack build  <variant_ref> --image ghcr.io/<you>/car-bench-agent:latest

# push + record the digest (the value every scenario.toml pins)
docker push ghcr.io/<you>/car-bench-agent:latest
cbtrack publish <variant_ref> --image ghcr.io/<you>/car-bench-agent:latest

# promote a validated checkpoint (gate: a completed test/hidden run)
cbtrack promote <variant_ref>

# emit the digest-pinned submission bundle
cbtrack submission <variant_ref>
# -> experiments/submissions/<id>/{scenario.toml, reproducibility.md, validation_table.md, manifest.json}
```

The generated `scenario.toml` uses the official evaluator image, the
digest-pinned agent image, `task_split = "hidden"`, and env vars as **names only**
(`${VAR:?}` / `${VAR:-}`) — no secret values.

## 6. Inspect the registry / store

```bash
cbtrack ls runs
cbtrack ls variants
duckdb experiments/store/carbench.duckdb "select variant_ref, pass_power_3 from runs order by pass_power_3 desc"
```

## 7. Verify

```bash
# evaluator boundary unchanged (local results stay comparable to the official image)
git diff upstream/main -- src/evaluator third_party        # MUST be empty

# no secrets persisted
grep -rIl "API_KEY" experiments/runs/*/env.captured.json    # MUST be empty (values are redacted)

# store integrity: recomputed Pass^3 == native pass_power_k_scores (see PLAN verification §)
cbtrack refresh
```
