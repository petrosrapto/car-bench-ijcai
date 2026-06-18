"""cbtrack dashboard backend.

Run: ``cbtrack serve`` (or ``uvicorn api.main:app --reload`` from the repo root).

Read-only API over the DuckDB store + the per-run result.json files. Serves the
built React app from ``web/dist`` if present; in dev the Vite server (5173) talks
to this API via CORS.
"""

from __future__ import annotations

import sys
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

_REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_REPO_ROOT / "src"))

from . import deps  # noqa: E402
from .routers import runs, stats, submissions, trajectory  # noqa: E402

app = FastAPI(title="cbtrack dashboard", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(runs.router)
app.include_router(stats.router)
app.include_router(trajectory.router)
app.include_router(submissions.router)


@app.get("/api/health")
def health():
    return {"ok": True, "store_built": deps.store_exists()}


# Serve the built frontend if it exists (production single-binary style).
_DIST = _REPO_ROOT / "web" / "dist"
if _DIST.exists():
    from fastapi.staticfiles import StaticFiles

    app.mount("/", StaticFiles(directory=str(_DIST), html=True), name="web")
