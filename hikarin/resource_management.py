"""Resource Management storage: a folder on disk holds a schema, like stories.

``resource_management.json`` sits next to ``variables.json`` in the project
folder. Same contract as the rest of the studio: no database, atomic whole-file
writes, validation before the file is touched.

The one seam between the RM schema and the VN registry is ``sync_vn_variables``.
A Resource flagged ``visible_to_vn`` is the *same variable* the story editor
reads from Hikarin's variables tab, exported under its ``vn_name`` in
``GLOBAL`` (or ``LOCAL``) scope. The writer does not see two systems — they see
a registry that happens to be maintained from the RM editor.

Sync rules:

* RM-derived entries carry ``"source": "rm"``. Hand-registered variables are
  never touched.
* Syncing replaces the RM-derived set wholesale: a Resource deleted or hidden
  in the RM editor disappears from the registry on the next save.
* A VN-visible Resource whose ``vn_name`` collides with a hand-registered
  variable is an error, not a silent overwrite — the human wrote that name on
  purpose, and the failure mode of shadowing it silently is exactly the
  affection/affection.cupa trap the registry exists to prevent.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from . import variables as variable_store
from .rm_schema import (
    ResourceManagementSchema,
    validate_schema,
)

RM_FILE = "resource_management.json"


class ResourceManagementError(Exception):
    """A user-facing problem with the RM schema. Reported as a 400."""


def resolve_path(project_path: Path) -> Path:
    return project_path / RM_FILE


def empty_schema() -> ResourceManagementSchema:
    return ResourceManagementSchema()


def load_rm(project_path: Path) -> ResourceManagementSchema:
    """The project's RM schema. A missing file is an empty schema."""
    path = resolve_path(project_path)
    if not path.is_file():
        return empty_schema()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        raise ResourceManagementError(f"{RM_FILE} is not valid JSON: {e}") from e
    if not isinstance(data, dict):
        raise ResourceManagementError(f"{RM_FILE} must hold a JSON object")
    try:
        return ResourceManagementSchema.model_validate(data)
    except ValueError as e:
        raise ResourceManagementError(f"{RM_FILE} is not a valid schema: {e}") from e


def _manual_variable_names(project_path: Path) -> set[str]:
    """Hand-registered VN variable names (i.e. not written by RM syncs)."""
    path = variable_store.resolve_path(project_path)
    if not path.is_file():
        return set()
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return set()  # sync_vn_variables refuses broken registries; don't block validation
    entries = raw.get("variables") if isinstance(raw, dict) else raw
    if not isinstance(entries, list):
        return set()
    return {
        str(entry.get("name"))
        for entry in entries
        if isinstance(entry, dict) and entry.get("source") != "rm" and entry.get("name")
    }


def validate_rm(schema: ResourceManagementSchema, project_path: Path | None = None) -> list[str]:
    """Full coherence check: internal refs + VN registry collisions."""
    problems = validate_schema(schema)

    if project_path is not None:
        manual_names = _manual_variable_names(project_path)
        for res in schema.resources:
            if not res.visible_to_vn:
                continue
            name = res.vn_name or res.id.replace("-", "_")
            if name in manual_names:
                problems.append(
                    f"Resource {res.id!r} exports to VN variable {name!r}, which is "
                    f"already hand-registered in Variables. Rename one of them."
                )
    return problems


def save_rm(
    project_path: Path,
    schema: ResourceManagementSchema,
) -> tuple[ResourceManagementSchema, list[str]]:
    """Validate, write, then sync VN variables.

    Hard errors (any problem not tagged ``(warning)``) refuse the write; the
    file on disk is left exactly as it was. Warnings are returned for the UI to
    show, and the save proceeds.
    """
    problems = validate_rm(schema, project_path)
    errors = [p for p in problems if "(warning)" not in p]
    if errors:
        raise ResourceManagementError("\n".join(errors))

    resolve_path(project_path).write_text(
        json.dumps(schema.model_dump(mode="json"), indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    sync_vn_variables(project_path, schema)
    return schema, [p for p in problems if "(warning)" in p]


def _rm_variable_entries(schema: ResourceManagementSchema) -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = []
    type_map = {"integer": "number", "decimal": "number", "boolean": "boolean"}
    for res in schema.resources:
        if not res.visible_to_vn:
            continue
        entries.append(
            {
                "name": res.vn_name or res.id.replace("-", "_"),
                "type": type_map.get(res.resource_type, "number"),
                "description": res.description or f"Resource {res.id} (resource management)",
                "source": "rm",
            }
        )
    return entries


def sync_vn_variables(project_path: Path, schema: ResourceManagementSchema) -> list[dict[str, Any]]:
    """Make ``variables.json`` reflect the VN-visible resources.

    Hand-registered entries are preserved verbatim; the RM-derived set is
    replaced wholesale. Runs on every save, so the registry never drifts from
    the schema. Returns the full merged list.
    """
    path = variable_store.resolve_path(project_path)
    manual: list[dict[str, Any]] = []
    if path.is_file():
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as e:
            raise ResourceManagementError(
                f"variables.json is not valid JSON: {e}. Fix it before saving "
                "the RM schema — the sync will not touch a broken registry."
            ) from e
        entries = raw.get("variables") if isinstance(raw, dict) else raw
        if isinstance(entries, list):
            for entry in entries:
                if isinstance(entry, dict) and entry.get("source") != "rm":
                    manual.append(entry)

    merged = manual + _rm_variable_entries(schema)
    # Names are unique across the two sets by validation; sort for a stable file.
    merged.sort(key=lambda v: str(v.get("name", "")).lower())
    path.write_text(
        json.dumps({"variables": merged}, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    return merged


def schema_summary(schema: ResourceManagementSchema) -> dict[str, int]:
    return {
        "resources": len(schema.resources),
        "generators": len(schema.generators),
        "converters": len(schema.converters),
        "assignables": len(schema.assignables),
        "nodes": len(schema.nodes),
        "events": len(schema.events),
        "techNodes": len(schema.tech_nodes),
        "vnVariables": len([r for r in schema.resources if r.visible_to_vn]),
    }
