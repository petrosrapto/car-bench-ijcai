# 0004 — Frontend = FastAPI + React

- **Status:** Accepted
- **Date:** 2026-06-18

## Context

We need an interactive dashboard with a statistics view (per-method Pass^3 with
CIs, subscore/policy/tool breakdowns, compare, trends) and a trajectory replay
viewer (turn-by-turn, verdict, GT-vs-taken diff). The user explicitly chose a
FastAPI + React stack over Streamlit / static export / notebooks.

## Decision

A read-only FastAPI backend (`api/`) over the DuckDB store + per-run `result.json`,
and a Vite + React + TypeScript frontend (`web/`). Dev: Vite (`:5173`) proxies
`/api` to FastAPI (`:8099`). Prod: `cbtrack serve` mounts the built `web/dist` at
`/`, giving a single-process dashboard. Charts are dependency-light (CSS/SVG bars
with CI whiskers) to keep the bundle small and the build robust.

## Consequences

- Clean API/UI separation; the API is reusable headless (curl/scripts).
- Polished, shareable interactive app; no Python-render coupling.
- Static publication figures still available via `plot_export.py` (wraps the
  official `plot_results.py`).
- Trade-off: two toolchains (Python + Node) vs a single-language Streamlit app —
  accepted per the explicit stack choice.

## Alternatives considered

- **Streamlit:** fastest to build, python-only, but less polished and couples UI to
  Python execution. Rejected by user preference.
- **Static export only:** great for paper figures, no drill-down/replay. Kept as a
  secondary export path, not the primary dashboard.
