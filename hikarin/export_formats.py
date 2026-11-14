"""The export registry: what this tool can produce, as data.

Adding an export should mean adding an entry here — not editing the manager's UI,
not touching the editor's dropdown. Both pages render from this list.

Two scopes, because the data has two shapes:

  project  one file built from the whole pack (every story, shared assets)
  story    one file built from one story

An entry declares its own parameters, so a format that needs a version number or
a target name renders its own input without the UI knowing anything about it::

    {
      "id": "pack",
      "label": "Resource pack",
      "extension": ".zip",
      "scope": "project",
      "hint": "What the runtime loads.",
      "params": [
        {"key": "pack_format", "label": "Format", "type": "number", "default": 15}
      ],
    }

``params`` is a list of small descriptors rather than free-form HTML: the manager
draws them, so a new format needs no new UI code. Types are ``number``, ``text``
and ``select`` (with ``options``).

Nothing here knows how to build anything. ``main.py`` maps an id to a builder;
this module is only the menu.
"""

from __future__ import annotations

from typing import Any

# The resource pack format version is the one number a pack export needs. It is
# an export option, not a project property: the same scripts build for several
# runtime versions.
DEFAULT_PACK_FORMAT = 15

EXPORT_FORMATS: list[dict[str, Any]] = [
    {
        "id": "pack",
        "label": "Resource pack",
        "extension": ".zip",
        "scope": "project",
        "hint": "What the runtime loads: pack.mcmeta, one compiled script per story, and the shared images and sounds.",
        "params": [
            {
                "key": "pack_format",
                "label": "Format version",
                "type": "number",
                "default": DEFAULT_PACK_FORMAT,
                "hint": "15 is 1.20.1. Only changes if you target a different runtime version.",
            },
        ],
    },
    {
        "id": "bundle",
        "label": "Project bundle",
        "extension": ".hikarin.zip",
        "scope": "project",
        "hint": "A re-importable backup: project.json and every story's blocks. Use this to move a project between machines, not to ship it.",
        "params": [],
    },
    {
        "id": "json",
        "label": "Compiled script",
        "extension": ".json",
        "scope": "story",
        "hint": "One story's compiled actions, exactly as the pack would contain them.",
        "params": [],
    },
    {
        "id": "txt",
        "label": "Plain-text script",
        "extension": ".txt",
        "scope": "story",
        "hint": "Readable dialogue with labels as section headings. Good for review or translation.",
        "params": [],
    },
    {
        "id": "md",
        "label": "Markdown script",
        "extension": ".md",
        "scope": "story",
        "hint": "The same script as Markdown: labels become ## headings.",
        "params": [],
    },
]


def formats_for(scope: str) -> list[dict[str, Any]]:
    """Every export available at one scope."""
    return [f for f in EXPORT_FORMATS if f["scope"] == scope]


def get_format(fmt_id: str) -> dict[str, Any] | None:
    """One entry by id."""
    return next((f for f in EXPORT_FORMATS if f["id"] == fmt_id), None)


def defaults(fmt_id: str) -> dict[str, Any]:
    """Default parameter values for a format, for the UI to seed its inputs."""
    entry = get_format(fmt_id)
    if not entry:
        return {}
    return {p["key"]: p.get("default") for p in entry.get("params") or []}


def public_formats() -> list[dict[str, Any]]:
    """The registry as the browser sees it."""
    return [
        {
            "id": f["id"],
            "label": f["label"],
            "extension": f["extension"],
            "scope": f["scope"],
            "hint": f["hint"],
            "params": [
                {k: v for k, v in p.items() if k != "options_values"}
                for p in (f.get("params") or [])
            ],
        }
        for f in EXPORT_FORMATS
    ]