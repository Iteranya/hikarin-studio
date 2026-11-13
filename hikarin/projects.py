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
import os
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


def _nested_dir(slug: str):
    """Split a nested slug 'game::event' into (game_dir, event_dir). Returns None otherwise."""
    parts = slug.split("::")
    if len(parts) != 2:
        return None
    game, event = parts
    if not SLUG_RE.match(game) or not SLUG_RE.match(event):
        raise ProjectError(f"Invalid nested project name: {slug!r}")
    game_dir = PROJECTS_ROOT / game
    meta_file = game_dir / "project.json"
    if not meta_file.is_file():
        raise ProjectError(f"Game '{game}' does not exist")
    try:
        meta = json.loads(meta_file.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        raise ProjectError(f"project.json is not valid JSON: {e}") from e
    if meta.get("kind") != "game":
        raise ProjectError(f"Project '{game}' is not a game project")
    event_dir = (game_dir / EVENTS_DIRNAME / event).resolve()
    if game_dir.resolve() not in event_dir.parents:
        raise ProjectError("Invalid event path")
    return game_dir, event_dir, game, event


def project_dir(slug: str) -> Path:
    nested = _nested_dir(slug)
    if nested:
        _game_dir, event_dir, _game, _event = nested
        if not event_dir.is_dir():
            raise ProjectError(f"Event '{_event}' does not exist under events/")
        return event_dir
    if not SLUG_RE.match(slug or ""):
        raise ProjectError(f"Invalid project name: {slug!r}")
    path = PROJECTS_ROOT / slug
    # Guard against traversal even though the regex already forbids it.
    if PROJECTS_ROOT.resolve() not in path.resolve().parents and path.resolve() != PROJECTS_ROOT.resolve():
        raise ProjectError("Invalid project path")
    return path


def dest_dir(slug: str) -> Path:
    """Destination path for a project (used by duplicate/rename targets).

    Unlike project_dir(), the nested event folder is allowed to be missing —
    a brand-new event is being created by the operation.
    """
    nested = _nested_dir(slug)
    if nested:
        _game_dir, event_dir, _game, _event = nested
        return event_dir
    if not SLUG_RE.match(slug or ""):
        raise ProjectError(f"Invalid project name: {slug!r}")
    path = PROJECTS_ROOT / slug
    if PROJECTS_ROOT.resolve() not in path.resolve().parents and path.resolve() != PROJECTS_ROOT.resolve():
        raise ProjectError("Invalid project path")
    return path


def asset_root(slug: str) -> Path:
    """Root that holds a project's assets.

    Flat projects: themselves. Nested events: the outer game root — assets are
    shared by the whole game, so a nested story sees the same sprites and
    audio as its parent project.
    """
    nested = _nested_dir(slug)
    return nested[0] if nested else project_dir(slug)


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
    # Nested story: assets live on the outer game root (shared pool), not the
    # event folder. The editor should see the same character/sprite lists it
    # would for any story opened from the outer game.
    nested = _nested_dir(slug)
    asset_root = nested[0] if nested else path
    return {
        "slug": slug,
        "nested": nested is not None,
        "meta": meta,
        "files": files,
        "assets": list_assets(asset_root),
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


def _story_scaffold(target: Path, virtual_slug: str, merged: dict[str, Any]) -> dict[str, Any]:
    """Write the story folder and project.json. Internal use only.

    Hikarin Studio no longer has standalone story top-level projects: a story
    is a nested project under events/<event>/ of a game project. This helper
    does the folder scaffolding for such nested stories and is also used by
    the bundled-story import wrap. The path must have already been validated
    by the caller; ``virtual_slug`` is the 'game::event' routing slug used by
    save_project/load_project.
    """
    target.mkdir(parents=True, exist_ok=True)

    # Scaffold the mediafile layout so the folders are obvious the first time
    # the author opens the project in Explorer.
    (target / "images" / "characters").mkdir(parents=True, exist_ok=True)
    (target / "images" / "asset").mkdir(parents=True, exist_ok=True)
    (target / "sounds" / "music").mkdir(parents=True, exist_ok=True)
    (target / "sounds" / "sound").mkdir(parents=True, exist_ok=True)
    (target / "images" / "characters" / "Add Character Sprite Here.txt").write_text(
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
    (target / "images" / "asset" / "Add Background Here.txt").write_text(
        "Backgrounds go here, flat.\n\n"
        "Like:\n\n"
        "    end.png\n\n"
        "In a script, reference them as:\n\n"
        "    asset/end.png\n",
        encoding="utf-8",
    )
    (target / "sounds" / "sound" / "Add Sound Here.txt").write_text(
        "Sound effects go here, as .ogg files.\n\n"
        "In a script, a sound named click.ogg is referenced as:\n\n"
        "    click\n",
        encoding="utf-8",
    )
    (target / "sounds" / "music" / "Add Music Here.txt").write_text(
        "Music tracks go here, as .ogg files.\n\n"
        "In a script, a track named haggstrom.ogg is referenced as:\n\n"
        "    haggstrom\n",
        encoding="utf-8",
    )

    save_project(virtual_slug, merged, {"main.story": list(DEFAULT_MAIN)})
    return load_project(virtual_slug)




def create_event(game_slug: str, event: str, meta: dict[str, Any] | None = None) -> dict[str, Any]:
    """Create a nested story under a game project.

    Games are the only top-level projects: stories live under
    events/<event>/ inside a game, sharing the game's asset pool.
    """
    if not SLUG_RE.match(event or ""):
        raise ProjectError(f"Invalid event name: {event!r}")
    if "::" in game_slug:
        raise ProjectError(f"Game '{game_slug}' must be a flat name")
    game_dir = project_dir(game_slug)
    game_meta_file = game_dir / "project.json"
    if not game_meta_file.is_file():
        raise ProjectError(f"Game '{game_slug}' does not exist")
    try:
        game_meta = json.loads(game_meta_file.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        raise ProjectError(f"project.json is not valid JSON: {e}") from e
    if game_meta.get("kind") not in (None, "game"):
        raise ProjectError(f"Project '{game_slug}' is not a game project")
    target = (game_dir / EVENTS_DIRNAME / event).resolve()
    if game_dir.resolve() not in target.parents:
        raise ProjectError("Invalid event path")
    if target.exists() and any(target.iterdir()):
        raise ProjectError(f"Event '{event}' already exists")
    merged = dict(DEFAULT_PROJECT)
    if meta:
        merged.update(meta)
    if not merged.get("character"):
        merged["character"] = event
    return _story_scaffold(target, f"{game_slug}::{event}", merged)


def create_project(slug: str, meta: dict[str, Any] | None = None) -> dict[str, Any]:
    """Any top-level project is a game.

    Stories no longer exist as top-level projects; they live under
    events/<event>/ of a game project (see create_event).
    """
    merged = dict(meta or {})
    merged["kind"] = "game"
    return create_game_project(slug, merged)


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
    "startMap": "home",
}


def create_game_project(slug: str, meta: dict[str, Any] | None = None) -> dict[str, Any]:
    """Scaffold a game project: nested event slot, world folder, one main flow.

    The generated ``world/maps.json`` is a ready-to-boot skeleton: one map,
    one grass tile, one spawn cell. The author paints from there.
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

    (path / "images" / "characters" / "Add Character Sprite Here.txt").write_text(
        "Character sprites go in folders here. " + chr(10) + "The format is name/outfit/image.png " + chr(10) + "like: cupa/default/happy.png" + chr(10),
        encoding="utf-8",
    )
    (path / "images" / "asset" / "Add Background Here.txt").write_text(
        "Backgrounds go here, flat. Scripts reference them as: asset/end.png" + chr(10),
        encoding="utf-8",
    )

    (world / VARIABLES_FILE_NAME).write_text(
        json.dumps({"variables": []}, indent=2) + "\n", encoding="utf-8"
    )

    grass = ["grass"] * (16 * 16)
    maps = {
        "startMap": "home",
        "maps": {
            "home": {
                "cols": 16,
                "rows": 16,
                "tiles": grass,
                "palette": {
                    "grass": {"image": "asset/grass.png", "traversable": True},
                },
                "entities": [],
                "spawn": {"col": 8, "row": 8, "facing": "down"},
            },
        },
    }
    (world / "maps.json").write_text(json.dumps(maps, indent=2) + "\n", encoding="utf-8")

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

EVENTS_DIRNAME = "events"


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
    dest = dest_dir(new_slug)
    if dest.exists() and any(dest.iterdir()):
        raise ProjectError(f"Project '{new_slug}' already exists")
    shutil.copytree(src, dest)
    return load_project(new_slug)


def rename_project(slug: str, new_slug: str) -> dict[str, Any]:
    src = project_dir(slug)
    if not src.is_dir():
        raise ProjectError(f"Project '{slug}' does not exist")
    dest = dest_dir(new_slug)
    if dest.exists() and any(dest.iterdir()):
        raise ProjectError(f"Project '{new_slug}' already exists")
    src.rename(dest)
    return load_project(new_slug)


def import_project_zip(slug: str, payload: bytes) -> dict[str, Any]:
    """Import a .hikarin.zip game bundle (or any zip containing project.json).

    Bundles made from a game project import cleanly: project.json carries
    kind=game with events/ and world/. A loose standalone story bundle is
    refused: stories live inside games, so make a game and add the story as
    an event instead.
    """
    if not SLUG_RE.match(slug or ""):
        raise ProjectError(f"Invalid project name: {slug!r}")

    dest = project_dir(slug)
    if dest.exists() and any(dest.iterdir()):
        raise ProjectError(f"Project '{slug}' already exists")

    try:
        zf = zipfile.ZipFile(io.BytesIO(payload))
    except zipfile.BadZipFile as e:
        raise ProjectError(f"Not a valid zip file: {e}") from e

    names = zf.namelist()
    prefix = ""
    if "project.json" not in names:
        candidates = [n for n in names if n.endswith("/project.json")]
        if len(candidates) != 1:
            raise ProjectError("Zip must contain a single project.json")
        prefix = candidates[0][: -len("project.json")]
    meta_member = f"{prefix}project.json"

    try:
        meta = json.loads(zf.read(meta_member).decode("utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError) as e:
        raise ProjectError(f"project.json is not valid JSON: {e}") from e
    kind = (meta or {}).get("kind")
    if kind != "game":
        raise ProjectError(
            "This bundle contains a standalone story, which cannot exist on its own. "
            "Create a game, add the story as an event, and import the files there."
        )

    dest_path = dest.resolve()
    dest.mkdir(parents=True, exist_ok=True)
    try:
        for name in names:
            if name.endswith("/"):
                continue
            rel = name[len(prefix) :] if prefix else name
            target = dest / rel
            try:
                target.resolve().relative_to(dest_path)
            except ValueError:
                raise ProjectError(f"Zip entry escapes project folder: {name}") from None
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(zf.read(name))
    except Exception:
        shutil.rmtree(dest, ignore_errors=True)
        raise

    (dest / EVENTS_DIRNAME).mkdir(exist_ok=True)
    return load_project(slug)
