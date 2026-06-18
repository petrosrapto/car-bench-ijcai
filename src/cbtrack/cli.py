"""``cbtrack`` command-line entry point.

Subcommands:
  run        run one evaluation (local) and land it in the registry
  refresh    rebuild the DuckDB/Parquet store from the registry
  backfill   ingest pre-existing native output JSONs (e.g. output/**/*.json)
  build      record a reproducibility-build for a variant checkpoint
  publish    record the published GHCR image digest
  promote    mark a validated checkpoint as a submission candidate
  submission generate the digest-pinned submission bundle
  serve      run the FastAPI dashboard backend
  ls         list runs / variants
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from . import backfill as backfill_mod
from . import paths, registry, scenario_gen, store, submission
from .scenario_gen import AgentSpec

_CONFIGS = {"smoke": scenario_gen.SMOKE, "test": scenario_gen.TEST_SET, "hidden": scenario_gen.HIDDEN_SET}


def _cmd_run(args: argparse.Namespace) -> int:
    from . import runner  # lazy: avoids importing harness deps for other commands

    agent = AgentSpec(
        name=args.variant,
        agent_module=args.agent_module,
        agent_llm=args.agent_llm,
        image=args.image,
    )
    config = _CONFIGS.get(args.config, scenario_gen.TEST_SET)
    manifest = runner.run(
        variant_id=args.variant,
        agent=agent,
        config=config,
        scaffold_kind=args.scaffold,
        tags=args.tag or [],
        hypothesis=args.hypothesis,
        show_logs=args.show_logs,
    )
    print(json.dumps({
        "run_id": manifest["run_id"],
        "variant_ref": manifest["variant_ref"],
        "status": manifest["status"],
        "pass_power_3": (manifest.get("headline", {}) or {}).get("pass_power_k", {}).get("Pass^3"),
        "run_dir": str(paths.run_dir(manifest["run_id"])),
    }, indent=2))
    return 0 if manifest["status"] == "completed" else 1


def _cmd_refresh(args: argparse.Namespace) -> int:
    counts = store.refresh()
    print(json.dumps({"store": str(paths.duckdb_path()), "rows": counts}, indent=2))
    return 0


def _cmd_backfill(args: argparse.Namespace) -> int:
    roots = [Path(p) for p in args.paths] or [paths.repo_root() / "output"]
    run_ids = backfill_mod.backfill_paths(roots)
    print(json.dumps({"backfilled": len(run_ids), "run_ids": run_ids[:20]}, indent=2))
    return 0


def _cmd_build(args: argparse.Namespace) -> int:
    print(json.dumps(submission.record_build(args.variant_ref, image=args.image), indent=2))
    return 0


def _cmd_publish(args: argparse.Namespace) -> int:
    print(json.dumps(submission.record_publish(args.variant_ref, image=args.image), indent=2))
    return 0


def _cmd_promote(args: argparse.Namespace) -> int:
    print(json.dumps(submission.promote(args.variant_ref), indent=2, default=str))
    return 0


def _cmd_submission(args: argparse.Namespace) -> int:
    out = submission.make_submission(args.variant_ref, team_image=args.image)
    print(json.dumps({"submission_dir": str(out), "files": sorted(p.name for p in out.iterdir())}, indent=2))
    return 0


def _cmd_serve(args: argparse.Namespace) -> int:
    import uvicorn  # noqa: WPS433

    uvicorn.run("api.main:app", host=args.host, port=args.port, reload=args.reload,
                app_dir=str(paths.repo_root()))
    return 0


def _cmd_ls(args: argparse.Namespace) -> int:
    if args.what == "runs":
        print(json.dumps(registry.list_runs(), indent=2, default=str))
    else:
        print(json.dumps(registry.list_variant_versions(), indent=2, default=str))
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="cbtrack", description="CAR-bench experiment tracker")
    sub = p.add_subparsers(dest="command", required=True)

    pr = sub.add_parser("run", help="run one evaluation (local)")
    pr.add_argument("--variant", required=True, help="variant_id (human slug for the method)")
    pr.add_argument("--config", default="test", choices=list(_CONFIGS), help="task/trial preset")
    pr.add_argument("--agent-llm", default=None, help="AGENT_LLM (LiteLLM model id)")
    pr.add_argument("--agent-module", default=scenario_gen.DEFAULT_AGENT_MODULE)
    pr.add_argument("--scaffold", default="bare")
    pr.add_argument("--image", default=None, help="agent image (for digest provenance)")
    pr.add_argument("--tag", action="append", help="repeatable run tag")
    pr.add_argument("--hypothesis", default=None)
    pr.add_argument("--show-logs", action="store_true")
    pr.set_defaults(func=_cmd_run)

    prf = sub.add_parser("refresh", help="rebuild the DuckDB/Parquet store")
    prf.set_defaults(func=_cmd_refresh)

    pb = sub.add_parser("backfill", help="ingest pre-existing native output JSONs")
    pb.add_argument("paths", nargs="*", help="files/dirs (default: output/)")
    pb.set_defaults(func=_cmd_backfill)

    pbd = sub.add_parser("build", help="record a reproducibility build for a checkpoint")
    pbd.add_argument("variant_ref")
    pbd.add_argument("--image", required=True)
    pbd.set_defaults(func=_cmd_build)

    ppub = sub.add_parser("publish", help="record the published GHCR image digest")
    ppub.add_argument("variant_ref")
    ppub.add_argument("--image", required=True)
    ppub.set_defaults(func=_cmd_publish)

    ppr = sub.add_parser("promote", help="mark a validated checkpoint as a candidate")
    ppr.add_argument("variant_ref")
    ppr.set_defaults(func=_cmd_promote)

    ps = sub.add_parser("submission", help="generate the digest-pinned submission bundle")
    ps.add_argument("variant_ref")
    ps.add_argument("--image", default=None, help="override agent image")
    ps.set_defaults(func=_cmd_submission)

    psv = sub.add_parser("serve", help="run the FastAPI dashboard backend")
    psv.add_argument("--host", default="127.0.0.1")
    psv.add_argument("--port", type=int, default=8099)
    psv.add_argument("--reload", action="store_true")
    psv.set_defaults(func=_cmd_serve)

    pls = sub.add_parser("ls", help="list runs or variants")
    pls.add_argument("what", choices=["runs", "variants"], default="runs", nargs="?")
    pls.set_defaults(func=_cmd_ls)

    return p


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
