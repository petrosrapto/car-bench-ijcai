"""Submission packaging endpoints — power the dashboard's Submission panel."""

from __future__ import annotations

import json
import sys
from pathlib import Path

from fastapi import APIRouter, HTTPException

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))
from cbtrack import paths, submission  # noqa: E402

router = APIRouter(prefix="/api/submissions", tags=["submissions"])


@router.get("")
def list_submissions():
    base = paths.submissions_dir()
    if not base.exists():
        return []
    out = []
    for d in sorted(base.iterdir()):
        manifest = d / "manifest.json"
        if manifest.exists():
            out.append(json.loads(manifest.read_text(encoding="utf-8")))
    return out


@router.get("/{submission_id}")
def preview(submission_id: str):
    d = paths.submission_dir(submission_id)
    if not d.exists():
        raise HTTPException(404, f"submission not found: {submission_id}")
    files = {}
    for name in ("scenario.toml", "reproducibility.md", "validation_table.md", "manifest.json"):
        p = d / name
        if p.exists():
            files[name] = p.read_text(encoding="utf-8")
    return files


@router.post("/generate/{variant_ref:path}")
def generate(variant_ref: str, image: str | None = None):
    try:
        out = submission.make_submission(variant_ref, team_image=image)
    except (KeyError, ValueError) as exc:
        raise HTTPException(400, str(exc))
    return {"submission_dir": str(out), "submission_id": out.name}
