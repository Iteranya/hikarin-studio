"""Asset inventory and mutation for a project's media folders.

The studio's mediafile layout, in one place::

    images/
        pack.png                                  resource pack icon
        characters/<id>/<outfit>/<emotion>.png    sprites
        asset/<background>.png                    backgrounds / image boxes
        <anything>/...                            extra image folders
    sounds/
        music/<track>.ogg
        sound/<sfx>.ogg

Reading is one pass (``inventory``). Writing is a handful of small operations the
asset manager window calls: create a character, add an outfit, make a folder,
drop files into a folder, delete a file or a folder.

Two rules hold everywhere here:

* every path that comes from the browser is relative to the project and must
  start with ``images/`` or ``sounds/`` — anything else, including ``..``, is a
  403-worthy mistake rather than a clever input;
* every name written to disk is squeezed to lowercase ``[a-z0-9._-]``, because
  these names become Minecraft texture paths and a space in a texture path is a
  sprite that silently does not load.
"""

from __future__ import annotations

import base64
import binascii
import re
import shutil
from pathlib import Path
from typing import Any

IMAGE_EXT = {".png", ".jpg", ".jpeg", ".webp"}
AUDIO_EXT = {".ogg", ".wav", ".mp3"}

# The two trees a project owns. Everything the asset manager writes lives under
# one of them; .story files and project.json are the editor's, not the assets'.
ROOTS = ("images", "sounds")

# Folders the scaffold depends on. Deleting the folder itself is a bug waiting to
# happen; deleting what is inside it is the actual intent.
PROTECTED = {
    "images",
    "sounds",
    "images/characters",
    "sounds/music",
    "sounds/sound",
}

# A single upload. Bigger than this is a video, and this is not a video tool.
MAX_UPLOAD_BYTES = 24 * 1024 * 1024

_JUNK = re.compile(r"[^a-z0-9._-]+")
_DASHES = re.compile(r"-{2,}")
_COMPONENT = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")


class AssetError(Exception):
    """A user-facing asset problem: bad name, bad path, missing file."""


# ── names and paths ─────────────────────────────────────────────────────────

def clean_name(raw: str) -> str:
    """A filename that is safe as a texture path, keeping a short extension.

    ``Screenshot 2024-01-01 at 12.00.00.png`` -> ``screenshot-2024-01-01-at-12-00-00.png``
    """
    text = (raw or "").strip().replace("\\", "/").split("/")[-1]
    stem, dot, ext = text.rpartition(".")
    if dot and ext and len(ext) <= 5 and ext.isalnum():
        name, suffix = stem, "." + ext.lower()
    else:
        name, suffix = text, ""

    name = _DASHES.sub("-", _JUNK.sub("-", name.lower())).strip("-._")
    return (name or "file") + suffix


def clean_component(raw: str, what: str = "name") -> str:
    """A folder-level name: character id, outfit, image folder.

    No extension, no dots at the ends, no spaces. These are path segments in a
    texture location, so the same rule as a filename applies minus the suffix.
    """
    text = _JUNK.sub("-", str(raw or "").strip().lower()).strip("-._")
    text = _DASHES.sub("-", text)
    if not text:
        raise AssetError(f"A {what} needs a name")
    if not _COMPONENT.match(text):
        raise AssetError(
            f"{what.capitalize()} name {text!r} is not usable — use lowercase letters, "
            "numbers, dashes or underscores, starting with a letter or number."
        )
    return text


def rel_parts(rel: str) -> list[str]:
    """Split a browser-supplied relative path and check it stays inside a root."""
    text = str(rel or "").replace("\\", "/").strip()
    parts = [p for p in text.split("/") if p not in ("", ".")]

    if not parts:
        raise AssetError("No path given")
    if any(p == ".." for p in parts):
        raise AssetError("Path escapes the project folder")
    if parts[0] not in ROOTS:
        raise AssetError(
            f"Assets live under {' or '.join(ROOTS)}/ — {parts[0]!r} is not an asset folder"
        )
    return parts


def resolve(project_path: Path, rel: str) -> Path:
    """Turn a relative asset path into a real path, refusing escapes."""
    parts = rel_parts(rel)
    base = project_path.resolve()
    target = project_path.joinpath(*parts)
    resolved = target.resolve()
    if resolved != base and base not in resolved.parents:
        raise AssetError("Path escapes the project folder")
    return target


# ── reading ─────────────────────────────────────────────────────────────────

def _entry(file: Path, project_path: Path, root: str) -> dict[str, Any]:
    """One file, described the way the asset window renders it.

    ``file`` is project-relative (``images/asset/end.png``) because that is what
    the delete endpoint and the preview URL want. ``path`` is relative to the
    asset root (``asset/end.png``) because that is what a script writes and what
    the block inspector's dropdowns already show.
    """
    stat = file.stat()
    return {
        "name": file.stem,
        "filename": file.name,
        "file": f"{root}/{file.relative_to(project_path / root).as_posix()}",
        "path": file.relative_to(project_path / root).as_posix(),
        "size": stat.st_size,
        "mtime": int(stat.st_mtime),
    }


def inventory(project_path: Path) -> dict[str, Any]:
    """Everything the editor's dropdowns and the asset window need.

    Keeps the flat keys the inspector already reads (``characters``,
    ``backgrounds``, ``folders``, ``sounds``, ``music``) and adds the tree the
    asset manager drives off (``characterTree``, ``imageFolders``, ``audio``).
    """
    images = project_path / "images"
    characters: dict[str, dict[str, set[str]]] = {}
    character_tree: list[dict[str, Any]] = []
    backgrounds: list[str] = []
    loose_images: list[dict[str, Any]] = []
    image_folders: dict[str, list[dict[str, Any]]] = {}
    music: list[dict[str, Any]] = []
    sounds: list[dict[str, Any]] = []

    if images.is_dir():
        for file in sorted(images.rglob("*")):
            if not file.is_file() or file.suffix.lower() not in IMAGE_EXT:
                continue

            parts = file.relative_to(images).as_posix().split("/")

            if len(parts) == 1:
                # images/pack.png is the pack icon, not a background.
                if parts[0] != "pack.png":
                    backgrounds.append(parts[0])
                    loose_images.append(_entry(file, project_path, "images"))
                continue

            if parts[0] == "characters" and len(parts) >= 4:
                character, outfit = parts[1], parts[2]
                characters.setdefault(character, {}).setdefault(outfit, set()).add(file.stem)
                continue

            # asset/<background>.png and anything else folder-shaped. These
            # double as the boxes a show_custom("<folder>", ...) stretches over
            # the screen, so they are indexed by folder as well as listed flat.
            backgrounds.append("/".join(parts))
            image_folders.setdefault("/".join(parts[:-1]), []).append(
                _entry(file, project_path, "images")
            )

    # The character tree, grouped for the asset window: one card per character,
    # one block per outfit, one tile per emotion.
    chars_root = images / "characters"
    if chars_root.is_dir():
        for char_dir in sorted(p for p in chars_root.iterdir() if p.is_dir()):
            outfits = []
            for outfit_dir in sorted(p for p in char_dir.iterdir() if p.is_dir()):
                tiles = [
                    _entry(f, project_path, "images")
                    for f in sorted(outfit_dir.iterdir())
                    if f.is_file() and f.suffix.lower() in IMAGE_EXT
                ]
                outfits.append(
                    {
                        "name": outfit_dir.name,
                        "dir": f"images/characters/{char_dir.name}/{outfit_dir.name}",
                        "images": tiles,
                    }
                )
            character_tree.append(
                {
                    "id": char_dir.name,
                    "dir": f"images/characters/{char_dir.name}",
                    "outfits": outfits,
                }
            )

    sounds_root = project_path / "sounds"
    if sounds_root.is_dir():
        for file in sorted(sounds_root.rglob("*")):
            if not file.is_file() or file.suffix.lower() not in AUDIO_EXT:
                continue
            entry = _entry(file, project_path, "sounds")
            if file.relative_to(sounds_root).as_posix().startswith("music/"):
                music.append(entry)
            else:
                sounds.append(entry)

    pack_icon = images / "pack.png"

    all_images = sum(
        len(outfit["images"]) for char in character_tree for outfit in char["outfits"]
    ) + sum(len(v) for v in image_folders.values()) + len(loose_images)

    def tree_bytes(root: Path) -> int:
        if not root.is_dir():
            return 0
        return sum(f.stat().st_size for f in root.rglob("*") if f.is_file())

    return {
        # flat, for the block inspector's dropdowns
        "characters": {
            char: {outfit: sorted(exprs) for outfit, exprs in sorted(outfits.items())}
            for char, outfits in sorted(characters.items())
        },
        # Backgrounds keep their folder prefix: a script writes asset/end.png
        "backgrounds": sorted(backgrounds),
        "folders": {
            name: sorted(i["name"] for i in imgs)
            for name, imgs in sorted(image_folders.items())
        },
        # Sound lists are relative to sounds/, matching the names a script uses.
        "sounds": [e["path"] for e in sounds],
        "music": [e["path"] for e in music],
        # tree, for the asset manager window
        "characterTree": character_tree,
        "imageFolders": [
            {"name": name, "dir": f"images/{name}", "images": imgs}
            for name, imgs in sorted(image_folders.items())
        ],
        "looseImages": loose_images,
        "audio": {"music": music, "sound": sounds},
        "packIcon": _entry(pack_icon, project_path, "images") if pack_icon.is_file() else None,
        "totals": {
            "characters": len(character_tree),
            "images": all_images,
            "audio": len(music) + len(sounds),
            "bytes": tree_bytes(images) + tree_bytes(sounds_root),
        },
        "limits": {
            "maxUploadBytes": MAX_UPLOAD_BYTES,
            "imageExt": sorted(IMAGE_EXT),
            "audioExt": sorted(AUDIO_EXT),
        },
    }


# ── writing ─────────────────────────────────────────────────────────────────

def create_character(project_path: Path, character: str, outfit: str = "default") -> dict[str, Any]:
    """Make ``images/characters/<id>/<outfit>/``.

    The outfit level is not optional — the engine builds
    ``characters/<id>/<outfit>/<emotion>.png`` — so creating a character always
    creates at least one outfit folder to drop images into.
    """
    name = clean_component(character, "character")
    outfit_name = clean_component(outfit or "default", "outfit")

    char_dir = project_path / "images" / "characters" / name
    outfit_dir = char_dir / outfit_name
    if outfit_dir.is_dir():
        raise AssetError(f"Character {name!r} already has a {outfit_name!r} outfit")
    outfit_dir.mkdir(parents=True, exist_ok=True)

    return {"character": name, "outfit": outfit_name, "dir": f"images/characters/{name}/{outfit_name}"}


def create_outfit(project_path: Path, character: str, outfit: str) -> dict[str, Any]:
    """Add another outfit folder under an existing character."""
    name = clean_component(character, "character")
    outfit_name = clean_component(outfit, "outfit")

    if not (project_path / "images" / "characters" / name).is_dir():
        raise AssetError(f"There is no character named {name!r}")
    outfit_dir = project_path / "images" / "characters" / name / outfit_name
    if outfit_dir.is_dir():
        raise AssetError(f"{name!r} already has a {outfit_name!r} outfit")
    outfit_dir.mkdir(parents=True, exist_ok=True)
    return {"character": name, "outfit": outfit_name, "dir": f"images/characters/{name}/{outfit_name}"}


def create_folder(project_path: Path, rel: str) -> dict[str, Any]:
    """Make an empty image folder, e.g. ``images/ui``."""
    parts = rel_parts(rel)
    if parts[0] != "images":
        raise AssetError("Only image folders can be created — audio lives in music/ and sound/")
    for raw in parts[1:]:
        clean_component(raw, "folder")

    target = resolve(project_path, rel)
    if target.is_file():
        raise AssetError(f"{rel} is a file, not a folder")
    target.mkdir(parents=True, exist_ok=True)
    return {"dir": "/".join(parts)}


def write_uploads(
    project_path: Path,
    rel_dir: str,
    files: list[tuple[str, bytes]],
) -> list[dict[str, Any]]:
    """Save uploaded blobs into a folder, cleaning each name on the way in."""
    target_dir = resolve(project_path, rel_dir)
    if target_dir.exists() and not target_dir.is_dir():
        raise AssetError(f"{rel_dir} is a file, not a folder")
    target_dir.mkdir(parents=True, exist_ok=True)

    written: list[dict[str, Any]] = []
    for raw_name, blob in files:
        if not blob:
            continue
        if len(blob) > MAX_UPLOAD_BYTES:
            raise AssetError(
                f"{raw_name} is {len(blob) // (1024 * 1024)} MB — the limit is "
                f"{MAX_UPLOAD_BYTES // (1024 * 1024)} MB per file"
            )

        name = clean_name(raw_name)
        suffix = Path(name).suffix.lower()
        if suffix not in IMAGE_EXT | AUDIO_EXT:
            raise AssetError(
                f"{raw_name}: only images ({', '.join(sorted(IMAGE_EXT))}) or audio "
                f"({', '.join(sorted(AUDIO_EXT))}) can be added"
            )

        destination = target_dir / name
        overwrote = destination.exists()
        destination.write_bytes(blob)
        written.append(
            {
                "file": f"{rel_dir.rstrip('/')}/{name}",
                "name": destination.stem,
                "renamedFrom": raw_name if raw_name != name else None,
                "overwrote": overwrote,
            }
        )
    return written


def delete_path(project_path: Path, rel: str) -> dict[str, Any]:
    """Remove an asset file, or an asset folder and everything in it."""
    parts = rel_parts(rel)
    joined = "/".join(parts)
    if joined in PROTECTED:
        raise AssetError(
            f"{joined}/ is part of the project layout — delete the files inside it instead"
        )

    target = resolve(project_path, rel)
    if not target.exists():
        raise AssetError(f"{rel} does not exist")

    if target.is_dir():
        shutil.rmtree(target)
        return {"deleted": joined, "kind": "folder"}
    target.unlink()
    return {"deleted": joined, "kind": "file"}


def decode_upload(data: str) -> bytes:
    """Decode a base64 payload from the browser, tolerating a data: URL prefix."""
    text = (data or "").strip()
    if text.startswith("data:"):
        _, _, text = text.partition(",")
    try:
        return base64.b64decode(text, validate=False)
    except (binascii.Error, ValueError) as e:
        raise AssetError(f"Upload data is not valid base64: {e}") from e
