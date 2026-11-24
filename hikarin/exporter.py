"""Export builders.

Two shapes for the same compiled scripts:

:func:`build_hikarin` — the Hikarin bundle. ``manifest.json``, one script per
story at the root, art as authored. Runtime-agnostic, and the default to reach
for.
:func:`build_pack` — a resource pack. The same scripts arranged for a loader
that expects ``pack.mcmeta``, an ``assets/<namespace>/`` prefix and a
``textures/`` rename.

Also here: the human-readable script renderers (``.txt`` / ``.md``) and the
re-importable project bundle.

---

Resource pack layout::

    <pack>.zip
        pack.mcmeta
        pack.png                             (optional)
        assets/hikarin/<story>.json          <- one compiled story per character
        assets/hikarin/textures/...          <- copied from the project's images/
        assets/hikarin/sounds/...            <- copied from the project's sounds/

The engine reads scenes from ``assets/hikarin/<trigger>.json``, where the
trigger is the character's name (the story's custom name, lowercased). One file
per character is the whole reason a project can hold several stories.

Textures resolve from the same namespace first, then the framework's own art,
then a legacy 2024-era pack under the ``mobtalkerredux:`` namespace.

``pack.mcmeta`` and ``pack_format`` are the resource pack format's own file and
field names, not ours to rename — they are what the runtime reads. The default
below is the value for 1.20.1.
"""

from __future__ import annotations

import io
import json
import zipfile
from pathlib import Path
from typing import Any

from .compiler import CompileResult

DEFAULT_PACK_FORMAT = 15

# Namespace the engine reads scenes and textures from.
CONTENT_NAMESPACE = "hikarin"

IMAGE_EXT = (".png", ".jpg", ".jpeg")
SOUND_EXT = (".ogg", ".wav", ".mp3")


def script_slug(character: str, script: str) -> str:
    """The flat file name for one script inside an export zip.

    ``<character>_<script>`` — the character prefix is what disambiguates two
    scripts that share a name under different characters (miku's ``main`` and
    rue's ``main`` become ``miku_main`` and ``rue_main``). Lowercased, spaces to
    underscores, so the result is a safe file name and a stable engine trigger.
    """
    raw = f"{character}_{script}".strip().lower().replace(" ", "_")
    return raw or "script"


def story_filename(story_meta: dict, slug: str | None = None, disambiguate: bool = False) -> str:
    """Deprecated: use :func:`script_slug`.

    Kept for a single-script export that only has a story meta with a
    ``character`` and no separate script name — it falls back to the character
    as the script, which yields ``<character>_<character>`` collapsed to the
    character alone when there is nothing to disambiguate.
    """
    character = story_meta.get("character") or story_meta.get("slug") or slug or "story"
    if slug and slug != character:
        return script_slug(character, slug)
    return str(character).strip().lower().replace(" ", "_")


def _split_key(key: str, story_meta: dict) -> tuple[str, str]:
    """Recover ``(character, script)`` from a ``"character/script"`` key.

    The exporter is fed the composite keys ``compile_all_scripts`` produces, but
    a caller that only has a story meta still works: fall back to the meta's
    ``character`` and the key as the script.
    """
    if "/" in key:
        character, script = key.split("/", 1)
        return character, script
    character = story_meta.get("character") or key
    return character, key


def build_pack(
    meta: dict,
    stories: dict[str, tuple[dict, CompileResult]],
    project_path: Path,
    pack_format: int | None = None,
) -> bytes:
    """Return the bytes of a resource pack zip.

    Args:
        meta:   the project manifest (packName, description).
        stories: ``{"<character>/<script>": (story meta, compile result)}``.
        project_path: the project folder, for images/ and sounds/.
        pack_format: the resource pack format version to target. Defaults to
            ``DEFAULT_PACK_FORMAT``. This is an export concern, not a project
            property: the same pack of scripts can be built for several runtime
            versions, so it belongs on this call rather than in project.json.

    Layout is flat: one ``<character>_<script>.json`` per script at
    ``assets/hikarin/``. The character prefix disambiguates two scripts that
    share a name under different characters.

    Raises ValueError if any script failed to compile, because shipping a broken
    script is worse than refusing to ship.
    """
    broken = [
        f"{key}: {result.errors[0]}"
        for key, (_story_meta, result) in stories.items()
        if result.errors
    ]
    if broken:
        raise ValueError(
            "Cannot export, a script has compile errors:\n  " + "\n  ".join(broken)
        )
    if not stories:
        raise ValueError("Cannot export: this project has no scripts.")

    description = meta.get("description") or "Made with Hikarin Studio"
    if pack_format is None:
        pack_format = DEFAULT_PACK_FORMAT

    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as zf:
        # pack.mcmeta — the format's own manifest: it tells the runtime this
        # pack exists and which format version it targets.
        mcmeta = {
            "pack": {
                "description": f"{description}\nScripts: {len(stories)}",
                "pack_format": pack_format,
            }
        }
        zf.writestr("pack.mcmeta", json.dumps(mcmeta, indent=2))

        # pack.png — the icon shown in the resource pack list. In the mediafile
        # layout it lives at images/pack.png.
        icon = project_path / "images" / "pack.png"
        if icon.is_file():
            zf.write(icon, "pack.png")

        # One flat JSON per script, named <character>_<script>.json.
        written: dict[str, str] = {}
        for key, (story_meta, result) in stories.items():
            character, script = _split_key(key, story_meta)
            filename = script_slug(character, script)
            if filename in written:
                raise ValueError(
                    f'Scripts "{written[filename]}" and "{key}" both compile to '
                    f"{filename}.json. Give each script a distinct name."
                )
            written[filename] = key
            zf.writestr(
                f"assets/{CONTENT_NAMESPACE}/{filename}.json",
                json.dumps(result.actions, indent=2, ensure_ascii=False),
            )

        # images/ becomes textures/. That single rename is the whole mapping,
        # and it is why the authoring folders are named after what they hold
        # rather than after the pack layout.
        #
        # Note the pack.png exclusion: it was already written at the zip root,
        # and copying it again as a texture would ship a stray image.
        images = project_path / "images"
        if images.is_dir():
            for file in sorted(images.rglob("*")):
                if not file.is_file() or file.suffix.lower() not in IMAGE_EXT:
                    continue
                rel = file.relative_to(images).as_posix()
                if rel == "pack.png":
                    continue
                zf.write(file, f"assets/{CONTENT_NAMESPACE}/textures/{rel}")

        # sounds/ maps one-to-one, keeping the music/ and sound/ split.
        sounds = project_path / "sounds"
        if sounds.is_dir():
            for file in sorted(sounds.rglob("*")):
                if not file.is_file() or file.suffix.lower() not in SOUND_EXT:
                    continue
                rel = file.relative_to(sounds).as_posix()
                zf.write(file, f"assets/{CONTENT_NAMESPACE}/sounds/{rel}")

    return buffer.getvalue()


def build_hikarin(
    meta: dict,
    stories: dict[str, tuple[dict, CompileResult]],
    project_path: Path,
) -> bytes:
    """Return the Hikarin bundle: a manifest plus plain files.

    This is the format the project is named after and the one to reach for by
    default. A directory another program can read without knowing anything about
    resource packs::

        manifest.json
        <trigger>.json        compiled script, one per story
        images/...            as authored
        sounds/...            as authored

    :func:`build_pack` produces the same content in a resource-pack layout — a
    ``pack.mcmeta``, an ``assets/<namespace>/`` prefix and a ``textures/``
    rename. That is a packaging convention for one runtime, not a better shape,
    so this one keeps the author's folder names and adds only a manifest: which
        files are scripts, which trigger maps to which story, and where the art
        lives.
    """
    broken = [
        f"{key}: {result.errors[0]}"
        for key, (_story_meta, result) in stories.items()
        if result.errors
    ]
    if broken:
        raise ValueError(
            "Cannot export, a script has compile errors:\n  " + "\n  ".join(broken)
        )
    if not stories:
        raise ValueError("Cannot export: this project has no scripts.")

    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as zf:
        scripts: list[dict[str, Any]] = []
        seen: dict[str, str] = {}

        for key, (story_meta, result) in stories.items():
            character, script = _split_key(key, story_meta)
            filename = script_slug(character, script)
            if filename in seen:
                raise ValueError(
                    f'Scripts "{seen[filename]}" and "{key}" both compile to '
                    f"{filename}.json. Give each script a distinct name."
                )
            seen[filename] = key
            zf.writestr(
                f"{filename}.json",
                json.dumps(result.actions, indent=2, ensure_ascii=False),
            )
            scripts.append(
                {
                    "character": character,
                    "script": script,
                    "file": f"{filename}.json",
                    "actions": len(result.actions),
                    "startLabel": story_meta.get("startLabel") or "start",
                }
            )

        manifest = {
            "format": "hikarin",
            "version": 1,
            "packName": meta.get("packName") or "Hikarin Pack",
            "description": meta.get("description") or "",
            "namespace": CONTENT_NAMESPACE,
            "scripts": scripts,
            "images": "images/",
            "sounds": "sounds/",
        }
        zf.writestr("manifest.json", json.dumps(manifest, indent=2, ensure_ascii=False))

        for sub in ("images", "sounds"):
            root = project_path / sub
            if not root.is_dir():
                continue
            for file in sorted(root.rglob("*")):
                if not file.is_file():
                    continue
                if file.suffix.lower() not in (IMAGE_EXT + SOUND_EXT):
                    continue
                rel = file.relative_to(project_path).as_posix()
                if rel == "images/pack.png":
                    # The pack icon is a resource-pack concept. In a plain
                    # bundle it is just another image, and shipping it twice
                    # (root and images/) is worse than leaving it where it is.
                    continue
                zf.write(file, rel)

    return buffer.getvalue()


def export_filename(meta: dict) -> str:
    """A safe file name for the zip, e.g. 'Cupa's Story' -> cupa-s-story.zip."""
    raw = (meta.get("packName") or meta.get("slug") or "pack").lower()
    safe = "".join(c if c.isalnum() else "-" for c in raw).strip("-")
    while "--" in safe:
        safe = safe.replace("--", "-")
    return f"{safe or 'pack'}.zip"


# ── extra export formats ────────────────────────────────────────────────────


EXPORT_FORMATS = ("pack", "hikarin", "json", "txt", "md", "bundle")


def _id_to_label(actions):
    out = {}
    for a in actions:
        if a.get("type") == "label":
            out[a.get("id")] = a.get("label", "")
    return out


def _render_script(meta, result, markdown=False):
    """Render compiled actions as a human-readable script (.txt / .md)."""
    if result.errors:
        raise ValueError("Cannot export: the story has compile errors.")

    actions = result.actions
    by_id = _id_to_label(actions)
    title = meta.get("packName") or meta.get("character") or "Story"
    character = meta.get("character") or ""

    lines = []
    if markdown:
        lines.append(f"# {title}")
        lines.append("")
        if character:
            lines.append(f"*Character: {character}*")
            lines.append("")
    else:
        lines.append(title.upper())
        lines.append("=" * len(title))
        if character:
            lines.append(f"Character: {character}")
        lines.append("")

    current_label = None

    def heading(name):
        if markdown:
            lines.append(f"## {name}")
            lines.append("")
        else:
            lines.append(f"--- {name} ---")
            lines.append("")

    def say(speaker, content):
        if markdown:
            lines.append(f"**{speaker or 'Narration'}:** {content}")
        else:
            lines.append(f"{speaker or 'Narration'}: {content}")
        lines.append("")

    def line(text, bullet=False, blank=True):
        if markdown and bullet:
            lines.append(f"- {text}")
        elif bullet:
            lines.append(f"  - {text}")
        else:
            lines.append(text)
        if blank:
            lines.append("")

    for a in actions:
        t = a.get("type")
        if t == "meta":
            continue
        if t == "label":
            current_label = a.get("label", "")
            heading(current_label)
            continue
        if current_label is None:
            current_label = "start"
            heading(current_label)

        if t == "dialogue":
            say(a.get("label") or "Narration", a.get("content", ""))
        elif t in ("choice", "night_choice"):
            prefix = "Night choice" if t == "night_choice" else "Choice"
            if markdown:
                lines.append(f"*{prefix}:*")
            else:
                lines.append(f"[{prefix}]")
            lines.append("")
            for c in a.get("choice") or []:
                line(f"{c.get('display','')} -> {c.get('label','')}", bullet=True, blank=False)
            lines.append("")
        elif t == "show_sprite":
            line(f"[Show {a.get('sprite','')} at {a.get('location','')}]")
        elif t == "remove_sprite":
            line(f"[Hide {a.get('sprite','')}]")
        elif t == "modify_background":
            line(f"[Background: {a.get('background','')}]")
        elif t == "clear_background":
            line("[Clear background]")
        elif t == "transition" and a.get("action") == "jump":
            line(f"[Jump to {a.get('label','')}]")
        elif t in ("conditional", "conditional_global"):
            target = by_id.get(a.get("end"), f"id {a.get('end')}")
            var = a.get("var", "")
            cond = a.get("condition", "")
            val = a.get("value", "")
            if cond in ("day", "night"):
                line(f"[If it is {cond} -> otherwise jump to {target}]")
            elif "value" in a:
                line(f"[If {var} {cond} {val!r} -> otherwise jump to {target}]")
            else:
                line(f"[If {var} {cond} -> otherwise jump to {target}]")
        elif t == "next":
            line(f"[Resume point: {a.get('label','')}]")
        elif t == "finish_dialogue":
            line("[End scene]")
        elif t == "modify_variable":
            line(f"[Set {a.get('var','')} {a.get('action','set')} {a.get('value','')!r}]")
        elif t == "unlock_dialogues":
            line(f"[Unlock: {', '.join(a.get('events') or [])}]")
        elif t == "give_item":
            line(f"[Give {a.get('amount',1)}x {a.get('item','')}]")
        elif t == "take_item":
            line(f"[Take {a.get('amount',1)}x {a.get('item','')}]")
        elif t == "play_music":
            line(f"[Music: {a.get('music') or 'stop'}]")
        elif t == "play_sound":
            line(f"[Sound: {a.get('sound','')}]")
        elif t == "command":
            line(f"[Command: {a.get('command','')}]")
        elif t == "play_level":
            line(f"[Play level: {a.get('level','')}]")
        elif t == "idle_chat":
            line("[Idle chat: jump to a random unlocked label]")
        else:
            line(f"[{t}]")

    return "\n".join(lines).rstrip() + "\n"


def build_json(meta, result) -> bytes:
    if result.errors:
        raise ValueError("Cannot export: the story has compile errors.")
    return json.dumps(result.actions, indent=2, ensure_ascii=False).encode("utf-8")


def build_text(meta, result) -> bytes:
    return _render_script(meta, result, markdown=False).encode("utf-8")


def build_markdown(meta, result) -> bytes:
    return _render_script(meta, result, markdown=True).encode("utf-8")


def build_project_bundle(meta, stories, project_path: Path) -> bytes:
    """Zip the whole authoring project so it can be imported back.

    ``stories`` is ``{"<character>/<script>": (script meta, files)}`` — the
    bundle carries the authoring blocks, not the compiled actions, because a
    bundle exists to be reopened in the editor.

    This is the only export that mirrors the on-disk nesting:
    ``stories/<character>/<script>/story.json`` plus each ``.story`` tab. A
    re-import recreates the same tree, so a project round-trips byte-for-byte
    at the folder level. The compiled exports (hikarin, pack) flatten to
    ``<character>_<script>.json`` slugs; the bundle keeps the folders because
    its whole job is to be opened again.
    """
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as zf:
        meta2 = {k: v for k, v in meta.items() if k != "stories"}
        meta2["stories"] = [
            key for key, (_sm, _files) in stories.items()
        ]
        zf.writestr("project.json", json.dumps(meta2, indent=2, ensure_ascii=False) + "\n")

        for key, (story_meta, files) in stories.items():
            character, script = _split_key(key, story_meta)
            body = {k: v for k, v in story_meta.items() if k != "files"}
            body["files"] = list(files)
            body["character"] = character
            zf.writestr(
                f"stories/{character}/{script}/story.json",
                json.dumps(body, indent=2, ensure_ascii=False) + "\n",
            )
            for name, blocks in files.items():
                zf.writestr(
                    f"stories/{character}/{script}/{name}",
                    json.dumps(blocks, indent=2, ensure_ascii=False) + "\n",
                )

        # assets
        for sub in ("images", "sounds"):
            root = project_path / sub
            if root.is_dir():
                for f in sorted(root.rglob("*")):
                    if f.is_file():
                        zf.write(f, f.relative_to(project_path).as_posix())

    return buffer.getvalue()


def export_filename_for(meta, fmt: str) -> str:
    base_name = export_filename(meta)[:-4]  # strip .zip
    if fmt == "json":
        return (meta.get("character") or base_name).lower() + ".json"
    if fmt == "txt":
        return f"{base_name}.txt"
    if fmt == "md":
        return f"{base_name}.md"
    if fmt == "bundle":
        return f"{base_name}.hikarin.zip"
    if fmt == "hikarin":
        return f"{base_name}-hikarin.zip"
    return export_filename(meta)