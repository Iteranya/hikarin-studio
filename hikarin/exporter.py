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


# ── extra export formats ────────────────────────────────────────────────────

EXPORT_FORMATS = ("pack", "json", "txt", "md", "bundle")


def _id_to_label(actions):
    out = {}
    for a in actions:
        if a.get("type") == "label":
            out[a.get("id")] = a.get("label", "")
    return out


def _label_for_id(actions, target_id):
    return _id_to_label(actions).get(target_id, f"id {target_id}")


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


def build_project_bundle(meta, files, project_path: Path) -> bytes:
    """Zip the whole authoring project so it can be imported back."""
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as zf:
        meta2 = dict(meta)
        meta2["files"] = list(files.keys())
        zf.writestr("project.json", json.dumps(meta2, indent=2, ensure_ascii=False) + "\n")
        written = set()
        for name, blocks in files.items():
            zf.writestr(name, json.dumps(blocks, indent=2, ensure_ascii=False) + "\n")
            written.add(name)
        # assets
        for sub in ("images", "sounds", "world", "events"):
            root = project_path / sub
            if root.is_dir():
                for f in sorted(root.rglob("*")):
                    if f.is_file():
                        rel = f.relative_to(project_path).as_posix()
                        if rel in written:
                            continue
                        zf.write(f, rel)
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
    return export_filename(meta)
