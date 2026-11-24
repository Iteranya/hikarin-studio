"""Project storage: a folder on disk is a project.

A **project** is a resource pack. Inside it, a **character** is one in-game
person, and a **script** is one of that character's conversations. A script is
made of one or more ``.story`` files (tabs). Four levels::

    projects/<project>/
        project.json            pack name, description
        stories/
            <character>/        one folder per character (a person)
                <script>/       one folder per script (a conversation)
                    story.json  character, start label, file order
                    main.story  the spine
                    night.story
                    idle.story  forty idle lines get their own tab
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

A project with one character and a project with six are the same shape, and so
is a character with one script versus six: adding either must not mean
restructuring anything. The character folder is what groups a person's
conversations together; the script folder is one conversation, built from its
own ``.story`` tabs.

``story.json`` keeps its ``character`` field even though the parent folder
already names the character: the manifest is what the editor and the exporter
read, and duplicating the name there keeps a script self-describing when it is
moved between folders.

``images/`` and ``sounds/`` are shared by every script in the project. That is
what makes a pack a pack — the art is loaded once and every script refers to
it. ``images/`` maps to ``textures/`` on export; that is the only rename.
Sounds map one-to-one. Scripts are generated, never hand-edited.

``.story`` files are JSON arrays of editor blocks, without ids. The compiler
assigns ids, so reordering blocks never causes a numbering conflict. Labels are
scoped to a script: a Jump in ``main.story`` can reach a label in
``night.story``, but never a label in another script.

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


def character_dir(slug: str, character: str) -> Path:
    """The folder holding one character's scripts."""
    _check_slug(character)
    return stories_root(slug) / character


def script_dir(slug: str, character: str, script: str) -> Path:
    """One script's folder: ``stories/<character>/<script>/``."""
    _check_slug(script)
    return character_dir(slug, character) / script


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


def _dir_with_manifests(root: Path) -> list[str]:
    """Child folders of ``root`` that hold a story.json, sorted."""
    if not root.is_dir():
        return []
    return sorted(
        entry.name
        for entry in root.iterdir()
        if entry.is_dir() and (entry / "story.json").is_file()
    )


def _character_names(path: Path) -> list[str]:
    """Character folders on disk, sorted.

    A character folder is any subfolder of ``stories/`` that contains at least
    one script folder (a child holding a story.json). An empty or stray folder
    is not a character.
    """
    root = path / STORIES_DIRNAME
    if not root.is_dir():
        return []
    names = []
    for entry in root.iterdir():
        if not entry.is_dir():
            continue
        if any(
            child.is_dir() and (child / "story.json").is_file()
            for child in entry.iterdir()
        ):
            names.append(entry.name)
    return sorted(names)


def _script_names(path: Path, character: str) -> list[str]:
    """Script folders for one character, sorted. A folder without story.json is
    not a script."""
    return _dir_with_manifests(path / STORIES_DIRNAME / character)


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


def _script_summary(project_path: Path, character: str, script: str) -> dict[str, Any]:
    """One script's metadata, without reading every block.

    ``character`` is the folder the script lives in — the source of truth. The
    manifest's own ``character`` field is a fallback for an older script that
    predates the character folder, but the folder wins when both exist.
    """
    path = project_path / STORIES_DIRNAME / character / script
    meta = _read_json(path / "story.json", f"stories/{character}/{script}/story.json")
    return {
        "character": character,
        "script": script,
        "description": meta.get("description") or "",
        "startLabel": meta.get("startLabel") or "start",
        "files": list(meta.get("files") or []),
        "blockCount": _count_blocks(path, meta),
    }


def _character_summaries(project_path: Path) -> list[dict[str, Any]]:
    """Every character in a project, each with its scripts.

    This is the shape the manager renders: a character is a group, and its
    scripts are the entries inside it.
    """
    characters: list[dict[str, Any]] = []
    for character in _character_names(project_path):
        scripts = [
            _script_summary(project_path, character, script)
            for script in _script_names(project_path, character)
        ]
        characters.append({"character": character, "scripts": scripts})
    return characters


def _all_script_refs(project_path: Path) -> list[dict[str, str]]:
    """Flat ``[{character, script}]`` for every script, for the story switcher."""
    refs: list[dict[str, str]] = []
    for character in _character_names(project_path):
        for script in _script_names(project_path, character):
            refs.append({"character": character, "script": script})
    return refs


def list_projects() -> list[dict[str, Any]]:
    """Every project folder under the projects root, with its character list.

    Metadata only: the manager page draws this to render a list, and parsing
    every block of every script to do that is how a launcher gets slow. Counts
    are derived from the tree so the caller never has to.
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
        characters = _character_summaries(entry)
        script_count = sum(len(c["scripts"]) for c in characters)
        found.append(
            {
                "slug": entry.name,
                "packName": meta.get("packName") or entry.name,
                "description": meta.get("description", ""),
                "characterCount": len(characters),
                "scriptCount": script_count,
                # Kept for the flat story-count chip some callers still read.
                "storyCount": script_count,
                "characters": characters,
            }
        )
    return found


def load_project(slug: str) -> dict[str, Any]:
    """A project, its characters, and every script inside them.

    Returns ``{"slug", "meta", "characters": [{character, scripts: [{character,
    script, description, startLabel, files, blockCount}]}], "scripts": [...]}``
    where ``scripts`` is the flat list (handy for a switcher).
    """
    path = project_dir(slug)
    meta_file = path / "project.json"
    if not meta_file.is_file():
        raise ProjectError(f"Project '{slug}' has no project.json")

    meta = _read_json(meta_file, "project.json")
    characters = _character_summaries(path)
    flat = [s for c in characters for s in c["scripts"]]

    # project.json's own "stories" mirror is kept flat for any external reader,
    # but the tree above is the truth the app uses.
    meta["stories"] = [f'{s["character"]}/{s["script"]}' for s in flat]

    return {
        "slug": slug,
        "meta": meta,
        "characters": characters,
        "scripts": flat,
    }


def load_script(slug: str, character: str, script: str) -> dict[str, Any]:
    """Read one script and all its ``.story`` files.

    Returns ``{"character", "script", "projectSlug", "meta", "files": {name:
    [block]}, "assets": [...], "variables": {...}, "siblings": [...]}``. Assets
    and variables are project-level, but they ride along because every picker in
    the inspector reads them; siblings are the other scripts in the project, so
    the editor's switcher draws with no second request.
    """
    path = _require_script_manifest(slug, character, script)
    meta = _read_json(
        path / "story.json", f"stories/{character}/{script}/story.json"
    )

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
    # The folder is the source of truth for the character; keep the manifest in
    # step so it round-trips correctly, but do not let a stale field override it.
    meta["character"] = character

    return {
        "character": character,
        "script": script,
        "projectSlug": slug,
        "meta": meta,
        "files": files,
        "assets": list_assets(project_dir(slug)),
        # The project's declared variables. Every variable field in the inspector
        # picks from this, so opening a script must already know them — one more
        # request per script open would be a request per keystroke's undo.
        "variables": load_variables(project_dir(slug)),
        # Every other script in this project, so the editor's switcher can be
        # drawn without a second request. This script is included; the caller
        # marks which one is current.
        "siblings": [
            s
            for s in _all_script_refs(project_dir(slug))
            if not (s["character"] == character and s["script"] == script)
        ],
    }


def _require_script(slug: str, character: str, script: str) -> Path:
    """The script folder, which must already exist.

    Only the folder is required, not the manifest: creating a script makes the
    folder and then writes its first manifest through the same path the editor
    saves through. Requiring ``story.json`` here would mean create cannot use
    its own writer. A save into a deleted script still fails, because the folder
    goes with it — that is the invariant that matters.
    """
    path = script_dir(slug, character, script)
    if not path.is_dir():
        raise ProjectError(
            f"Script '{character}/{script}' does not exist in '{slug}'"
        )
    return path


def _require_script_manifest(slug: str, character: str, script: str) -> Path:
    """The script folder, which must have a readable story.json."""
    path = _require_script(slug, character, script)
    if not (path / "story.json").is_file():
        raise ProjectError(
            f"Script '{character}/{script}' has no story.json"
        )
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


def save_script(
    slug: str,
    character: str,
    script: str,
    meta: dict[str, Any],
    files: dict[str, list[dict]],
) -> dict[str, Any]:
    """Write story.json and every ``.story`` file for one script.

    Files removed from ``files`` are deleted from disk, so deleting a tab in the
    editor actually removes the file rather than leaving an orphan that would be
    re-discovered on next load.
    """
    path = _require_script(slug, character, script)

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
    # The parent folder is the source of truth for the character; keep the
    # manifest's own field in step so it round-trips correctly.
    clean["character"] = character
    _write_json(path / "story.json", clean)
    return load_script(slug, character, script)


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


def create_script(
    slug: str,
    character: str,
    script: str,
    meta: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """A script is a folder under its character with a manifest and one starter
    ``.story`` file.

    Uniqueness is on the ``(character, script)`` pair, so the same script name
    can exist under two different characters without colliding.
    """
    if not project_dir(slug).is_dir():
        raise ProjectError(f"Project '{slug}' does not exist")

    path = script_dir(slug, character, script)
    if path.exists() and any(path.iterdir()):
        raise ProjectError(
            f"Script '{character}/{script}' already exists"
        )

    merged = dict(DEFAULT_STORY)
    if meta:
        merged.update({k: v for k, v in meta.items() if k != "files"})
    merged["character"] = character

    # save_script() refuses to invent a script folder — it writes into one that
    # is already there, so a save can never resurrect a deleted script. Creating
    # one means making the folders first, then handing it to the same writer the
    # editor uses.
    path.mkdir(parents=True, exist_ok=True)
    return save_script(slug, character, script, merged, _default_blocks(character))


def delete_project(slug: str) -> None:
    path = project_dir(slug)
    if not path.is_dir():
        raise ProjectError(f"Project '{slug}' does not exist")
    shutil.rmtree(path)


def delete_script(slug: str, character: str, script: str) -> None:
    path = _require_script(slug, character, script)
    shutil.rmtree(path)
    # If the character has no scripts left, drop its now-empty folder too, so
    # the tree never carries an empty character group.
    char_path = character_dir(slug, character)
    if char_path.is_dir() and not any(char_path.iterdir()):
        try:
            char_path.rmdir()
        except OSError:
            pass


def delete_character(slug: str, character: str) -> None:
    """Remove a character and every script under it."""
    path = character_dir(slug, character)
    if not path.is_dir():
        raise ProjectError(
            f"Character '{character}' does not exist in '{slug}'"
        )
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


def duplicate_script(
    slug: str,
    character: str,
    script: str,
    new_script: str,
    new_character: str | None = None,
) -> dict[str, Any]:
    """Copy a script folder to a new script name, optionally under a different
    character. Defaults to the same character."""
    src = _require_script(slug, character, script)
    target_character = new_character or character
    dest = script_dir(slug, target_character, new_script)
    if dest.exists() and any(dest.iterdir()):
        raise ProjectError(
            f"Script '{target_character}/{new_script}' already exists"
        )
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(src, dest)
    meta = _read_json(
        dest / "story.json",
        f"stories/{target_character}/{new_script}/story.json",
    )
    meta["character"] = target_character
    _write_json(dest / "story.json", meta)
    return load_script(slug, target_character, new_script)


def rename_script(
    slug: str,
    character: str,
    script: str,
    new_script: str,
    new_character: str | None = None,
) -> dict[str, Any]:
    """Move a script folder to a new name, and optionally to a new character.

    Both the script name and the character can change in one call — the rename
    dialog sets both without a second write, because a save replaces every
    ``.story`` file and re-uploading them to change one string is how a rename
    turns into data loss.

    ``new_character`` moves the script under a different character folder; when
    omitted the character is unchanged. The manifest's ``character`` field is
    rewritten to match the destination folder.

    No ``.story`` file is read or written here. Renaming moves blocks, it does
    not rewrite them.
    """
    path = _require_script_manifest(slug, character, script)
    target_character = new_character or character
    dest = script_dir(slug, target_character, new_script)
    if dest.exists() and any(dest.iterdir()):
        raise ProjectError(
            f"Script '{target_character}/{new_script}' already exists"
        )

    meta = _read_json(
        path / "story.json",
        f"stories/{character}/{script}/story.json",
    )
    dest.parent.mkdir(parents=True, exist_ok=True)
    path.rename(dest)
    meta["character"] = target_character
    _write_json(dest / "story.json", meta)

    # If the old character folder is now empty (the script moved away), drop it
    # so the tree never carries an empty group.
    if target_character != character:
        old_char = character_dir(slug, character)
        if old_char.is_dir() and not any(old_char.iterdir()):
            try:
                old_char.rmdir()
            except OSError:
                pass

    return load_script(slug, target_character, new_script)


# ── compile ─────────────────────────────────────────────────────────────────


def compile_script(slug: str, character: str, script: str) -> CompileResult:
    loaded = load_script(slug, character, script)
    return compile_project(loaded["meta"], loaded["files"])


def compile_all_scripts(slug: str) -> dict[str, CompileResult]:
    """Compile every script, keyed by ``"<character>/<script>"``.

    That composite key is what the export iterates — it carries both halves of
    the identity, so the exporter can group by character and still name a
    script's slug without a second lookup.
    """
    project = load_project(slug)
    return {
        f'{s["character"]}/{s["script"]}': compile_script(
            slug, s["character"], s["script"]
        )
        for s in project["scripts"]
    }


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
            # The common cause by far: this is an exported resource pack, not a
            # project bundle. Both are .zip, and the pack has no project.json —
            # it has pack.mcmeta and assets/. Saying only "must contain a single
            # project.json" reads like a corrupt file rather than the wrong
            # export button.
            if "pack.mcmeta" in names or any(n.startswith("assets/") for n in names):
                raise ProjectError(
                    "That is a resource pack, not a project bundle. A pack is what "
                    "the game loads (pack.mcmeta and assets/); a bundle is what "
                    "this tool re-imports (project.json and stories/). Export it "
                    "again with Export bundle, not Export pack."
                )
            if candidates:
                raise ProjectError(
                    f"Zip has {len(candidates)} project.json files; expected one."
                )
            raise ProjectError(
                "No project.json in that zip, so it is not a project bundle. "
                "Export it again with Backup."
            )
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