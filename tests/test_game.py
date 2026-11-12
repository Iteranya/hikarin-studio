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

    (root / "world" / "map.orch").write_text(json.dumps({
        "kind": "orch-graph",
        "start": "n_meta",
        "nodes": [
            {"id": "n_meta", "verb": "meta", "fields": {"action": "start"}, "at": [0, 0]},
            {"id": "n_label", "verb": "label", "fields": {"label": "start"}, "at": [0, 100]},
            {"id": "n_run", "verb": "run_event", "fields": {"event": "hestia"}, "at": [0, 200]},
            {"id": "n_end", "verb": "ending", "fields": {}, "at": [0, 300]},
        ],
        "wires": [
            {"from": ["n_meta", "out"], "to": ["n_label", "in"]},
            {"from": ["n_label", "out"], "to": ["n_run", "in"]},
            {"from": ["n_run", "out"], "to": ["n_end", "in"]},
        ],
    }), encoding="utf-8")

    (root / "project.json").write_text(json.dumps({
        "kind": "game",
        "packName": "My Game",
        "description": "test fixture",
        "version": 1,
        "start": "start",
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
    assert payload["meta"]["variables"][0]["name"] == "hestia_met"
    assert payload["script"][0]["type"] == "meta"
    types = [a["type"] for a in payload["script"]]
    assert types == ["meta", "label", "run_event", "ending"]
    ids = [a["id"] for a in payload["script"]]
    assert ids == list(range(len(ids)))


def test_event_output_is_valid_story_json(tmp_path: Path):
    make_game(tmp_path)
    game.compile_game("my-game", root=tmp_path)
    actions = json.loads((tmp_path / "my-game" / "build" / "events" / "hestia.json").read_text(encoding="utf-8"))
    # Same acceptance FORMAT.md applies to a story: sequential ids from 0.
    assert [a["id"] for a in actions] == list(range(len(actions)))


def test_unknown_event_is_an_error(tmp_path: Path):
    root = make_game(tmp_path)
    orch = json.loads((root / "world" / "map.orch").read_text(encoding="utf-8"))
    orch["nodes"][2]["fields"] = {"event": "does_not_exist"}
    (root / "world" / "map.orch").write_text(json.dumps(orch), encoding="utf-8")
    report = game.compile_game("my-game", root=tmp_path)
    assert report["ok"] is False
    assert any("does_not_exist" in e for e in report["errors"])


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


def test_conditional_false_target_resolves_to_id(tmp_path: Path):
    root = make_game(tmp_path)
    (root / "world" / "variables.json").write_text(json.dumps({
        "variables": [{"name": "hestia_met", "type": "boolean", "default": False}],
    }), encoding="utf-8")
    (root / "world" / "map.orch").write_text(json.dumps({
        "kind": "orch-graph",
        "nodes": [
            {"id": "a", "verb": "meta", "fields": {"action": "start"}, "at": [0, 0]},
            {"id": "b", "verb": "conditional", "fields": {"condition": "equal", "var": "@world.hestia_met", "value": True}, "at": [0, 100]},
            {"id": "c", "verb": "set_world", "fields": {"var": "@world.hestia_met", "value": True}, "at": [-200, 200]},
            {"id": "d", "verb": "run_event", "fields": {"event": "hestia"}, "at": [0, 250]},
        ],
        "wires": [
            {"from": ["a", "out"], "to": ["b", "in"]},
            {"from": ["b", "true"], "to": ["d", "in"]},
            {"from": ["b", "false"], "to": ["c", "in"]},
        ],
    }), encoding="utf-8")
    report = game.compile_game("my-game", root=tmp_path)
    assert report["ok"] is True
    cond = next(a for a in json.loads((root / "build" / "game.json").read_text())["script"] if a["type"] == "conditional")
    sw = next(a for a in json.loads((root / "build" / "game.json").read_text())["script"] if a["type"] == "set_world")
    assert cond["end"] == sw["id"]


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
