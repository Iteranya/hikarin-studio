"""The resource management kit: pure data out of the project.

No runtime code — this deliberately ships only what the designer authors:
the schema itself, a JSON Schema for validating it elsewhere, and a short
integration note. Whatever engine you feed it to is your business; Hikarin
Studio is a content pipeline, not a game engine.
"""

from __future__ import annotations

import io
import json
from pathlib import Path
from typing import Any

from .rm_schema import ResourceManagementSchema
from .resource_management import load_rm, validate_rm


def build_rmkit(project_path: Path) -> bytes:
    """Zip the project's resource management schema as a portable kit.

    Raises ``ValueError`` when the schema has hard validation errors — the
    export dialog turns that into a 400, same as a story with compile errors.
    """
    schema = load_rm(project_path)
    problems = validate_rm(schema, project_path)
    hard = [p for p in problems if "(warning)" not in p]
    if hard:
        raise ValueError(
            "Cannot export: the resource management schema has errors:\n  "
            + "\n  ".join(hard)
        )

    buffer = io.BytesIO()
    import zipfile

    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(
            "resource_management.json",
            json.dumps(schema.model_dump(mode="json"), indent=2, ensure_ascii=False) + "\n",
        )
        zf.writestr(
            "schema.json",
            json.dumps(ResourceManagementSchema.model_json_schema(), indent=2) + "\n",
        )
        zf.writestr(
            "README.md",
            _readme(schema),
        )
    return buffer.getvalue()


def _readme(schema: ResourceManagementSchema) -> str:
    counts = {
        "resources": len(schema.resources),
        "generators": len(schema.generators),
        "converters": len(schema.converters),
        "assignables": len(schema.assignables),
        "nodes": len(schema.nodes),
        "events": len(schema.events),
        "tech nodes": len(schema.tech_nodes),
    }
    summary = ", ".join(f"{n} {k}" for k, n in counts.items())
    return f"""# Resource management kit

Exported from Hikarin Studio. Contains:

- `resource_management.json` — the designed schema ({summary})
- `schema.json` — JSON Schema for validating the above

This is data, not a runtime. Interpret the primitives as:

| Primitive | Meaning |
|---|---|
| `resources` | Named values with caps. `visible_to_vn: true` ones are the same value the VN sees as a variable. |
| `generators` | Produce resources per tick. `levels` is 1-based; `slots` hold assignables. |
| `converters` | Recipes: inputs → outputs over `duration` ticks. `chance_bonus` is an additive roll on completion. |
| `assignables` | Plug into slots. `tags` are read by `assignment_bonuses`. |
| `nodes` | Points on a map/tree with requirements, rewards, event pools, and `connects_to` progression edges. |
| `events` | Random outcomes rolled from a node's `event_pool`. |
| `tech_nodes` | Research unlocks: other ids, and `effects` applied on completion. |
| `requirements` / `effects` | Gates and mutations; `type` picks the vocabulary (`resource`, `tech`, `flag`, `custom`, …). |

`visible_to_vn` resources are shared with the story side: whatever the VN sets
is what your game reads. Keep one writer.
"""
