"""Project storage: a folder on disk is a project.

The layout deliberately mirrors the original MobTalkerSDK's ``mediafile``
directory, because that structure is the one that already works and the author
wrote it down::

    projects/cupa/
        project.json         character, pack name, file order, start label
        main.story           the spine
        night.story
        idle.story
        images/              becomes assets/<ns>/textures/ in the pack
            pack.png         the resource pack icon
            characters/
                cupa/
                    default/         outfit, always present
                        happy.png
                        angry.png
            asset/           backgrounds
                end.png
                void.png
        sounds/
            music/           haggstrom.ogg
            sound/           teleport.ogg

``images/`` maps to ``textures/`` on export; that is the only rename. Sounds map
one-to-one. Scripts are generated, never hand-edited — the pack's JSON is
written at export time from the compiled story.

The SDK's own note on sprite layout::

    the format is

    name/outfit/images.png

    like:

    cupa/default/happy.png

    The mod as of writing this doesn't have swap outfit feature yet, but just in
    case and for the sake of future compatibility, add 'default' there, aight?

``.story`` files are JSON arrays of editor blocks, without ids. The compiler
assigns ids, so reordering blocks never causes a numbering conflict.
"""

from __future__ import annotations

import io
import json
import re
import shutil
import zipfile
from pathlib import Path
from typing import Any

from .compiler import CompileResult, compile_project

PROJECTS_ROOT = Path(__file__).resolve().parent.parent / "projects"

SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")

DEFAULT_PROJECT: dict[str, Any] = {
    "character": "cupa",
    "packName": "My Story",
    "packFormat": 15,
    "description": "Made with Hikarin Studio",
    "files": ["main.story"],
    "startLabel": "start",
}

DEFAULT_MAIN: list[dict] = [
    {"kind": "label", "data": {"name": "start"}},
    {"kind": "say", "data": {"label": "Cupa", "content": "Hello there."}},
    {"kind": "end", "data": {}},
]


class ProjectError(Exception):
    """Raised for user-facing project problems (bad name, missing file...)."""


# ── discovery ───────────────────────────────────────────────────────────────

def list_projects() -> list[dict[str, Any]]:
    """Every project folder under the projects root."""
    if not PROJECTS_ROOT.is_dir():
        return []
    found = []
    for entry in sorted(PROJECTS_ROOT.iterdir()):
        if not entry.is_dir():
            continue
        meta_file = entry / "project.json"
        if not meta_file.is_file():
            continue
        try:
            meta = json.loads(meta_file.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        modified = meta_file.stat().st_mtime
        try:
            for f in entry.rglob("*"):
                if f.is_file():
                    m = f.stat().st_mtime
                    if m > modified:
                        modified = m
        except OSError:
            pass
        found.append(
            {
                "slug": entry.name,
                "kind": meta.get("kind", "story"),
                "character": meta.get("character", entry.name),
                "packName": meta.get("packName", entry.name),
                "description": meta.get("description", ""),
                "files": meta.get("files", []),
                "modified": int(modified * 1000),
            }
        )
    return found


def project_dir(slug: str) -> Path:
    if not SLUG_RE.match(slug or ""):
        raise ProjectError(f"Invalid project name: {slug!r}")
    path = PROJECTS_ROOT / slug
    # Guard against traversal even though the regex already forbids it.
    if PROJECTS_ROOT.resolve() not in path.resolve().parents and path.resolve() != PROJECTS_ROOT.resolve():
        raise ProjectError("Invalid project path")
    return path


# ── load / save ─────────────────────────────────────────────────────────────

def load_project(slug: str) -> dict[str, Any]:
    """Read a project and all its .story files.

    Returns ``{"slug", "meta", "files": {name: [block]}, "assets": [...]}``.
    """
    path = project_dir(slug)
    meta_file = path / "project.json"
    if not meta_file.is_file():
        raise ProjectError(f"Project '{slug}' has no project.json")

    try:
        meta = json.loads(meta_file.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        raise ProjectError(f"project.json is not valid JSON: {e}") from e

    names = list(meta.get("files") or [])
    # Include any .story file on disk that project.json forgot about.
    for story in sorted(path.rglob("*.story")):
        rel = story.relative_to(path).as_posix()
        if rel not in names:
            names.append(rel)

    files: dict[str, list[dict]] = {}
    for name in names:
        story_path = path / name
        if not story_path.is_file():
            files[name] = []
            continue
        try:
            data = json.loads(story_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as e:
            raise ProjectError(f"{name} is not valid JSON: {e}") from e
        if not isinstance(data, list):
            raise ProjectError(f"{name} must contain a JSON array of blocks")
        files[name] = data

    meta["files"] = names
    return {
        "slug": slug,
        "meta": meta,
        "files": files,
        "assets": list_assets(path),
    }


def save_project(slug: str, meta: dict[str, Any], files: dict[str, list[dict]]) -> None:
    """Write project.json and every .story file.

    Files removed from ``files`` are deleted from disk, so deleting a tab in the
    editor actually removes the file rather than leaving an orphan that would be
    re-discovered on next load.
    """
    path = project_dir(slug)
    path.mkdir(parents=True, exist_ok=True)

    existing = {p.relative_to(path).as_posix() for p in path.rglob("*.story")}
    incoming = set(files)

    for gone in existing - incoming:
        try:
            (path / gone).unlink()
        except OSError:
            pass

    for name, blocks in files.items():
        target = path / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(
            json.dumps(blocks, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
        )

    meta = dict(meta)
    meta["files"] = list(files)
    (path / "project.json").write_text(
        json.dumps(meta, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )


def create_project(slug: str, meta: dict[str, Any] | None = None) -> dict[str, Any]:
    meta = dict(meta or {})
    if meta.get("kind") == "game":
        return create_game_project(slug, meta)

    path = project_dir(slug)
    if path.exists() and any(path.iterdir()):
        raise ProjectError(f"Project '{slug}' already exists")
    path.mkdir(parents=True, exist_ok=True)

    # Scaffold the mediafile layout so the folders are obvious the first time
    # the author opens the project in Explorer.
    (path / "images" / "characters").mkdir(parents=True, exist_ok=True)
    (path / "images" / "asset").mkdir(parents=True, exist_ok=True)
    (path / "sounds" / "music").mkdir(parents=True, exist_ok=True)
    (path / "sounds" / "sound").mkdir(parents=True, exist_ok=True)
    (path / "images" / "characters" / "Add Character Sprite Here.txt").write_text(
        "Character sprites go in folders here.\n\n"
        "The format is name/outfit/image.png\n\n"
        "like:\n\n"
        "    cupa/default/happy.png\n\n"
        "Always include the outfit folder. The mod does not swap outfits yet, but\n"
        "the level exists so scripts never need rewriting when it does.\n\n"
        "Names must be lowercase with no spaces or punctuation: they become\n"
        "texture paths.\n",
        encoding="utf-8",
    )
    (path / "images" / "asset" / "Add Background Here.txt").write_text(
        "Backgrounds go here, flat.\n\n"
        "Like:\n\n"
        "    end.png\n\n"
        "In a script, reference them as:\n\n"
        "    asset/end.png\n",
        encoding="utf-8",
    )
    (path / "sounds" / "sound" / "Add Sound Here.txt").write_text(
        "Sound effects go here, as .ogg files.\n\n"
        "In a script, a sound named click.ogg is referenced as:\n\n"
        "    click\n",
        encoding="utf-8",
    )
    (path / "sounds" / "music" / "Add Music Here.txt").write_text(
        "Music tracks go here, as .ogg files.\n\n"
        "In a script, a track named haggstrom.ogg is referenced as:\n\n"
        "    haggstrom\n",
        encoding="utf-8",
    )

    merged = dict(DEFAULT_PROJECT)
    if meta:
        merged.update(meta)
    merged["character"] = merged.get("character") or slug

    save_project(slug, merged, {"main.story": list(DEFAULT_MAIN)})
    return load_project(slug)


def delete_project(slug: str) -> None:
    path = project_dir(slug)
    if not path.is_dir():
        raise ProjectError(f"Project '{slug}' does not exist")
    shutil.rmtree(path)


# ── compile ─────────────────────────────────────────────────────────────────

def compile_slug(slug: str) -> CompileResult:
    loaded = load_project(slug)
    return compile_project(loaded["meta"], loaded["files"])


# ── assets ──────────────────────────────────────────────────────────────────

def list_assets(path: Path) -> dict[str, Any]:
    """Inventory the project's media folders, grouped for the editor.

    Reads the ``mediafile`` layout the SDK ships:

        images/characters/<id>/<outfit>/<emotion>.png   sprites
        images/asset/<background>.png                   backgrounds
        sounds/music/<track>.ogg                        music
        sounds/sound/<sfx>.ogg                          sound effects

    Returns the shape the editor's dropdowns want::

        {
          "characters": {"cupa": {"default": ["happy", "normal"]}},
          "backgrounds": ["asset/end.png"],
          "folders": {"asset": ["end", "void"]},
          "sounds": ["sound/teleport.ogg"],
          "music": ["music/haggstrom.ogg"],
          # plus the tree the asset manager window drives off:
          "characterTree", "imageFolders", "audio", "packIcon", "totals",
        }

    Backgrounds are reported with their folder prefix because that is how a
    script must reference them: ``asset/end.png``, not ``end.png``.

    The walk itself lives in :mod:`hikarin.assets`, next to the code that adds
    and removes the files it describes, so the two cannot drift apart.
    """
    from .assets import inventory

    return inventory(path)


# ── game projects ───────────────────────────────────────────────────────────

DEFAULT_GAME: dict[str, Any] = {
    "kind": "game",
    "packName": "My Game",
    "description": "Made with Hikarin Studio",
    "version": 1,
    "start": "start",
}


def create_game_project(slug: str, meta: dict[str, Any] | None = None) -> dict[str, Any]:
    """Scaffold a game project: nested event slot, world folder, one main flow.

    The generated ``world/map.orch`` is a ready-to-run skeleton (meta -> label
    -> ending) so a game is openable and buildable on creation day.
    """
    path = project_dir(slug)
    if path.exists() and any(path.iterdir()):
        raise ProjectError(f"Project '{slug}' already exists")
    path.mkdir(parents=True, exist_ok=True)

    # Same mediafile scaffold as stories: assets shared by every event.
    (path / "images" / "characters").mkdir(parents=True, exist_ok=True)
    (path / "images" / "asset").mkdir(parents=True, exist_ok=True)
    (path / "sounds" / "music").mkdir(parents=True, exist_ok=True)
    (path / "sounds" / "sound").mkdir(parents=True, exist_ok=True)
    (path / "events").mkdir()
    world = path / "world"
    world.mkdir()

    (world / VARIABLES_FILE_NAME).write_text(
        json.dumps({"variables": []}, indent=2) + "\n", encoding="utf-8"
    )

    skeleton = {
        "kind": "orch-graph",
        "start": "n_meta",
        "nodes": [
            {"id": "n_meta", "verb": "meta", "fields": {"action": "start"}, "at": [0, 0]},
            {"id": "n_label", "verb": "label", "fields": {"label": "start"}, "at": [0, 120]},
            {"id": "n_end", "verb": "ending", "fields": {}, "at": [0, 240]},
        ],
        "wires": [
            {"from": ["n_meta", "out"], "to": ["n_label", "in"]},
            {"from": ["n_label", "out"], "to": ["n_end", "in"]},
        ],
    }
    (world / "map.orch").write_text(json.dumps(skeleton, indent=2) + "\n", encoding="utf-8")

    merged = dict(DEFAULT_GAME)
    if meta:
        merged.update(meta)
    merged["kind"] = "game"
    (path / "project.json").write_text(
        json.dumps(merged, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    return load_game_meta(path)


def load_game_meta(path: Path) -> dict[str, Any]:
    """Everything the game editor needs, loaded once."""
    meta_file = path / "project.json"
    meta = json.loads(meta_file.read_text(encoding="utf-8"))
    events = [
        child.name
        for child in sorted((path / EVENTS_DIRNAME).iterdir())
        if child.is_dir() and (child / "project.json").is_file()
    ] if (path / EVENTS_DIRNAME).is_dir() else []
    world = path / WORLD_DIRNAME
    files = []
    if world.is_dir():
        for f in sorted(world.glob("*")):
            if f.is_file() and f.suffix in (".orch", ".json", ".md"):
                files.append(f.name)
    return {
        "meta": meta,
        "events": events,
        "worldFiles": files,
        "buildDir": str(path / "build"),
    }


VARIABLES_FILE_NAME = "variables.json"
EVENTS_DIRNAME = "events"
WORLD_DIRNAME = "world"


def _world_containment(slug: str, rel: str) -> Path:
    """Resolve rel under <project>/world/ and refuse anything outside it."""
    base = project_dir(slug) / WORLD_DIRNAME
    base_resolved = base.resolve()
    target = (base / rel).resolve()
    if target != base_resolved and base_resolved not in target.parents:
        raise ProjectError("Path escapes the world folder")
    if not target.is_file():
        raise ProjectError(f"world file not found: {rel!r}")
    return target


def read_world_file(slug: str, rel: str) -> str:
    return _world_containment(slug, rel).read_text(encoding="utf-8")


def write_world_file(slug: str, rel: str, content: str) -> None:
    base = project_dir(slug) / WORLD_DIRNAME
    base_resolved = base.resolve()
    target = (base / rel).resolve()
    if target != base_resolved and base_resolved not in target.parents:
        raise ProjectError("Path escapes the world folder")
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.suffix in (".orch", ".json"):
        try:
            json.loads(content)
        except json.JSONDecodeError as e:
            raise ProjectError(f"world file must be valid JSON: {e}") from e
    tmp = target.with_name(target.name + ".tmp")
    tmp.write_text(content, encoding="utf-8")
    tmp.replace(target)

# ── duplicate / rename / import ─────────────────────────────────────────────

def duplicate_project(slug: str, new_slug: str) -> dict[str, Any]:
    src = project_dir(slug)
    if not src.is_dir():
        raise ProjectError(f"Project '{slug}' does not exist")
    dest = project_dir(new_slug)
    if dest.exists() and any(dest.iterdir()):
        raise ProjectError(f"Project '{new_slug}' already exists")
    shutil.copytree(src, dest)
    return load_project(new_slug)


def rename_project(slug: str, new_slug: str) -> dict[str, Any]:
    src = project_dir(slug)
    if not src.is_dir():
        raise ProjectError(f"Project '{slug}' does not exist")
    dest = project_dir(new_slug)
    if dest.exists() and any(dest.iterdir()):
        raise ProjectError(f"Project '{new_slug}' already exists")
    src.rename(dest)
    return load_project(new_slug)


def import_project_zip(slug: str, payload: bytes) -> dict[str, Any]:
    """Import a .hikarin.zip project bundle (or any zip containing project.json)."""
    dest = project_dir(slug)
    if dest.exists() and any(dest.iterdir()):
        raise ProjectError(f"Project '{slug}' already exists")
    try:
        zf = zipfile.ZipFile(io.BytesIO(payload))
    except zipfile.BadZipFile as e:
        raise ProjectError(f"Not a valid zip file: {e}") from e

    names = zf.namelist()
    # Find project.json at root or one level deep
    prefix = ""
    if "project.json" not in names:
        candidates = [n for n in names if n.endswith("/project.json")]
        if len(candidates) != 1:
            raise ProjectError("Zip must contain a single project.json")
        prefix = candidates[0][:-len("project.json")]

    dest_path = dest.resolve()
    dest.mkdir(parents=True, exist_ok=True)
    try:
        for name in names:
            if name.endswith("/"):
                continue
            rel = name[len(prefix):] if prefix else name
            target = (dest / rel)
            # guard traversal
            try:
                target.resolve().relative_to(dest_path)
            except ValueError:
                raise ProjectError(f"Zip entry escapes project folder: {name}")
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(zf.read(name))
    except Exception:
        shutil.rmtree(dest, ignore_errors=True)
        raise

    if not (dest / "project.json").is_file():
        shutil.rmtree(dest, ignore_errors=True)
        raise ProjectError("Zip must contain project.json")
    try:
        return load_project(slug)
    except ProjectError:
        shutil.rmtree(dest, ignore_errors=True)
        raise
