"""Shared variable registry.

A project declares its **global** variables here: the names every story in the
pack reads and writes. ``affection``, ``story_complete``, ``unlockedEnding``.

Why a registry at all: a global flag typed by hand in six blocks across four
stories ends up spelled three ways, and a conditional reading ``affection`` while
another block writes ``affection.cupa`` fails silently — the engine treats them as
different variables. Declaring a name once means the editor offers it everywhere.

**Only globals are declared.** A local variable is working state inside one story
— a counter for one conversation, a scratch flag for one route. It never leaves
the story that made it, so there is nothing to share and nothing to keep
consistent: the editor lets you type those freely, and the registry stays out of
the way. That split is the point of two scopes rather than four.

Storage is a separate ``variables.json`` rather than a field on ``project.json``:
the pack manifest is what the project dialog rewrites when you rename a pack, and
a registry is authoring state that must not ride along with a careless save.

Entry shape::

    {
      "name": "affection",
      "type": "number",
      "description": "How fond the player is."
    }

``type`` is a hint for the value field (a number variable wants a number, a
boolean wants true/false). The engine does not enforce it, so it never blocks a
save.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

VARIABLES_FILE = "variables.json"

NAME_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_.]{0,63}$")

TYPES = ("number", "boolean", "text")

DEFAULT_TYPE = "number"

# The scope a declared global is stored under. It is the studio's word, not the
# engine's — hikarin.blocks translates GLOBAL to the engine's "WORLD" on the way
# out, so nothing here has to know the engine's spelling.
GLOBAL_SCOPE = "GLOBAL"


class VariableError(Exception):
    """A user-facing problem with the variable registry.

    Its own exception rather than a subclass of ``ProjectError``: ``projects``
    imports this module to hand the registry to the editor, so importing the
    error type back would be a cycle. Both are reported to the browser as a 400
    either way.
    """


def resolve_path(project_path: Path) -> Path:
    """The registry file inside a project folder.

    Takes a path rather than a slug so this module never imports ``projects``.
    """
    return project_path / VARIABLES_FILE


def load_variables(project_path: Path) -> list[dict[str, Any]]:
    """Every declared global variable, in a stable order.

    A project with no registry yet returns an empty list rather than failing: a
    missing file means "nothing declared", not "broken project".
    """
    path = resolve_path(project_path)
    if not path.is_file():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        raise VariableError(f"{VARIABLES_FILE} is not valid JSON: {e}") from e

    entries = data.get("variables") if isinstance(data, dict) else data
    if not isinstance(entries, list):
        raise VariableError(f"{VARIABLES_FILE} must hold a list of variables")

    out: list[dict[str, Any]] = []
    for entry in entries:
        if isinstance(entry, str):
            entry = {"name": entry}
        if not isinstance(entry, dict):
            continue
        name = str(entry.get("name") or "").strip()
        if not name:
            continue
        out.append(
            {
                "name": name,
                "type": entry.get("type") or DEFAULT_TYPE,
                "description": entry.get("description") or "",
            }
        )
    return sorted(out, key=lambda v: v["name"].lower())


def save_variables(project_path: Path, entries: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Replace the registry.

    A whole-list write, the same shape the asset window uses: the manager holds
    the list and hands it back after each edit, so there is no partial state to
    reconcile. Validates everything before writing, so a bad entry cannot leave
    the file half-updated.
    """
    clean: list[dict[str, Any]] = []
    seen: set[str] = set()

    for entry in entries:
        name = str((entry or {}).get("name") or "").strip()
        if not name:
            continue
        if not NAME_RE.match(name):
            raise VariableError(
                f'"{name}" is not a usable variable name. Letters, numbers, _ and . '
                "only, and it cannot start with a digit — it becomes a key in the "
                "compiled script."
            )
        if name in seen:
            raise VariableError(f'"{name}" is registered twice.')

        vtype = str(entry.get("type") or DEFAULT_TYPE).lower()
        if vtype not in TYPES:
            raise VariableError(
                f'"{name}" has type {vtype!r}; expected one of {", ".join(TYPES)}.'
            )

        seen.add(name)
        clean.append(
            {
                "name": name,
                "type": vtype,
                "description": str(entry.get("description") or "").strip(),
            }
        )

    clean.sort(key=lambda v: v["name"].lower())
    resolve_path(project_path).write_text(
        json.dumps({"variables": clean}, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    return clean


def variable_names(project_path: Path) -> list[str]:
    """Just the names, for the editor's global-variable dropdown."""
    return [v["name"] for v in load_variables(project_path)]