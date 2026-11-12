"""Tests for hikarin.game — the game-project compiler.

These run entirely against a synthetic project created in a tmp_path: no
existing projects are touched, and PROJECTS_ROOT is bypassed through the
``root`` parameter of ``compile_game``.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from hikarin import game


# ── fixture helpers ─────────────────────────────────────────────────────────

def make_game(projects_root: Path, slug: str = "my-game") -> Path:
    """Create a minimal but complete game project."""
    root = projects_root / slug
    (root / "events" / "hestia").mkdir(parents=True)
    (root / "events" / "hestia" / "project.json").write_text(json.dumps({
        "kind": "story",
        "character": "hestia",
        "packName": "Hestia's Event",
        "packFormat": 15,
        "startLabel": "start",
        "files": ["main.story"],
    }), encoding="utf-8")
    (root / "events" / "hestia" / "main.story").write_text(json.dumps([
        {"kind": "label", "data": {"name": "start"}},
        {"kind": "say", "data": {"label": "Hestia", "content": "Hello."}},
        {"kind": "end", "data": {}},
    ]), encoding="utf-8")

    (root / "world").mkdir()
    (root / "world" / "variables.json").write_text(json.dumps({
        "variables": [
            {"name": "hestia_met", "type": "boolean", "default": False, "desc": "Met Hestia"},
            {"name": "west_open", "type": "boolean", "default": False, "desc": "West gate opened"},
        ],
    }), encoding="utf-8")

    (root / "world" / "maps.json").write_text(json.dumps({
        "startMap": "home",
        "maps": {
            "home": {
                "cols": 4,
                "rows": 3,
                "tiles": ["grass"] * 12,
                "palette": {
                    "grass": {"image": "asset/grass.png", "traversable": True},
                    "wall": {"image": "asset/wall.png", "traversable": False},
                },
                "entities": [
                    {"id": "statue", "kind": "static", "col": 1, "row": 1, "event": "hestia"},
                ],
                "spawn": {"col": 0, "row": 0, "facing": "down"},
            },
        },
    }), encoding="utf-8")

    (root / "project.json").write_text(json.dumps({
        "kind": "game",
        "packName": "My Game",
        "description": "test fixture",
        "version": 1,
        "startMap": "home",
    }), encoding="utf-8")
    return root


# ── compile ──────────────────────────────────────────────────────────────────

def test_minimal_game_builds(tmp_path: Path):
    make_game(tmp_path)
    report = game.compile_game("my-game", root=tmp_path)
    assert report["ok"] is True
    assert report["errors"] == []
    assert report["events"] == ["hestia"]
    assert (tmp_path / "my-game" / "build" / "game.json").is_file()
    assert (tmp_path / "my-game" / "build" / "events" / "hestia.json").is_file()


def test_game_json_contents(tmp_path: Path):
    make_game(tmp_path)
    game.compile_game("my-game", root=tmp_path)
    payload = json.loads((tmp_path / "my-game" / "build" / "game.json").read_text(encoding="utf-8"))
    assert payload["meta"]["packName"] == "My Game"
    assert payload["meta"]["startMap"] == "home"
    assert payload["maps"]["startMap"] == "home"
    assert payload["maps"]["maps"]["home"]["spawn"] == {"col": 0, "row": 0, "facing": "down"}
    assert payload["meta"]["variables"][0]["name"] == "hestia_met"


def test_event_output_is_valid_story_json(tmp_path: Path):
    make_game(tmp_path)
    game.compile_game("my-game", root=tmp_path)
    actions = json.loads((tmp_path / "my-game" / "build" / "events" / "hestia.json").read_text(encoding="utf-8"))
    # Same acceptance FORMAT.md applies to a story: sequential ids from 0.
    assert [a["id"] for a in actions] == list(range(len(actions)))


def test_unknown_entity_event_is_an_error(tmp_path: Path):
    root = make_game(tmp_path)
    raw = json.loads((root / "world" / "maps.json").read_text(encoding="utf-8"))
    raw["maps"]["home"]["entities"][0]["event"] = "does_not_exist"
    (root / "world" / "maps.json").write_text(json.dumps(raw), encoding="utf-8")
    report = game.compile_game("my-game", root=tmp_path)
    assert report["ok"] is False
    assert any("does_not_exist" in e for e in report["errors"])


def test_map_tiles_must_fit_grid(tmp_path: Path):
    root = make_game(tmp_path)
    raw = json.loads((root / "world" / "maps.json").read_text(encoding="utf-8"))
    raw["maps"]["home"]["tiles"] = ["grass"] * 5   # too short
    (root / "world" / "maps.json").write_text(json.dumps(raw), encoding="utf-8")
    report = game.compile_game("my-game", root=tmp_path)
    assert report["ok"] is False
    assert any("expected" in e for e in report["errors"])


def test_unknown_tile_reference_is_an_error(tmp_path: Path):
    root = make_game(tmp_path)
    raw = json.loads((root / "world" / "maps.json").read_text(encoding="utf-8"))
    raw["maps"]["home"]["tiles"][0] = "nope"
    (root / "world" / "maps.json").write_text(json.dumps(raw), encoding="utf-8")
    report = game.compile_game("my-game", root=tmp_path)
    assert report["ok"] is False
    assert any("unknown tile" in e for e in report["errors"])


def test_duplicate_world_variable_is_an_error(tmp_path: Path):
    root = make_game(tmp_path)
    (root / "world" / "variables.json").write_text(json.dumps({
        "variables": [
            {"name": "dup", "type": "boolean", "default": False},
            {"name": "dup", "type": "boolean", "default": True},
        ],
    }), encoding="utf-8")
    report = game.compile_game("my-game", root=tmp_path)
    assert report["ok"] is False
    assert any("Duplicate world variable" in e for e in report["errors"])


def test_non_game_project_rejected(tmp_path: Path):
    (tmp_path / "story").mkdir()
    (tmp_path / "story" / "project.json").write_text('{"packName": "s"}', encoding="utf-8")
    with pytest.raises(game.project_store.ProjectError):
        game.compile_game("story", root=tmp_path)


def test_hikarin_map_block_compiles_flat(tmp_path: Path):
    """A map switch is just a hikarin action; the compiler passes it through."""
    from hikarin.blocks import BUILDERS
    action = BUILDERS["mapSwitch"]({"map": "wastes", "x": 2, "y": 1, "facing": "left"})
    assert action == {"type": "map", "action": "switch", "map": "wastes", "x": 2, "y": 1, "facing": "left"}


def test_hikarin_map_block_roundtrip(tmp_path: Path):
    from hikarin.blocks import block_from_action
    block = block_from_action({"type": "map", "action": "switch", "map": "void", "x": 0, "y": 0})
    assert block is not None
    assert block["kind"] == "mapSwitch"
    assert block["data"]["map"] == "void"
    assert block["data"]["x"] == 0
    assert block["data"]["y"] == 0


def test_story_flow_still_exists(tmp_path: Path):
    """A sanity check that the retrofit does not touch story projects."""
    (tmp_path / "velvet").mkdir()
    (tmp_path / "velvet" / "project.json").write_text(json.dumps({
        "character": "velvet", "packName": "Velvet", "packFormat": 15,
        "startLabel": "start", "files": ["main.story"],
    }), encoding="utf-8")
    (tmp_path / "velvet" / "main.story").write_text(json.dumps([
        {"kind": "label", "data": {"name": "start"}},
        {"kind": "end", "data": {}},
    ]), encoding="utf-8")
    from hikarin.compiler import compile_project
    import json as _json
    meta = _json.loads((tmp_path / "velvet" / "project.json").read_text(encoding="utf-8"))
    files = {"main.story": _json.loads((tmp_path / "velvet" / "main.story").read_text(encoding="utf-8"))}
    result = compile_project(meta, files)
    assert result.ok
