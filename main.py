"""Hikarin Studio — visual editor for Hikarin visual novel scripts.

Run:
    uv run serve.py

Then open http://127.0.0.1:8411

A small FastAPI app. No database, no accounts: a project is a folder under
``projects/``, and the editor is static files in ``static/``.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

from fastapi import FastAPI, HTTPException, Response, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from hikarin import assets as asset_store
from hikarin import blocks as block_defs
from hikarin import projects as project_store
from hikarin.compiler import compile_project
from hikarin.exporter import (build_json, build_markdown, build_pack, build_project_bundle, build_text, export_filename, export_filename_for)

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


class RawSaveRequest(BaseModel):
    content: str


class CreateRequest(BaseModel):
    slug: str
    meta: dict = Field(default_factory=dict)


class RenameRequest(BaseModel):
    new_slug: str


class DuplicateRequest(BaseModel):
    new_slug: str


class NewCharacterRequest(BaseModel):
    character: str
    outfit: str = "default"


class NewOutfitRequest(BaseModel):
    character: str
    outfit: str


class NewFolderRequest(BaseModel):
    path: str


class UploadedFile(BaseModel):
    name: str
    data: str  # base64, optionally behind a data: URL prefix


class UploadRequest(BaseModel):
    """Files land in ``dir``, a project-relative folder such as images/asset."""

    dir: str
    files: list[UploadedFile] = Field(default_factory=list)



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

@app.post("/api/projects/{slug}/duplicate")
def duplicate_endpoint(slug: str, req: DuplicateRequest):
    try:
        return project_store.duplicate_project(slug, req.new_slug)
    except project_store.ProjectError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


@app.post("/api/projects/{slug}/rename")
def rename_endpoint(slug: str, req: RenameRequest):
    try:
        return project_store.rename_project(slug, req.new_slug)
    except project_store.ProjectError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


@app.post("/api/projects/import-zip")
async def import_zip_endpoint(request: Request, slug: str = "imported"):
    payload = await request.body()
    if not payload:
        raise HTTPException(status_code=400, detail="No file uploaded")
    try:
        return project_store.import_project_zip(slug, payload)
    except project_store.ProjectError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


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


# ── game: world files ───────────────────────────────────────────

@app.get("/api/projects/{slug}/world")
def list_world_files(slug: str):
    """The game editor's world-file summary (kind, events, world files)."""
    try:
        return project_store.load_game_meta(project_store.project_dir(slug))
    except project_store.ProjectError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e


@app.get("/api/projects/{slug}/worldfile/{path:path}")
def read_world_file(slug: str, path: str):
    """Raw text of one world file (the studio round-trips verbatim)."""
    try:
        return Response(
            content=project_store.read_world_file(slug, path),
            media_type="application/json",
        )
    except project_store.ProjectError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e


@app.put("/api/projects/{slug}/worldfile/{path:path}")
def write_world_file(slug: str, path: str, req: RawSaveRequest):
    """Raw text write; .orch/.json contents are validated as JSON."""
    try:
        project_store.write_world_file(slug, path, req.content)
        return {"ok": True}
    except project_store.ProjectError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


# ── game: nested story events (roster) ──────────────────────────
# ── game: nested story events (roster) ─────────────────────────────

@app.get("/api/projects/{slug}/events")
def list_story_events(slug: str):
    """Every story living under events/ of a game project (cards for the roster)."""
    try:
        path = project_store.project_dir(slug)
        meta_file = path / "project.json"
        meta = json.loads(meta_file.read_text(encoding="utf-8"))
    except project_store.ProjectError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    except (OSError, json.JSONDecodeError) as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    if meta.get("kind") != "game":
        raise HTTPException(status_code=400, detail="not a game project")
    events_dir = path / "events"
    cards = []
    if events_dir.is_dir():
        for child in sorted(events_dir.iterdir()):
            meta_f = child / "project.json"
            if not child.is_dir() or not meta_f.is_file():
                continue
            try:
                data = json.loads(meta_f.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                continue
            if data.get("kind") == "game":
                continue
            cards.append(
                {
                    "slug": child.name,
                    "character": data.get("character", child.name),
                    "packName": data.get("packName", child.name),
                    "description": data.get("description", ""),
                    "files": data.get("files", []),
                    "storyFiles": len(list(child.rglob("*.story"))),
                }
            )
    return {"slug": slug, "events": cards}


class EventCreateRequest(BaseModel):
    event: str
    packName: str | None = None


@app.post("/api/projects/{slug}/events")
def create_story_event(slug: str, req: EventCreateRequest):
    """Create a fresh nested story event under events/<name>/."""
    try:
        meta = {"packName": req.packName} if req.packName else None
        project_store.create_event(slug, req.event, meta)
        return {"ok": True, "event": req.event}
    except project_store.ProjectError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


# ── assets ──────────────────────────────────────────────────────────────────
#
# The asset manager window's half of the story: read the inventory, add a
# character, add an outfit, make a folder, drop files in, delete something.
# Every mutation answers with the fresh inventory so the window re-renders from
# one source of truth instead of patching its own state and hoping.

def _assets_or_400(fn, *args):
    try:
        return fn(*args)
    except asset_store.AssetError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


def _inventory(slug: str) -> dict:
    return asset_store.inventory(project_store.asset_root(slug))


@app.get("/api/projects/{slug}/asset-list")
def list_project_assets(slug: str):
    """The full asset tree, without reloading the story files."""
    try:
        project_store.asset_root(slug)
    except project_store.ProjectError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    return _assets_or_400(_inventory, slug)


@app.post("/api/projects/{slug}/assets/character")
def create_character_asset(slug: str, req: NewCharacterRequest):
    base = project_store.asset_root(slug)
    created = _assets_or_400(asset_store.create_character, base, req.character, req.outfit)
    return {"created": created, "assets": _assets_or_400(_inventory, slug)}


@app.post("/api/projects/{slug}/assets/outfit")
def create_outfit_asset(slug: str, req: NewOutfitRequest):
    base = project_store.asset_root(slug)
    created = _assets_or_400(asset_store.create_outfit, base, req.character, req.outfit)
    return {"created": created, "assets": _assets_or_400(_inventory, slug)}


@app.post("/api/projects/{slug}/assets/folder")
def create_asset_folder(slug: str, req: NewFolderRequest):
    base = project_store.asset_root(slug)
    created = _assets_or_400(asset_store.create_folder, base, req.path)
    return {"created": created, "assets": _assets_or_400(_inventory, slug)}


@app.post("/api/projects/{slug}/assets/upload")
def upload_assets(slug: str, req: UploadRequest):
    """Save dropped or picked files into one folder.

    Base64 in JSON rather than multipart: it keeps the app on FastAPI alone with
    no extra install to break, and an image is not big enough for the encoding
    overhead to matter. The 24 MB per-file ceiling is in ``hikarin.assets``.
    """
    base = project_store.asset_root(slug)
    if not req.files:
        raise HTTPException(status_code=400, detail="No files given")

    decoded: list[tuple[str, bytes]] = []
    for item in req.files:
        decoded.append((item.name, _assets_or_400(asset_store.decode_upload, item.data)))

    written = _assets_or_400(asset_store.write_uploads, base, req.dir, decoded)
    return {"written": written, "assets": _assets_or_400(_inventory, slug)}


@app.delete("/api/projects/{slug}/assets")
def delete_asset(slug: str, path: str):
    base = project_store.asset_root(slug)
    deleted = _assets_or_400(asset_store.delete_path, base, path)
    return {"deleted": deleted, "assets": _assets_or_400(_inventory, slug)}


@app.get("/api/projects/{slug}/assets/{path:path}")
def serve_asset(slug: str, path: str):
    """Serve a project's media files to the in-browser preview.

    The editor's asset folders are named after what they hold (``images/``,
    ``sounds/``), not after Minecraft's internal layout. The preview asks for
    ``textures/<...>`` because that is what the engine's location strings say,
    so the two get mapped here: ``textures/x`` -> ``images/x``.
    """
    base = project_store.asset_root(slug).resolve()

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
def export_project(slug: str, format: str = "pack"):
    """Compile and return a ready-to-install resource pack zip."""
    fmt0 = (format or "pack").lower()
    if fmt0 == "game":
        # Game builds bypass the story compiler entirely — the game registry,
        # events and orchestrator are the unit under test.
        from hikarin import game as game_build
        try:
            report = game_build.compile_game(slug)
        except project_store.ProjectError as e:
            raise HTTPException(status_code=404, detail=str(e)) from e
        if not report["ok"]:
            return JSONResponse(
                status_code=400,
                content={"ok": False, "errors": report["errors"], "warnings": report["warnings"]},
            )
        game_json = report["buildDir"] / "game.json"
        return Response(
            content=game_json.read_bytes(),
            media_type="application/json",
            headers={"Content-Disposition": 'attachment; filename="game.json"'},
        )

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

    fmt = (format or "pack").lower()
    import io as _io
    import json as _json
    try:
        if fmt == "pack":
            payload = build_pack(loaded["meta"], result, project_store.asset_root(slug))
            media = "application/zip"
        elif fmt == "json":
            payload = build_json(loaded["meta"], result)
            media = "application/json"
        elif fmt == "txt":
            payload = build_text(loaded["meta"], result)
            media = "text/plain"
        elif fmt == "md":
            payload = build_markdown(loaded["meta"], result)
            media = "text/markdown"
        elif fmt == "bundle":
            payload = build_project_bundle(loaded["meta"], loaded["files"], project_store.asset_root(slug))
            media = "application/zip"
        else:
            raise HTTPException(status_code=400, detail=f"Unknown export format: {format!r} (pack|json|txt|md|bundle|game)")
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e

    filename = export_filename_for(loaded["meta"], fmt)
    return Response(
        content=payload,
        media_type=media,
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
        port=int(os.environ.get("HIKARIN_PORT", "8411")),
        reload=False,
    )
