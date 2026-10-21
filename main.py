"""Hikarin Studio — visual editor for Hikarin visual novel scripts.

Run:
    uv run serve.py

Then open http://127.0.0.1:8411

A small FastAPI app. No database, no accounts: a project is a folder under
``projects/``, and the editor is static files in ``static/``.
"""

from __future__ import annotations

import os
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

# Editing a .js or .css file and reloading is the whole development loop for
# this tool. A cached response makes an edit look like it did nothing, which has
# already sent me hunting through the wrong file twice. Tell browsers to always
# revalidate.
NO_CACHE = {
    "Cache-Control": "no-store, no-cache, must-revalidate, max-age=0",
    "Pragma": "no-cache",
    "Expires": "0",
}

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


@app.get("/api/projects/{slug}/play")
def play_project(slug: str):
    """Compiled actions for the in-browser preview.

    Same compiler as export, so what you test is what ships. Errors come back as
    a 200 with ``ok: false`` rather than a 4xx: a broken story is a normal state
    while writing, and the preview page renders the problems in place of the
    stage instead of showing a network error.
    """
    try:
        loaded = project_store.load_project(slug)
    except project_store.ProjectError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e

    result = compile_project(loaded["meta"], loaded["files"])
    return {
        "ok": result.ok,
        "errors": result.errors,
        "warnings": result.warnings,
        "actions": result.actions,
        "character": loaded["meta"].get("character", slug),
        "startLabel": loaded["meta"].get("startLabel", "start"),
        # Where the viewer should look for sprite and background images.
        "assetsPath": f"/api/projects/{slug}/assets/",
        "suggestedVars": _suggested_variables(loaded["files"]),
    }


def _suggested_variables(files: dict[str, list[dict]]) -> list[dict]:
    """Variables the story reads, so the preview can offer them.

    Derived from the script rather than hardcoded: if the writer invents
    ``affection.cupa``, the state panel should let them set it without typing.

    The browser viewer has a single variable namespace — it does not implement
    ``@maid``/``@world``/``@scene``. So the same variable name appearing under
    different scopes collapses into one entry here, keeping the first non-empty
    test value. The scope is still reported so the label reads correctly, but it
    does not change where the value goes.
    """
    from hikarin.blocks import CONDITIONS

    found: dict[str, dict] = {}
    for blocks in files.values():
        for block in blocks:
            data = block.get("data") or {}
            kind = block.get("kind")
            if kind not in ("if", "setVar"):
                continue

            condition = data.get("condition", "equal")
            spec = CONDITIONS.get(condition, {})
            needs_var = spec.get("needs_var", True)
            needs_value = spec.get("needs_value", True)

            # Day and night read no variable. Listing them here would present
            # them as settable state, which is the exact confusion this check
            # exists to avoid: they are condition types, not variables.
            if kind == "if" and not needs_var:
                continue

            name = data.get("var")
            if not name:
                continue

            if name in found:
                found[name]["writes"] = found[name]["writes"] or kind == "setVar"
                # Prefer a test value from an `if`: that is what the story asks.
                if kind == "if" and needs_value and found[name]["value"] is None:
                    found[name]["value"] = data.get("value")
                    found[name]["condition"] = condition
                continue

            found[name] = {
                "name": name,
                "scope": data.get("scope") or "",
                "value": data.get("value") if (kind == "if" and needs_value) else None,
                "condition": condition,
                "writes": kind == "setVar",
            }

    return sorted(found.values(), key=lambda v: (v["scope"] != "PLAYER", v["name"]))


@app.get("/api/projects/{slug}/assets/{path:path}")
def serve_asset(slug: str, path: str):
    """Serve a project's media files to the in-browser preview.

    The editor's asset folders are named after what they hold (``images/``,
    ``sounds/``), not after Minecraft's internal layout. The preview asks for
    ``textures/<...>`` because that is what the engine's location strings say,
    so the two get mapped here: ``textures/x`` -> ``images/x``.
    """
    base = project_store.project_dir(slug).resolve()

    if path.startswith("textures/"):
        target = (base / "images" / path[len("textures/"):]).resolve()
    elif path.startswith("sounds/"):
        target = (base / "sounds" / path[len("sounds/"):]).resolve()
    else:
        target = (base / "images" / path).resolve()

    if base != target and base not in target.parents:
        raise HTTPException(status_code=403, detail="Path escapes the project folder")
    if not target.is_file():
        raise HTTPException(status_code=404, detail=f"No asset named {path}")

    return FileResponse(target)


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
    return FileResponse(STATIC / "index.html", headers=NO_CACHE)


class NoCacheStatic(StaticFiles):
    """StaticFiles that asks the browser not to cache anything."""

    def file_response(self, *args, **kwargs):
        response = super().file_response(*args, **kwargs)
        response.headers.update(NO_CACHE)
        return response


if STATIC.is_dir():
    app.mount("/", NoCacheStatic(directory=STATIC, html=True), name="static")


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "main:app",
        host="127.0.0.1",
        port=int(os.environ.get("HIKARIN_PORT", "8422")),
        reload=False,
    )
