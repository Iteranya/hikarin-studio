"""Project storage: a folder on disk is a project.

A **project** is a resource pack. A **story** is one character's script inside it.
The distinction is not cosmetic — the engine reads one JSON file per character,
keyed by the trigger (the story's lowercased name)::

    projects/<project>/
        project.json            pack name, description
        stories/
            <story>/
                story.json      character (the trigger), start label, file order
                main.story      the spine
                night.story
                idle.story      forty idle lines get their own tab
        images/                 shared sprites and backgrounds
            pack.png            the resource pack icon
            characters/
                cupa/
                    default/    outfit, always present
                        happy.png
            asset/              backgrounds
                end.png
        sounds/
            music/              haggstrom.ogg
            sound/              teleport.ogg

Three levels: project → story → ``.story`` files. A project with one story and a
project with six are the same shape, which is the point: adding a story must not
mean restructuring anything.

``images/`` and ``sounds/`` are shared by every story in the project. That is
what makes a pack a pack — the art is loaded once and every script refers to it.
``images/`` maps to ``textures/`` on export; that is the only rename. Sounds map
one-to-one. Scripts are generated, never hand-edited.

``.story`` files are JSON arrays of editor blocks, without ids. The compiler
assigns ids, so reordering blocks never causes a numbering conflict. Labels are
scoped to a story: a Jump in ``main.story`` can reach a label in ``night.story``,
but never a label in another story's script.

The SDK's own note on sprite layout::

    the format is

    name/outfit/images.png

    like:

    cupa/default/happy.png

    The mod as of writing this doesn't have swap outfit feature yet, but just in
    case and for the sake of future compatibility, add 'default' there, aight?
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
from .variables import load_variables, save_variables

PROJECTS_ROOT = Path(__file__).resolve().parent.parent / "projects"

SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")

STORIES_DIRNAME = "stories"

# No packFormat here on purpose: the resource pack version to target is an
# export option, not a property of the project. A project is a set of scripts
# and shared art; which runtime version you build them for is decided at export
# time (see hikarin.exporter.DEFAULT_PACK_FORMAT).
DEFAULT_PACK: dict[str, Any] = {
    "packName": "My Pack",
    "description": "Made with Hikarin Studio",
}

DEFAULT_STORY: dict[str, Any] = {
    "character": "",
    "description": "",
    "startLabel": "start",
}


class ProjectError(Exception):
    """Raised for user-facing project problems (bad name, missing file...)."""


# ── paths ───────────────────────────────────────────────────────────────────


def _check_slug(slug: str) -> str:
    if not SLUG_RE.match(slug or ""):
        raise ProjectError(
            f"Invalid name: {slug!r}. Use lowercase letters, numbers, - and _."
        )
    return slug


def project_dir(slug: str) -> Path:
    _check_slug(slug)
    path = PROJECTS_ROOT / slug
    # Guard against traversal even though the regex already forbids it.
    if (
        PROJECTS_ROOT.resolve() not in path.resolve().parents
        and path.resolve() != PROJECTS_ROOT.resolve()
    ):
        raise ProjectError("Invalid project path")
    return path


def stories_root(slug: str) -> Path:
    return project_dir(slug) / STORIES_DIRNAME


def story_dir(slug: str, story: str) -> Path:
    _check_slug(story)
    return stories_root(slug) / story


# ── reading ─────────────────────────────────────────────────────────────────


def _read_json(path: Path, what: str) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except OSError as e:
        raise ProjectError(f"Could not read {what}: {e}") from e
    except json.JSONDecodeError as e:
        raise ProjectError(f"{what} is not valid JSON: {e}") from e
    if not isinstance(data, dict):
        raise ProjectError(f"{what} must contain a JSON object")
    return data


def _story_names(path: Path) -> list[str]:
    """Story slugs on disk, sorted. A folder without story.json is not a story."""
    root = path / STORIES_DIRNAME
    if not root.is_dir():
        return []
    return sorted(
        entry.name
        for entry in root.iterdir()
        if entry.is_dir() and (entry / "story.json").is_file()
    )


def _safe_story_field(project_path: Path, story: str, key: str) -> str:
    """Read one string field from a story.json, tolerating a broken one."""
    target = project_path / STORIES_DIRNAME / story / "story.json"
    try:
        meta = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return ""
    value = meta.get(key) if isinstance(meta, dict) else None
    return value if isinstance(value, str) else ""


def _count_blocks(path: Path, meta: dict[str, Any]) -> int:
    total = 0
    for name in meta.get("files") or []:
        target = path / name
        if not target.is_file():
            continue
        try:
            blocks = json.loads(target.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if isinstance(blocks, list):
            total += len(blocks)
    return total


def _story_summary(project_path: Path, story: str) -> dict[str, Any]:
    """One story's metadata, without reading every block."""
    path = project_path / STORIES_DIRNAME / story
    meta = _read_json(path / "story.json", f"stories/{story}/story.json")
    return {
        "slug": story,
        "character": meta.get("character") or story,
        "description": meta.get("description") or "",
        "startLabel": meta.get("startLabel") or "start",
        "files": list(meta.get("files") or []),
        "blockCount": _count_blocks(path, meta),
    }


def list_projects() -> list[dict[str, Any]]:
    """Every project folder under the projects root, with its story list.

    Metadata only: the manager page draws this to render a list, and parsing
    every block of every script to do that is how a launcher gets slow.
    """
    if not PROJECTS_ROOT.is_dir():
        return []
    found: list[dict[str, Any]] = []
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
        if not isinstance(meta, dict):
            continue
        stories = [
            {
                "slug": name,
                "character": _safe_story_field(entry, name, "character") or name,
            }
            for name in _story_names(entry)
        ]
        found.append(
            {
                "slug": entry.name,
                "packName": meta.get("packName") or entry.name,
                "description": meta.get("description", ""),
                "storyCount": len(stories),
                "stories": stories,
            }
        )
    return found


def _story_summaries(project_path: Path) -> list[dict[str, Any]]:
    """Every story in a project folder, as summaries."""
    return [_story_summary(project_path, name) for name in _story_names(project_path)]


def load_project(slug: str) -> dict[str, Any]:
    """A project and every story in it.

    Returns ``{"slug", "meta", "stories": [{slug, character, description,
    startLabel, files, blockCount}]}``.
    """
    path = project_dir(slug)
    meta_file = path / "project.json"
    if not meta_file.is_file():
        raise ProjectError(f"Project '{slug}' has no project.json")

    meta = _read_json(meta_file, "project.json")
    stories = _story_summaries(path)
    meta["stories"] = [s["slug"] for s in stories]

    return {"slug": slug, "meta": meta, "stories": stories}


def load_story(slug: str, story: str) -> dict[str, Any]:
    """Read one story and all its ``.story`` files.

    Returns ``{"slug", "projectSlug", "meta", "files": {name: [block]},
    "assets": [...]}``. Assets are project-level, but they ride along because
    every picker in the inspector reads them.
    """
    path = _require_story_manifest(slug, story)
    meta = _read_json(path / "story.json", f"stories/{story}/story.json")

    names = list(meta.get("files") or [])
    # Include any .story file on disk that story.json forgot about.
    for found in sorted(path.rglob("*.story")):
        rel = found.relative_to(path).as_posix()
        if rel not in names:
            names.append(rel)

    files: dict[str, list[dict]] = {}
    for name in names:
        target = path / name
        if not target.is_file():
            files[name] = []
            continue
        try:
            data = json.loads(target.read_text(encoding="utf-8"))
        except json.JSONDecodeError as e:
            raise ProjectError(f"{name} is not valid JSON: {e}") from e
        if not isinstance(data, list):
            raise ProjectError(f"{name} must contain a JSON array of blocks")
        files[name] = data

    meta["files"] = names
    return {
        "slug": story,
        "projectSlug": slug,
        "meta": meta,
        "files": files,
        "assets": list_assets(project_dir(slug)),
        # The project's declared variables. Every variable field in the inspector
        # picks from this, so opening a story must already know them — one more
        # request per story open would be a request per keystroke's undo.
        "variables": load_variables(project_dir(slug)),
        # The other stories in this project, so the editor's story switcher can
        # be drawn without a second request. This story is included; the caller
        # marks which one is current.
        "siblings": [
            s for s in _story_summaries(project_dir(slug)) if s["slug"] != story
        ],
    }


def _require_story(slug: str, story: str) -> Path:
    """The story folder, which must already exist.

    Only the folder is required, not the manifest: creating a story makes the
    folder and then writes its first manifest through the same path the editor
    saves through. Requiring ``story.json`` here would mean create cannot use
    its own writer. A save into a deleted story still fails, because the folder
    goes with it — that is the invariant that matters.
    """
    path = story_dir(slug, story)
    if not path.is_dir():
        raise ProjectError(f"Story '{story}' does not exist in '{slug}'")
    return path


def _require_story_manifest(slug: str, story: str) -> Path:
    """The story folder, which must have a readable story.json."""
    path = _require_story(slug, story)
    if not (path / "story.json").is_file():
        raise ProjectError(f"Story '{story}' has no story.json")
    return path


# ── writing ─────────────────────────────────────────────────────────────────


def _write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )


def save_project_meta(slug: str, meta: dict[str, Any]) -> dict[str, Any]:
    """Write project.json. Story metadata is not touched here."""
    path = project_dir(slug)
    if not (path / "project.json").is_file():
        raise ProjectError(f"Project '{slug}' does not exist")

    clean = {k: v for k, v in meta.items() if k != "stories"}
    _write_json(path / "project.json", clean)
    return load_project(slug)


def save_story(
    slug: str, story: str, meta: dict[str, Any], files: dict[str, list[dict]]
) -> dict[str, Any]:
    """Write story.json and every ``.story`` file.

    Files removed from ``files`` are deleted from disk, so deleting a tab in the
    editor actually removes the file rather than leaving an orphan that would be
    re-discovered on next load.
    """
    path = _require_story(slug, story)

    existing = {p.relative_to(path).as_posix() for p in path.rglob("*.story")}
    for gone in existing - set(files):
        try:
            (path / gone).unlink()
        except OSError:
            pass

    for name, blocks in files.items():
        target = path / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(
            json.dumps(blocks, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )

    clean = {k: v for k, v in meta.items() if k != "files"}
    clean["files"] = list(files)
    _write_json(path / "story.json", clean)
    return load_story(slug, story)


# ── create / delete / duplicate / rename ────────────────────────────────────


def _scaffold_assets(path: Path) -> None:
    """Scaffold the mediafile layout so the folders are obvious on first open."""
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


def _default_blocks(character: str) -> dict[str, list[dict]]:
    return {
        "main.story": [
            {"kind": "label", "data": {"name": "start"}},
            {
                "kind": "say",
                "data": {"label": character or "Narrator", "content": "Hello there."},
            },
            {"kind": "end", "data": {}},
        ]
    }


def create_project(slug: str, meta: dict[str, Any] | None = None) -> dict[str, Any]:
    """A project is a folder with a pack manifest. Stories are added after."""
    path = project_dir(slug)
    if path.exists() and any(path.iterdir()):
        raise ProjectError(f"Project '{slug}' already exists")

    _scaffold_assets(path)
    merged = dict(DEFAULT_PACK)
    if meta:
        merged.update({k: v for k, v in meta.items() if k != "stories"})
    merged["packName"] = merged.get("packName") or slug
    _write_json(path / "project.json", merged)

    return load_project(slug)


def create_story(
    slug: str, story: str, meta: dict[str, Any] | None = None
) -> dict[str, Any]:
    """A story is a folder with a manifest and one starter ``.story`` file."""
    if not project_dir(slug).is_dir():
        raise ProjectError(f"Project '{slug}' does not exist")

    path = story_dir(slug, story)
    if path.exists() and any(path.iterdir()):
        raise ProjectError(f"Story '{story}' already exists")

    merged = dict(DEFAULT_STORY)
    if meta:
        merged.update({k: v for k, v in meta.items() if k != "files"})
    merged["character"] = merged.get("character") or story

    # save_story() refuses to invent a story folder — it writes into one that
    # is already there, so a save can never resurrect a deleted story. Creating
    # one means making the folder first, then handing it to the same writer the
    # editor uses.
    path.mkdir(parents=True, exist_ok=True)
    return save_story(slug, story, merged, _default_blocks(merged["character"]))


def delete_project(slug: str) -> None:
    path = project_dir(slug)
    if not path.is_dir():
        raise ProjectError(f"Project '{slug}' does not exist")
    shutil.rmtree(path)


def delete_story(slug: str, story: str) -> None:
    path = _require_story(slug, story)
    shutil.rmtree(path)


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


def duplicate_story(slug: str, story: str, new_story: str) -> dict[str, Any]:
    src = _require_story(slug, story)
    dest = story_dir(slug, new_story)
    if dest.exists() and any(dest.iterdir()):
        raise ProjectError(f"Story '{new_story}' already exists")
    shutil.copytree(src, dest)
    meta = _read_json(dest / "story.json", f"stories/{new_story}/story.json")
    meta["character"] = new_story
    _write_json(dest / "story.json", meta)
    return load_story(slug, new_story)


def rename_story(
    slug: str, story: str, new_story: str, character: str | None = None
) -> dict[str, Any]:
    """Move a story folder, and optionally change its character.

    The character name is the engine's trigger, so it usually matches the folder
    name. When it does — the common case, because a new story takes its character
    from its slug — renaming follows through, so the story keeps exporting under
    the name you just gave it. When the author deliberately set a different
    character name, that name is left alone: it is a decision, not a default.

    ``character`` sets it explicitly, which is why the rename dialog can change
    both without a second write. It takes a character argument rather than being
    a separate save call on purpose: a save replaces every ``.story`` file, so
    re-uploading them to change one string is how a rename turns into data loss.

    No ``.story`` file is read or written here. Renaming moves blocks, it does
    not rewrite them.
    """
    path = _require_story_manifest(slug, story)
    dest = story_dir(slug, new_story)
    if dest.exists() and any(dest.iterdir()):
        raise ProjectError(f"Story '{new_story}' already exists")

    meta = _read_json(path / "story.json", f"stories/{story}/story.json")
    was_default = (meta.get("character") or story) == story
    path.rename(dest)
    if character:
        meta["character"] = character
    elif was_default:
        meta["character"] = new_story
    _write_json(dest / "story.json", meta)
    return load_story(slug, new_story)


# ── compile ─────────────────────────────────────────────────────────────────


def compile_slug(slug: str, story: str) -> CompileResult:
    loaded = load_story(slug, story)
    return compile_project(loaded["meta"], loaded["files"])


def compile_all_stories(slug: str) -> dict[str, CompileResult]:
    """Compile every story, keyed by story slug. What the pack export ships."""
    project = load_project(slug)
    return {s["slug"]: compile_slug(slug, s["slug"]) for s in project["stories"]}


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


# ── import ──────────────────────────────────────────────────────────────────


def import_project_zip(slug: str, payload: bytes) -> dict[str, Any]:
    """Import a ``.hikarin.zip`` bundle: a project.json plus stories/."""
    dest = project_dir(slug)
    if dest.exists() and any(dest.iterdir()):
        raise ProjectError(f"Project '{slug}' already exists")
    try:
        zf = zipfile.ZipFile(io.BytesIO(payload))
    except zipfile.BadZipFile as e:
        raise ProjectError(f"Not a valid zip file: {e}") from e

    names = zf.namelist()
    # Find project.json at root or one level deep.
    prefix = ""
    if "project.json" not in names:
        candidates = [n for n in names if n.endswith("/project.json")]
        if len(candidates) != 1:
            raise ProjectError("Zip must contain a single project.json")
        prefix = candidates[0][: -len("project.json")]

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