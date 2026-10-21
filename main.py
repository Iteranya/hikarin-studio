"""Hikarin Studio — visual editor for Hikarin visual novel scripts.

Run:
    uv run main.py

Then open http://127.0.0.1:8411

A small FastAPI app. No database, no accounts: a project is a folder under
``projects/``, and the editor is static files in ``static/``.
"""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, HTTPException, Response
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from hikarin import blocks as block_defs
from hikarin import projects as project_store
from hikarin.compiler import compile_project
from hikarin.exporter import build_pack, export_filename

ROOT = Path(__file__).resolve().parent
STATIC = ROOT / "static"

app = FastAPI(title="Hikarin Studio", version="0.1.0")


# ── models ──────────────────────────────────────────────────────────────────

class Block(BaseModel):
    kind: str
    data: dict = Field(default_factory=dict)


class SaveRequest(BaseModel):
    meta: dict
    files: dict[str, list[Block]]


class CreateRequest(BaseModel):
    slug: str
    meta: dict = Field(default_factory=dict)


# ── meta ────────────────────────────────────────────────────────────────────

@app.get("/api/meta")
def get_meta():
    """Everything the editor needs to render its palette and dropdowns."""
    return {
        "blocks": sorted(block_defs.BUILDERS),
        "conditions": block_defs.CONDITIONS,
        "positions": block_defs.POSITIONS,
        "spriteDefaults": block_defs.SPRITE_DEFAULTS,
        "scopes": [
            {"value": "", "label": "This scene only (temporary)"},
            {"value": "WORLD", "label": "Story flag (remembered forever)"},
            {"value": "MAID", "label": "This maid only"},
            {"value": "SCENE", "label": "This scene only"},
        ],
    }


# ── projects ────────────────────────────────────────────────────────────────

@app.get("/api/projects")
def list_projects():
    return project_store.list_projects()


@app.post("/api/projects")
def create_project(req: CreateRequest):
    try:
        return project_store.create_project(req.slug, req.meta)
    except project_store.ProjectError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


@app.get("/api/projects/{slug}")
def get_project(slug: str):
    try:
        return project_store.load_project(slug)
    except project_store.ProjectError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e


@app.put("/api/projects/{slug}")
def save_project(slug: str, req: SaveRequest):
    files = {name: [b.model_dump() for b in blocks_] for name, blocks_ in req.files.items()}
    try:
        project_store.save_project(slug, req.meta, files)
        return {"saved": True, "files": list(files)}
    except project_store.ProjectError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


@app.delete("/api/projects/{slug}")
def delete_project(slug: str):
    try:
        project_store.delete_project(slug)
        return {"deleted": True}
    except project_store.ProjectError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e


# ── compile ─────────────────────────────────────────────────────────────────

@app.get("/api/projects/{slug}/compile")
def compile_project_endpoint(slug: str):
    """Compile without writing anything. The editor's Validate button."""
    try:
        loaded = project_store.load_project(slug)
    except project_store.ProjectError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e

    result = compile_project(loaded["meta"], loaded["files"])
    return {
        "ok": result.ok,
        "errors": result.errors,
        "warnings": result.warnings,
        "labels": result.labels,
        "actionCount": len(result.actions),
        "actions": result.actions,
    }


# ── export ──────────────────────────────────────────────────────────────────

@app.get("/api/projects/{slug}/export")
def export_project(slug: str):
    """Compile and return a ready-to-install resource pack zip."""
    try:
        loaded = project_store.load_project(slug)
    except project_store.ProjectError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e

    result = compile_project(loaded["meta"], loaded["files"])
    if result.errors:
        return JSONResponse(
            status_code=400,
            content={"ok": False, "errors": result.errors, "warnings": result.warnings},
        )

    try:
        payload = build_pack(loaded["meta"], result, project_store.project_dir(slug))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e

    filename = export_filename(loaded["meta"])
    return Response(
        content=payload,
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


# ── static ──────────────────────────────────────────────────────────────────

@app.get("/")
def index():
    return FileResponse(STATIC / "index.html")


if STATIC.is_dir():
    app.mount("/", StaticFiles(directory=STATIC, html=True), name="static")


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("main:app", host="127.0.0.1", port=8411, reload=True)
