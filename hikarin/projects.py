"""Project storage: a folder on disk is a project.

Layout (owned by the studio, living under ``projects/``)::

    projects/cupa/
        project.json     character, pack name, file order, start label
        main.story       the spine
        night.story
        idle.story
        assets/          sprites, backgrounds, sounds (optional)

``.story`` files are JSON arrays of editor blocks, without ids. The compiler
assigns ids. Keeping the source id-free means reordering blocks in the editor
never produces a merge conflict over numbering.
"""

from __future__ import annotations

import json
import re
import shutil
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
        found.append(
            {
                "slug": entry.name,
                "character": meta.get("character", entry.name),
                "packName": meta.get("packName", entry.name),
                "files": meta.get("files", []),
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
    path = project_dir(slug)
    if path.exists() and any(path.iterdir()):
        raise ProjectError(f"Project '{slug}' already exists")
    path.mkdir(parents=True, exist_ok=True)
    (path / "assets").mkdir(exist_ok=True)

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
    """Inventory the project's assets folder, grouped for the editor.

    Sprite layout mirrors the original SDK exactly:

        characters/<character id>/<outfit>/<emotion>.png

    so the Show block can offer a character, then that character's outfits, then
    the emotions inside the chosen outfit — instead of asking the writer to
    remember folder names.

    A flat image is a background. Anything else with an image extension and at
    least two path segments is treated as a sprite, with a missing outfit level
    read as "default" so hand-made two-level folders still work.

    Returns::

        {
          "characters": { "<id>": { "<outfit>": ["<emotion>", ...] } },
          "backgrounds": [...],
          "sounds": [...],
        }
    """
    root = path / "assets"
    characters: dict[str, dict[str, set[str]]] = {}
    backgrounds: list[str] = []
    sounds: list[str] = []

    if not root.is_dir():
        return {"characters": {}, "backgrounds": [], "sounds": []}

    for file in root.rglob("*"):
        if not file.is_file():
            continue
        rel = file.relative_to(root).as_posix()
        lower = rel.lower()

        if lower.endswith((".ogg", ".wav", ".mp3")):
            sounds.append(rel)
        elif lower.endswith((".png", ".jpg", ".jpeg")):
            parts = rel.split("/")
            if len(parts) == 1:
                backgrounds.append(rel)
                continue

            # Drop the leading "characters/" so both layouts read the same:
            #   characters/<id>/<outfit>/<emotion>.png   (SDK)
            #   <id>/<outfit>/<emotion>.png              (bare)
            sprite_parts = parts[1:] if parts[0] == "characters" else parts

            emotion = sprite_parts[-1].rsplit(".", 1)[0]
            character = sprite_parts[0]
            outfit = sprite_parts[-2] if len(sprite_parts) >= 3 else "default"
            characters.setdefault(character, {}).setdefault(outfit, set()).add(emotion)

    return {
        "characters": {
            char: {outfit: sorted(exprs) for outfit, exprs in sorted(outfits.items())}
            for char, outfits in sorted(characters.items())
        },
        "backgrounds": sorted(backgrounds),
        "sounds": sorted(sounds),
    }
