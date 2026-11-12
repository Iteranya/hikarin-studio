"""Game projects: a folder of nested hikarin projects plus a world model,
compiled into one ``build/`` folder the runtime engine loads.

Layout (one project = one orchestrator)::

    projects/my-game/
        project.json          {"kind": "game", "packName": ..., "start": "start"}
        world/
            <name>.orch        the orchestrator graph (see orchestrator.py)
            variables.json     SHARED world-variable registry (all @world.*)
            maps.json          OPTIONAL map definitions (tiles, palette, entities)
        events/
            <event-slug>/      a nested hikarin project (story kind), compiled output = build/events/<slug>.json
                project.json    {"kind": "story", ...}
                <story>.story
        images/                shared assets
        sounds/                shared assets
        build/                 ← export output, gitignored
            game.json          the orchestrator: {meta, maps, script}
            events/<slug>.json compiled event
            images/...

One project is one orchestrator. An orchestrator just like a script is composed
of many source files before compiled together into a single json in the end
product. The game output is *multiple* json: one orchestrator + one per event.
"""

from __future__ import annotations

import json
import re
import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from . import projects as project_store
from .compiler import compile_project
from .orchestrator import compile_orch_files, load_orch_files

GAME_KIND = "game"
EVENTS_DIRNAME = "events"
WORLD_DIRNAME = "world"
VARIABLES_FILE = "variables.json"
MAPS_FILE = "maps.json"
BUILD_DIRNAME = "build"
ORCH_GLOB = "*.orch"

# ── registry validation ──────────────────────────────────────────────────────

_VALID_PRIMITIVES = ("string", "number", "boolean")
_NAME_RE = re.compile(r"^[a-z][a-z0-9_]{0,63}$")


@dataclass
class RegistryCheck:
    variables: list[dict[str, Any]] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


def load_registry(world_dir: Path) -> RegistryCheck:
    """Read and validate ``world/variables.json``.

    Flat table, ``@world.*`` only: each entry needs ``name``, ``type``
    (JSON primitive), ``default`` matching ``type``, optional ``desc``.
    Duplicate names are errors; non-primitive types are errors; entries
    unused anywhere are warnings (never errors). Unknown names referenced by
    scripts are warnings at export, not errors — the author may still
    reference a flag the engine will create at first set.
    """
    check = RegistryCheck()
    path = world_dir / VARIABLES_FILE
    if not path.is_file():
        # Registry is optional. Absence = free-text variables everywhere.
        return check
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        check.errors.append(f"{VARIABLES_FILE} is not valid JSON: {e}")
        return check

    entries = raw.get("variables") if isinstance(raw, dict) else raw
    if not isinstance(entries, list):
        check.errors.append(f"{VARIABLES_FILE} must hold a JSON array of variables")
        return check

    seen: set[str] = set()
    for index, entry in enumerate(entries):
        if not isinstance(entry, dict):
            check.errors.append(f"variables[{index}]: entry must be an object")
            continue
        name = entry.get("name", "")
        if not _NAME_RE.match(str(name)):
            check.errors.append(f"variables[{index}]: invalid name {name!r} (lowercase, digits, _, starts with a letter)")
            continue
        if name in seen:
            check.errors.append(f'Duplicate world variable "{name}"')
            continue
        seen.add(name)
        vtype = entry.get("type", "string")
        if vtype not in _VALID_PRIMITIVES:
            check.errors.append(f"variables[{index}] ({name}): type must be one of {_VALID_PRIMITIVES}")
            continue
        default = entry.get("default")
        ok = (
            (vtype == "string" and isinstance(default, str))
            or (vtype == "number" and isinstance(default, (int, float)) and not isinstance(default, bool))
            or (vtype == "boolean" and isinstance(default, bool))
        )
        if not ok:
            check.errors.append(f"variables[{index}] ({name}): default does not match type {vtype}")
            continue
        check.variables.append(
            {
                "name": name,
                "type": vtype,
                "default": default,
                "desc": str(entry.get("desc", "")),
            }
        )
    return check


# ── game loading ─────────────────────────────────────────────────────────────

def is_game_meta(meta: dict[str, Any]) -> bool:
    return (meta or {}).get("kind") == GAME_KIND


def event_dirs(game_path: Path) -> list[Path]:
    """Nested hikarin projects under events/, one folder per event."""
    root = game_path / EVENTS_DIRNAME
    if not root.is_dir():
        return []
    out = []
    for child in sorted(root.iterdir()):
        if child.is_dir() and (child / "project.json").is_file():
            out.append(child)
    return out


def compile_game(slug: str, root: Path | None = None) -> dict[str, Any]:
    """Build the whole game: per-event JSON + game.json + assets.

    Returns a dict: success flag, output dir, file list, warnings/errors,
    and the compiled counts for the caller (studio UI, CI) to display.
    """
    base = root or project_store.PROJECTS_ROOT
    game_path = base / slug
    if not game_path.is_dir():
        raise project_store.ProjectError(f"Game '{slug}' does not exist")

    meta_file = game_path / "project.json"
    if not meta_file.is_file():
        raise project_store.ProjectError(f"Game '{slug}' has no project.json")
    try:
        meta = json.loads(meta_file.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        raise project_store.ProjectError(f"project.json is not valid JSON: {e}") from e
    if not is_game_meta(meta):
        raise project_store.ProjectError(
            f"project '{slug}' is not a game project (kind={meta.get('kind')!r}). "
            f'Set "kind": "game" in project.json to build it as a game.'
        )

    errors: list[str] = []
    warnings: list[str] = []

    # ── events: compile each nested story project ───────────────────────────
    events_out: list[str] = []
    build_dir = game_path / BUILD_DIRNAME
    events_build = build_dir / "events"
    events_build.mkdir(parents=True, exist_ok=True)

    event_info: list[tuple[str, list[str]]] = []   # (slug, file list)
    for event_dir in event_dirs(game_path):
        event_slug = event_dir.name
        if not re.match(r"^[a-z0-9][a-z0-9_-]{0,63}$", event_slug):
            errors.append(f'Event folder "{event_slug}": invalid slug for an event; use lowercase, digits, _, -')
            continue
        try:
            # Reuse the story compiler unchanged — an event is just a story.
            event_project = json.loads((event_dir / "project.json").read_text(encoding="utf-8"))
            if is_game_meta(event_project):
                errors.append(f'events/{event_slug}: nested games are not supported; folders are hikarin story projects')
                continue
            files: dict[str, list[dict]] = {}
            names = list(event_project.get("files") or [])
            for story in sorted(event_dir.rglob("*.story")):
                rel = story.relative_to(event_dir).as_posix()
                if rel not in names:
                    names.append(rel)
            for name in names:
                story_path = event_dir / name
                if not story_path.is_file():
                    files[name] = []
                    continue
                try:
                    data = json.loads(story_path.read_text(encoding="utf-8"))
                except json.JSONDecodeError as e:
                    errors.append(f'events/{event_slug}/{name} is not valid JSON: {e}')
                    files[name] = None
                    continue
                files[name] = data
            if any(v is None for v in files.values()):
                continue
            result = compile_project(event_project, files)
        except project_store.ProjectError as e:
            errors.append(f'events/{event_slug}: {e}')
            continue
        if result.errors:
            for err in result.errors:
                errors.append(f'events/{event_slug}: {err}')
            continue
        warnings.extend(result.warnings)
        out_file = events_build / f"{event_slug}.json"
        out_file.write_text(json.dumps(result.actions, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        events_out.append(event_slug)
        event_info.append((event_slug, names))

    # ── world: registry + maps + orchestrator ────────────────────────────────
    world_dir = game_path / WORLD_DIRNAME
    registry = load_registry(world_dir)
    errors.extend(f"variables.json: {e}" for e in registry.errors)
    warnings.extend(f"variables.json: {w}" for w in registry.warnings)
    declared: set[str] = {v["name"] for v in registry.variables}

    maps: dict[str, Any] = {}
    maps_path = world_dir / MAPS_FILE
    if maps_path.is_file():
        try:
            maps = json.loads(maps_path.read_text(encoding="utf-8"))
            if not isinstance(maps, dict):
                errors.append(f"{MAPS_FILE} must hold a JSON object of map definitions")
                maps = {}
        except json.JSONDecodeError as e:
            errors.append(f"{MAPS_FILE} is not valid JSON: {e}")

    orch_files: dict[str, Any] = {}
    if world_dir.is_dir():
        orch_files = load_orch_files(world_dir)
    orch = compile_orch_files(orch_files)
    errors.extend(f"orchestrator: {e}" for e in orch["errors"])
    warnings.extend(f"orchestrator: {w}" for w in orch["warnings"])

    # ── cross-check the orchestrator against the registry and the events ────
    known_events = set(events_out)
    for action in orch.get("actions", []):
        if action.get("type") == "run_event" and action.get("event"):
            if action["event"] not in known_events:
                errors.append(f'run_event "{action["event"]}" has no compiled event at events/{action["event"]}/')
        if action.get("type") == "set_world":
            raw = str(action.get("var", ""))
            name = raw.removeprefix("@world.")
            if name and name not in declared:
                warnings.append(f'set_world references undeclared world variable "{name}" (free-text allowed)')
        if action.get("type") == "conditional":
            raw = str(action.get("var", ""))
            name = raw.removeprefix("@world.")
            if name and name not in declared:
                warnings.append(f'conditional references undeclared world variable "{name}" (free-text allowed)')

    # ── unused registry entries: warn at export, never error ────────────────
    referenced: set[str] = set()
    for action in orch.get("actions", []):
        for key in ("var", "value"):
            v = action.get(key)
            if isinstance(v, str):
                referenced.add(v.removeprefix("@world."))
    # Events also reference world flags; do the same walk on compiled event output.
    all_event_json = " ".join(p.read_text(encoding="utf-8") for p in events_build.glob("*.json") if p.is_file())
    for name in declared:
        if name in all_event_json or name in referenced:
            continue
        warnings.append(f'world variable "{name}" is declared but never referenced — export warning (not an error)')

    # ── assemble build/game.json ─────────────────────────────────────────────
    game_json = {
        "meta": {
            "packName": meta.get("packName", slug),
            "description": meta.get("description", ""),
            "version": meta.get("version", 1),
            "start": meta.get("start", "start"),
            "variables": registry.variables,
        },
        "maps": maps,
        "script": orch.get("actions", []),
    }
    (build_dir / "game.json").write_text(
        json.dumps(game_json, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )

    # ── shared assets, copied into build/ ────────────────────────────────────
    for asset_dir in ("images", "sounds"):
        src = game_path / asset_dir
        if not src.is_dir():
            continue
        for file in src.rglob("*"):
            if not file.is_file():
                continue
            rel = file.relative_to(src)
            dest = build_dir / asset_dir / rel
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(file, dest)

    return {
        "ok": not errors,
        "slug": slug,
        "buildDir": build_dir,
        "events": events_out,
        "actions": len(orch.get("actions", [])),
        "variables": registry.variables,
        "errors": errors,
        "warnings": warnings,
    }
