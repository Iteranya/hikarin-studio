"""Game projects: a folder of nested hikarin projects plus shared world data,
compiled into one ``build/`` folder the runtime engine loads.

Layout (one project = one game)::

    projects/my-game/
        project.json          {"kind": "game", "packName": ..., "startMap": "home"}
        world/
            variables.json     SHARED world-variable registry (all @world.*)
            maps.json          grid maps (tiles, palette, entities, spawn)
        events/
            <event-slug>/      a nested hikarin story project
                project.json    {"kind": "story", ...}
                <story>.story
        images/                shared assets (also served to the canvas)
        sounds/                shared assets
        build/                 ← export output, gitignored
            game.json          {meta, maps} — the world definition
            events/<slug>.json compiled event (hikarin JSON, verbatim)
            images/...
            sounds/...

Game logic lives inside hikarin itself: a map switch is a hikarin action
(``map``), conditional blocks are hikarin conditionals, and the world flags
run on the same variables the story already uses. There is no secondary
graph language.
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

GAME_KIND = "game"
EVENTS_DIRNAME = "events"
WORLD_DIRNAME = "world"
VARIABLES_FILE = "variables.json"
MAPS_FILE = "maps.json"
BUILD_DIRNAME = "build"

# ── registry validation ──────────────────────────────────────────────────────

_VALID_PRIMITIVES = ("string", "number", "boolean")
_NAME_RE = re.compile(r"^[a-z][a-z0-9_]{0,63}$")
_SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")


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


# ── maps validation ──────────────────────────────────────────────────────────

@dataclass
class MapsCheck:
    start_map: str | None = None
    maps: dict[str, Any] = field(default_factory=dict)
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


def load_maps(world_dir: Path, known_events: set[str] | None = None) -> MapsCheck:
    """Read and validate ``world/maps.json``.

    Expected shape::

        {
          "startMap": "home",
          "maps": {
            "home": {
              "cols": 16, "rows": 16,
              "tiles": ["grass", "wall_a", ...],       # cols*rows entries
              "palette": { "grass": {"image": "asset/grass.png", "traversable": true} },
              "entities": [ {"id": "statue", "kind": "static", "col": 7, "row": 3,
                             "event": "hestia", "visible_if": "", "interact_if": ""} ],
              "spawn": {"col": 2, "row": 8, "facing": "down"}
            }
          }
        }
    """
    check = MapsCheck()
    known = known_events or set()
    path = world_dir / MAPS_FILE
    if not path.is_file():
        check.warnings.append(f"{MAPS_FILE} not found — the engine has no map to boot from")
        return check
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        check.errors.append(f"{MAPS_FILE} is not valid JSON: {e}")
        return check
    if not isinstance(raw, dict):
        check.errors.append(f"{MAPS_FILE} must hold a JSON object")
        return check

    maps_obj = raw.get("maps")
    if not isinstance(maps_obj, dict) or not maps_obj:
        check.errors.append(f'{MAPS_FILE} must hold a non-empty "maps" object')
        return check

    start_map = raw.get("startMap") or next(iter(maps_obj))
    if not isinstance(start_map, str) or start_map not in maps_obj:
        check.errors.append(f'startMap "{start_map}" does not exist in maps')
        start_map = None

    for map_id, m in maps_obj.items():
        label = f'map "{map_id}"'
        if not _SLUG_RE.match(str(map_id)):
            check.errors.append(f'{label}: invalid map id {map_id!r} (lowercase, digits, _, -)')
            continue
        if not isinstance(m, dict):
            check.errors.append(f"{label}: must be an object")
            continue

        cols = m.get("cols")
        rows = m.get("rows")
        if not isinstance(cols, int) or not isinstance(rows, int) or cols < 1 or rows < 1:
            check.errors.append(f"{label}: cols and rows must be positive integers")
            continue

        palette = m.get("palette") or {}
        if not isinstance(palette, dict):
            check.errors.append(f"{label}: palette must be an object")
            continue
        for tile_id, entry in palette.items():
            if not isinstance(entry, dict):
                check.errors.append(f"{label}: tile {tile_id!r} palette entry must be an object")
                continue
            if not isinstance(entry.get("image"), str):
                check.errors.append(f"{label}: tile {tile_id!r} needs an image path")
            if not isinstance(entry.get("traversable"), bool):
                check.errors.append(f"{label}: tile {tile_id!r} needs traversable: true|false")

        tiles = m.get("tiles")
        if not isinstance(tiles, list):
            check.errors.append(f"{label}: tiles must be an array of tile ids")
            continue
        expected = cols * rows
        if len(tiles) != expected:
            check.errors.append(f"{label}: tiles has {len(tiles)} entries; expected {expected} ({cols}x{rows})")
        for index, tile_id in enumerate(tiles):
            if tile_id not in palette:
                check.errors.append(f"{label}: tiles[{index}] references unknown tile {tile_id!r}")
                break

        spawn = m.get("spawn") or {}
        if not isinstance(spawn, dict):
            check.errors.append(f"{label}: spawn must be an object")
            spawn = {}
        sc, sr = spawn.get("col", 0), spawn.get("row", 0)
        if not isinstance(sc, int) or not isinstance(sr, int) or not (0 <= sc < cols) or not (0 <= sr < rows):
            check.errors.append(f"{label}: spawn cell ({sc},{sr}) is outside the grid")
        if isinstance(spawn.get("facing"), str) and spawn["facing"] not in ("up", "down", "left", "right"):
            check.warnings.append(f"{label}: spawn facing should be up|down|left|right")

        entities = m.get("entities") or []
        if not isinstance(entities, list):
            check.errors.append(f"{label}: entities must be an array")
            entities = []
        seen_ids: set[str] = set()
        for entity in entities:
            if not isinstance(entity, dict):
                check.errors.append(f"{label}: entity entries must be objects")
                continue
            eid = entity.get("id")
            label_e = f"{label} entity {eid!r}"
            if not eid or not _SLUG_RE.match(str(eid)):
                check.errors.append(f"{label_e}: invalid id (lowercase, digits, _, -)")
                continue
            if eid in seen_ids:
                check.errors.append(f"{label_e}: duplicate entity id")
                continue
            seen_ids.add(eid)
            kind = entity.get("kind", "static")
            if kind not in ("static", "non-static"):
                check.errors.append(f"{label_e}: kind must be static|non-static")
                continue
            event = entity.get("event")
            if not event:
                check.errors.append(f"{label_e}: missing event slug")
            elif event not in known:
                check.errors.append(f'{label_e}: event "{event}" has no compiled event at events/{event}/')
            c, r = entity.get("col"), entity.get("row")
            if kind == "static" and (not isinstance(c, int) or not isinstance(r, int)):
                check.errors.append(f"{label_e}: static entity needs col/row")
            elif c is not None or r is not None:
                if not isinstance(c, int) or not isinstance(r, int) or not (0 <= c < cols) or not (0 <= r < rows):
                    check.errors.append(f"{label_e}: col/row ({c},{r}) is outside the grid")

    check.start_map = start_map
    check.maps = maps_obj
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

    for event_dir in event_dirs(game_path):
        event_slug = event_dir.name
        if not _SLUG_RE.match(event_slug):
            errors.append(f'Event folder "{event_slug}": invalid slug for an event; use lowercase, digits, _, -')
            continue
        try:
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
                    files[name] = None  # type: ignore[assignment]
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

    # ── world: registry + maps ───────────────────────────────────────────────
    world_dir = game_path / WORLD_DIRNAME
    registry = load_registry(world_dir)
    errors.extend(f"variables.json: {e}" for e in registry.errors)
    warnings.extend(f"variables.json: {w}" for w in registry.warnings)
    declared: set[str] = {v["name"] for v in registry.variables}

    maps = load_maps(world_dir, set(events_out))
    errors.extend(f"maps.json: {e}" for e in maps.errors)
    warnings.extend(f"maps.json: {w}" for w in maps.warnings)

    # ── unused registry entries: warn at export, never error ────────────────
    all_content = " ".join(p.read_text(encoding="utf-8") for p in events_build.glob("*.json") if p.is_file())
    if maps.maps:
        all_content += " " + json.dumps(maps.maps)
    for name in declared:
        if name in all_content:
            continue
        warnings.append(f'world variable "{name}" is declared but never referenced — export warning (not an error)')

    # ── assemble build/game.json ─────────────────────────────────────────────
    game_json = {
        "meta": {
            "packName": meta.get("packName", slug),
            "description": meta.get("description", ""),
            "version": meta.get("version", 1),
            "startMap": maps.start_map or meta.get("startMap"),
            "variables": registry.variables,
        },
        "maps": {
            "startMap": maps.start_map,
            "maps": maps.maps,
        },
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
        "variables": registry.variables,
        "maps": list(maps.maps),
        "startMap": maps.start_map,
        "errors": errors,
        "warnings": warnings,
    }
