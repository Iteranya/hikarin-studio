"""Resource pack export.

Takes a project's compiled actions and produces a zip that Minecraft will load
as a resource pack::

    <pack>.zip
        pack.mcmeta
        pack.png                       (optional)
        assets/hikarin/<character>.json    <- the compiled story
        assets/hikarin/textures/...        <- copied from the project's assets/

The engine reads scenes from ``assets/hikarin/<trigger>.json``, where the
trigger is the character's name (the maid's custom name, lowercased). Textures
resolve from the same namespace first, then the framework's own art, then a
2024-era ``mobtalkerredux`` pack.

Pack format for Minecraft 1.20.1 is 15.
"""

from __future__ import annotations

import io
import json
import zipfile
from pathlib import Path

from .compiler import CompileResult

MC_PACK_FORMAT_1201 = 15

# Namespace the engine reads scenes and textures from.
CONTENT_NAMESPACE = "hikarin"


def build_pack(
    meta: dict,
    result: CompileResult,
    project_path: Path,
) -> bytes:
    """Return the bytes of a resource pack zip.

    Raises ValueError if the compile produced errors, because shipping a broken
    story is worse than refusing to ship.
    """
    if result.errors:
        raise ValueError("Cannot export: the story has compile errors.")

    character = (meta.get("character") or "character").lower().replace(" ", "_")
    pack_name = meta.get("packName") or character
    description = meta.get("description") or "Made with Hikarin Studio"
    pack_format = int(meta.get("packFormat") or MC_PACK_FORMAT_1201)

    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as zf:
        # pack.mcmeta — Minecraft reads this to know the pack exists and its version.
        mcmeta = {
            "pack": {
                "description": f"{description}\nCharacter: {character}",
                "pack_format": pack_format,
            }
        }
        zf.writestr("pack.mcmeta", json.dumps(mcmeta, indent=2))

        # pack.png — the icon shown in the resource pack list. In the mediafile
        # layout it lives at images/pack.png.
        icon = project_path / "images" / "pack.png"
        if icon.is_file():
            zf.write(icon, "pack.png")

        # The story itself. The SDK generated this into scripts/ at compile
        # time; here it is written fresh on every export, which is why there is
        # no scripts/ folder to hand-edit.
        zf.writestr(
            f"assets/{CONTENT_NAMESPACE}/{character}.json",
            json.dumps(result.actions, indent=2, ensure_ascii=False),
        )

        # images/ becomes textures/. That single rename is the whole mapping,
        # and it is why the authoring folders are named after what they hold
        # rather than after Minecraft's internal layout.
        #
        # Note the pack.png exclusion: it was already written at the zip root,
        # and copying it again as a texture would ship a stray image.
        images = project_path / "images"
        if images.is_dir():
            for file in images.rglob("*"):
                if not file.is_file() or file.suffix.lower() not in (".png", ".jpg", ".jpeg"):
                    continue
                rel = file.relative_to(images).as_posix()
                if rel == "pack.png":
                    continue
                zf.write(file, f"assets/{CONTENT_NAMESPACE}/textures/{rel}")

        # sounds/ maps one-to-one, keeping the music/ and sound/ split.
        sounds = project_path / "sounds"
        if sounds.is_dir():
            for file in sounds.rglob("*"):
                if not file.is_file() or file.suffix.lower() not in (".ogg", ".wav", ".mp3"):
                    continue
                rel = file.relative_to(sounds).as_posix()
                zf.write(file, f"assets/{CONTENT_NAMESPACE}/sounds/{rel}")

    return buffer.getvalue()


def export_filename(meta: dict) -> str:
    """A safe file name for the zip, e.g. 'Cupa's Story' -> cupa-s-story.zip."""
    raw = (meta.get("packName") or meta.get("character") or "story").lower()
    safe = "".join(c if c.isalnum() else "-" for c in raw).strip("-")
    while "--" in safe:
        safe = safe.replace("--", "-")
    return f"{safe or 'story'}.zip"
