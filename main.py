"""Hikarin Studio — visual editor for Hikarin visual novel scripts.

Run:
    uv run serve.py

Then open http://127.0.0.1:8411

A small FastAPI app. No database, no accounts: a project is a folder under
``projects/``, and the editor is static files in ``static/``.

The shape of the API follows the shape of the data: projects contain stories,
and a story is what the editor opens. ``/api/projects/{slug}`` is the launcher
view (pack metadata, story list); ``/api/projects/{slug}/scripts/{character}/{script}`` is
what the editor edits.
"""

from __future__ import annotations

import os
from pathlib import Path

from fastapi import FastAPI, HTTPException, Response, Request
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from hikarin import assets as asset_store
from hikarin import blocks as block_defs
from hikarin import projects as project_store
from hikarin import resource_management as rm_store
from hikarin import variables as variable_store
from hikarin.rm_schema import ResourceManagementSchema
from hikarin.compiler import CompileResult, compile_project
from hikarin.exporter import (
    build_hikarin,
    build_json,
    build_markdown,
    build_pack,
    build_project_bundle,
    build_text,
    export_filename_for,
    script_slug,
)
from hikarin.export_formats import EXPORT_FORMATS, defaults, get_format, public_formats
from hikarin.rm_exporter import build_rmkit

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

app = FastAPI(title="Hikarin Studio", version="0.2.0")


# ── models ──────────────────────────────────────────────────────────────────


class Block(BaseModel):
    kind: str
    data: dict = Field(default_factory=dict)


class StorySaveRequest(BaseModel):
    meta: dict
    files: dict[str, list[Block]]


class CreateProjectRequest(BaseModel):
    slug: str
    meta: dict = Field(default_factory=dict)


class CreateScriptRequest(BaseModel):
    character: str
    script: str
    meta: dict = Field(default_factory=dict)


class RenameRequest(BaseModel):
    new_slug: str


class RenameScriptRequest(BaseModel):
    new_slug: str
    character: str | None = None


class VariablesRequest(BaseModel):
    """A whole-registry write: the manager holds the list and sends it back."""

    variables: list[dict] = Field(default_factory=list)


class ResourceManagementRequest(BaseModel):
    """The full RM schema, as edited in the RM designer."""

    data: dict = Field(default_factory=dict)


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
        # Two scopes, because two are all an author chooses between: local (this
        # story's own state) and global (shared by every story in the pack). The
        # engine has four and spells the shared one WORLD; hikarin.blocks owns
        # that translation, so nothing here has to know it.
        # The export menu. Adding a format means adding an entry to
        # hikarin.export_formats, not editing this file or the manager's HTML.
        "exportFormats": public_formats(),
        "scopes": [
            {"value": "LOCAL", "label": "Local — this story only"},
            {"value": "GLOBAL", "label": "Global — shared across the pack"},
        ],
    }


# ── projects ────────────────────────────────────────────────────────────────
#
# A project is a pack: metadata plus a list of stories. It is what the launcher
# lists and what gets exported. It has no blocks of its own.


def _project_or_404(fn, *args):
    try:
        return fn(*args)
    except project_store.ProjectError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e


def _project_or_400(fn, *args):
    try:
        return fn(*args)
    except project_store.ProjectError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


@app.get("/api/projects")
def list_projects():
    return project_store.list_projects()


@app.post("/api/projects")
def create_project(req: CreateProjectRequest):
    return _project_or_400(project_store.create_project, req.slug, req.meta)


@app.get("/api/projects/{slug}")
def get_project(slug: str):
    return _project_or_404(project_store.load_project, slug)


@app.put("/api/projects/{slug}")
def save_project_meta(slug: str, req: dict):
    """Write pack metadata. Story blocks are saved through the story endpoint."""
    return _project_or_400(project_store.save_project_meta, slug, req)


@app.delete("/api/projects/{slug}")
def delete_project(slug: str):
    _project_or_404(project_store.delete_project, slug)
    return {"deleted": True}


@app.post("/api/projects/{slug}/duplicate")
def duplicate_project(slug: str, req: RenameRequest):
    return _project_or_400(project_store.duplicate_project, slug, req.new_slug)


@app.post("/api/projects/{slug}/rename")
def rename_project(slug: str, req: RenameRequest):
    return _project_or_400(project_store.rename_project, slug, req.new_slug)


@app.post("/api/projects/import-zip")
async def import_zip_endpoint(request: Request, slug: str = "imported"):
    payload = await request.body()
    if not payload:
        raise HTTPException(status_code=400, detail="No file uploaded")
    return _project_or_400(project_store.import_project_zip, slug, payload)


# ── variables ───────────────────────────────────────────────────────────────
#
# The project's shared variable registry. A variable is a name the story reads
# and writes; declaring it once here means the editor's variable fields pick
# from a list instead of being typed by hand in every block.
#
# Project-level, like assets: a flag like `affection` is shared by every story in
# the pack, and a project that spells it two ways is a project that does not work.


@app.get("/api/projects/{slug}/variables")
def get_variables(slug: str):
    _project_or_404(project_store.project_dir, slug)
    try:
        return {"variables": variable_store.load_variables(project_store.project_dir(slug))}
    except variable_store.VariableError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


@app.put("/api/projects/{slug}/variables")
def put_variables(slug: str, req: VariablesRequest):
    """Replace the registry. Validates everything before writing anything."""
    try:
        saved = variable_store.save_variables(
            project_store.project_dir(slug), req.variables
        )
    except variable_store.VariableError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    return {"variables": saved}


# ── resource management ─────────────────────────────────────────────────────
#
# The designer for the game's economy: currencies, generators, converters,
# expeditions, tech trees, assignments. Everything is data; nothing here is VN
# logic. VN-visible resources are synced into the variables registry on save,
# so the story editor sees them as ordinary globals — the one seam between the
# two systems.


@app.get("/api/projects/{slug}/resource-management")
def get_rm(slug: str):
    _project_or_404(project_store.project_dir, slug)
    try:
        schema = rm_store.load_rm(project_store.project_dir(slug))
    except rm_store.ResourceManagementError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    problems = rm_store.validate_rm(schema, project_store.project_dir(slug))
    return {
        "schema": schema.model_dump(mode="json"),
        "problems": problems,
        "summary": rm_store.schema_summary(schema),
    }


@app.put("/api/projects/{slug}/resource-management")
def put_rm(slug: str, req: ResourceManagementRequest):
    """Validate and write the whole RM schema, then sync VN variables.

    Hard errors refuse the write entirely — the file on disk stays as it was.
    Warnings are returned for display. The sync drops RM-derived VN variables
    that no longer exist and registers newly visible ones; hand-registered
    variables are never touched.
    """
    _project_or_404(project_store.project_dir, slug)
    try:
        schema = ResourceManagementSchema.model_validate(req.data)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    try:
        schema, warnings = rm_store.save_rm(project_store.project_dir(slug), schema)
    except rm_store.ResourceManagementError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    return {
        "schema": schema.model_dump(mode="json"),
        "problems": warnings,
        "summary": rm_store.schema_summary(schema),
    }


@app.post("/api/projects/{slug}/resource-management/validate")
def validate_rm(slug: str, req: ResourceManagementRequest):
    """Validate a schema without writing it. What the designer's ✓ means."""
    _project_or_404(project_store.project_dir, slug)
    try:
        schema = ResourceManagementSchema.model_validate(req.data)
    except ValueError as e:
        return {"ok": False, "problems": [str(e)], "summary": None}
    problems = rm_store.validate_rm(schema, project_store.project_dir(slug))
    hard = [p for p in problems if "(warning)" not in p]
    return {
        "ok": not hard,
        "problems": problems,
        "summary": rm_store.schema_summary(schema),
    }


# ── stories ─────────────────────────────────────────────────────────────────
#
# A story is one character's script: a manifest, its .story files, and the blocks
# inside them. Everything the editor edits lives under here.


@app.get("/api/projects/{slug}/scripts")
def list_scripts(slug: str):
    """Every character with its scripts, grouped — what the manager renders."""
    return _project_or_404(project_store.load_project, slug)["characters"]


@app.post("/api/projects/{slug}/scripts")
def create_script(slug: str, req: CreateScriptRequest):
    return _project_or_400(
        project_store.create_script, slug, req.character, req.script, req.meta
    )


@app.get("/api/projects/{slug}/scripts/{character}/{script}")
def get_script(slug: str, character: str, script: str):
    return _project_or_404(project_store.load_script, slug, character, script)


@app.put("/api/projects/{slug}/scripts/{character}/{script}")
def save_script(slug: str, character: str, script: str, req: StorySaveRequest):
    files = {
        name: [b.model_dump() for b in blocks_] for name, blocks_ in req.files.items()
    }
    return _project_or_400(
        project_store.save_script, slug, character, script, req.meta, files
    )


@app.delete("/api/projects/{slug}/scripts/{character}/{script}")
def delete_script(slug: str, character: str, script: str):
    _project_or_404(project_store.delete_script, slug, character, script)
    return {"deleted": True}


@app.delete("/api/projects/{slug}/characters/{character}")
def delete_character(slug: str, character: str):
    """Remove a character and every script under it."""
    _project_or_404(project_store.delete_character, slug, character)
    return {"deleted": True}


@app.post("/api/projects/{slug}/scripts/{character}/{script}/duplicate")
def duplicate_script(slug: str, character: str, script: str, req: RenameScriptRequest):
    return _project_or_400(
        project_store.duplicate_script,
        slug,
        character,
        script,
        req.new_slug,
        req.character,
    )


@app.post("/api/projects/{slug}/scripts/{character}/{script}/rename")
def rename_script(slug: str, character: str, script: str, req: RenameScriptRequest):
    """Rename a script and/or move it under a different character.

    One call rather than rename-then-save: a save rewrites every ``.story``
    file, so changing a single manifest string through it would mean re-sending
    all the blocks and risking them.
    """
    return _project_or_400(
        project_store.rename_script,
        slug,
        character,
        script,
        req.new_slug,
        req.character,
    )


# ── compile ─────────────────────────────────────────────────────────────────


@app.get("/api/projects/{slug}/scripts/{character}/{script}/compile")
def compile_script_endpoint(slug: str, character: str, script: str):
    """Compile one script without writing anything. The editor's Validate button."""
    loaded = _project_or_404(project_store.load_script, slug, character, script)
    result = compile_project(loaded["meta"], loaded["files"])
    return {
        "ok": result.ok,
        "errors": result.errors,
        "warnings": result.warnings,
        "labels": result.labels,
        "actionCount": len(result.actions),
        "actions": result.actions,
    }


@app.get("/api/projects/{slug}/scripts/{character}/{script}/play")
def play_script(slug: str, character: str, script: str):
    """Compiled actions for the in-browser preview.

    Same compiler as export, so what you test is what ships. Errors come back as
    a 200 with ``ok: false`` rather than a 4xx: a broken script is a normal state
    while writing, and the preview page renders the problems in place of the
    stage instead of showing a network error.
    """
    loaded = _project_or_404(project_store.load_script, slug, character, script)
    result = compile_project(loaded["meta"], loaded["files"])
    return {
        "ok": result.ok,
        "errors": result.errors,
        "warnings": result.warnings,
        "actions": result.actions,
        "character": loaded["meta"].get("character") or character,
        "script": script,
        "startLabel": loaded["meta"].get("startLabel") or "start",
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


# ── assets ──────────────────────────────────────────────────────────────────
#
# The asset manager window's half of the story: read the inventory, add a
# character, add an outfit, make a folder, drop files in, delete something.
# Every mutation answers with the fresh inventory so the window re-renders from
# one source of truth instead of patching its own state and hoping.
#
# Assets belong to the project, not the story: a pack's art is shared by every
# story in it. That is why these hang off /projects/{slug}.


def _assets_or_400(fn, *args):
    try:
        return fn(*args)
    except asset_store.AssetError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


def _inventory(slug: str) -> dict:
    return asset_store.inventory(project_store.project_dir(slug))


def _project_base(slug: str) -> Path:
    return _project_or_404(project_store.project_dir, slug)


@app.get("/api/projects/{slug}/asset-list")
def list_project_assets(slug: str):
    """The full asset tree, without reloading the story files."""
    _project_base(slug)
    return _assets_or_400(_inventory, slug)


@app.post("/api/projects/{slug}/assets/character")
def create_character_asset(slug: str, req: NewCharacterRequest):
    base = _project_base(slug)
    created = _assets_or_400(asset_store.create_character, base, req.character, req.outfit)
    return {"created": created, "assets": _assets_or_400(_inventory, slug)}


@app.post("/api/projects/{slug}/assets/outfit")
def create_outfit_asset(slug: str, req: NewOutfitRequest):
    base = _project_base(slug)
    created = _assets_or_400(asset_store.create_outfit, base, req.character, req.outfit)
    return {"created": created, "assets": _assets_or_400(_inventory, slug)}


@app.post("/api/projects/{slug}/assets/folder")
def create_asset_folder(slug: str, req: NewFolderRequest):
    base = _project_base(slug)
    created = _assets_or_400(asset_store.create_folder, base, req.path)
    return {"created": created, "assets": _assets_or_400(_inventory, slug)}


@app.post("/api/projects/{slug}/assets/upload")
def upload_assets(slug: str, req: UploadRequest):
    """Save dropped or picked files into one folder.

    Base64 in JSON rather than multipart: it keeps the app on FastAPI alone with
    no extra install to break, and an image is not big enough for the encoding
    overhead to matter. The 24 MB per-file ceiling is in ``hikarin.assets``.
    """
    base = _project_base(slug)
    if not req.files:
        raise HTTPException(status_code=400, detail="No files given")

    decoded: list[tuple[str, bytes]] = []
    for item in req.files:
        decoded.append((item.name, _assets_or_400(asset_store.decode_upload, item.data)))

    written = _assets_or_400(asset_store.write_uploads, base, req.dir, decoded)
    return {"written": written, "assets": _assets_or_400(_inventory, slug)}


@app.delete("/api/projects/{slug}/assets")
def delete_asset(slug: str, path: str):
    base = _project_base(slug)
    deleted = _assets_or_400(asset_store.delete_path, base, path)
    return {"deleted": deleted, "assets": _assets_or_400(_inventory, slug)}


@app.get("/api/projects/{slug}/assets/{path:path}")
def serve_asset(slug: str, path: str):
    """Serve a project's media files to the in-browser preview.

    The editor's asset folders are named after what they hold (``images/``,
    ``sounds/``), not after the pack layout. The preview asks for
    ``textures/<...>`` because that is what the engine's location strings say,
    so the two get mapped here: ``textures/x`` -> ``images/x``.
    """
    base = _project_base(slug).resolve()

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
#
# A pack export compiles every script and writes one JSON per script. A single
# script can still be exported on its own (json/txt/md), which is what the
# editor's Export button does when you are looking at one script.


def _compiled_scripts(slug: str) -> dict[str, tuple[dict, CompileResult]]:
    """Every script in the project, compiled, keyed by ``"<character>/<script>"``.

    Raises 400 if any script is broken.
    """
    project = _project_or_404(project_store.load_project, slug)
    out: dict[str, tuple[dict, CompileResult]] = {}
    errors: list[str] = []
    for summary in project["scripts"]:
        character, script = summary["character"], summary["script"]
        loaded = project_store.load_script(slug, character, script)
        result = compile_project(loaded["meta"], loaded["files"])
        if result.errors:
            errors.append(f"{character}/{script}: {result.errors[0]}")
            continue
        out[f"{character}/{script}"] = (loaded["meta"], result)
    if errors:
        raise HTTPException(
            status_code=400,
            detail={"ok": False, "message": "Fix compile errors before exporting.", "errors": errors},
        )
    return out


def _raw_scripts(slug: str) -> dict[str, tuple[dict, dict]]:
    """Every script's authoring files, keyed by ``"<character>/<script>"``.

    What the bundle export carries — blocks, not compiled actions.
    """
    project = _project_or_404(project_store.load_project, slug)
    out: dict[str, tuple[dict, dict]] = {}
    for summary in project["scripts"]:
        character, script = summary["character"], summary["script"]
        loaded = project_store.load_script(slug, character, script)
        out[f"{character}/{script}"] = (loaded["meta"], loaded["files"])
    return out


@app.get("/api/projects/{slug}/export")
def export_project(slug: str, format: str = "pack", pack_format: int | None = None):
    """Compile the whole pack and return it in the requested format.

    ``pack_format`` is an export option, not a project setting: the same pack of
    scripts can be built for several runtime versions, so it is a query
    parameter here rather than a field in project.json.

    Layout by format: ``pack`` and ``hikarin`` flatten to ``<character>_<script>``
    slugs; ``bundle`` keeps the nested ``stories/<character>/<script>/`` folders.
    """
    project = _project_or_404(project_store.load_project, slug)
    fmt = (format or "pack").lower()

    try:
        if fmt == "pack":
            scripts = _compiled_scripts(slug)
            payload = build_pack(
                project["meta"],
                scripts,
                project_store.project_dir(slug),
                pack_format=pack_format,
            )
            media = "application/zip"
            filename = export_filename_for(project["meta"], "pack")

        elif fmt == "hikarin":
            scripts = _compiled_scripts(slug)
            payload = build_hikarin(project["meta"], scripts, project_store.project_dir(slug))
            media = "application/zip"
            filename = export_filename_for(project["meta"], "hikarin")

        elif fmt == "bundle":
            # The bundle carries authoring blocks, not compiled actions, and
            # keeps the character/script folder nesting.
            scripts = _raw_scripts(slug)
            payload = build_project_bundle(
                project["meta"], scripts, project_store.project_dir(slug)
            )
            media = "application/zip"
            filename = export_filename_for(project["meta"], "bundle")

        elif fmt == "rmkit":
            # Data only: the resource management schema plus its JSON Schema.
            payload = build_rmkit(project_store.project_dir(slug))
            media = "application/zip"
            filename = export_filename_for(project["meta"], "bundle").replace(
                ".hikarin.zip", ".rmkit.zip"
            )

        elif fmt == "story-json":
            character, script = _require_script_param(project)
            loaded = project_store.load_script(slug, character, script)
            result = compile_project(loaded["meta"], loaded["files"])
            payload = build_json(loaded["meta"], result)
            media = "application/json"
            filename = f"{script_slug(character, script)}.json"

        else:
            raise HTTPException(
                status_code=400,
                detail=f"Unknown export format: {format!r} (pack|hikarin|bundle|story-json|rmkit)",
            )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e

    return Response(
        content=payload,
        media_type=media,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@app.get("/api/projects/{slug}/scripts/{character}/{script}/export")
def export_script(slug: str, character: str, script: str, format: str = "json"):
    """One script, compiled and written out on its own."""
    loaded = _project_or_404(project_store.load_script, slug, character, script)
    result = compile_project(loaded["meta"], loaded["files"])
    if result.errors:
        return JSONResponse(
            status_code=400,
            content={"ok": False, "errors": result.errors, "warnings": result.warnings},
        )

    fmt = (format or "json").lower()
    try:
        if fmt == "json":
            payload = build_json(loaded["meta"], result)
            media = "application/json"
            filename = f"{script_slug(character, script)}.json"
        elif fmt == "txt":
            payload = build_text(loaded["meta"], result)
            media = "text/plain"
            filename = f"{script_slug(character, script)}.txt"
        elif fmt == "md":
            payload = build_markdown(loaded["meta"], result)
            media = "text/markdown"
            filename = f"{script_slug(character, script)}.md"
        else:
            raise HTTPException(
                status_code=400, detail=f"Unknown format {format!r} (json|txt|md)"
            )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e

    return Response(
        content=payload,
        media_type=media,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


def _require_script_param(project: dict) -> tuple[str, str]:
    """Pick the single script for a project-level single-script export."""
    scripts = project.get("scripts") or []
    if len(scripts) == 1:
        return scripts[0]["character"], scripts[0]["script"]
    raise HTTPException(
        status_code=400,
        detail="This project has several scripts; export one from its own endpoint.",
    )


# ── static ──────────────────────────────────────────────────────────────────


@app.get("/")
def index():
    """The front door is the manager, not the editor.

    The editor edits one story, so it has nothing to show until a project and a
    story exist. Landing there on a fresh install is a blank page with an error
    in the status bar, which reads as "the app is broken" rather than "you have
    not made anything yet". The manager is the honest first screen: it says how
    many projects you have, and offers the button that fixes it.
    """
    return RedirectResponse(url="/manager")


@app.get("/editor")
def editor():
    """The story editor. Always reached with ?project=...&story=... ."""
    return FileResponse(STATIC / "index.html", headers=NO_CACHE)


@app.get("/rm-editor")
def rm_editor():
    """The resource management designer. ?project=<slug>."""
    return FileResponse(STATIC / "rm-editor.html", headers=NO_CACHE)


@app.get("/manager")
def manager():
    """The launcher: projects, their stories, and nothing else."""
    return FileResponse(STATIC / "manager.html", headers=NO_CACHE)


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