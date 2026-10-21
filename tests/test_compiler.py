"""Compiler tests — ported from the JavaScript version that shipped first."""

from __future__ import annotations

import json

import pytest

from hikarin.blocks import parse_literal
from hikarin.compiler import compile_project, suggest

PROJECT = {"character": "cupa", "startLabel": "start", "packName": "Test", "packFormat": 15}


def block(kind: str, **data) -> dict:
    return {"kind": kind, "data": data}


def test_emits_meta_start_then_sequential_ids():
    files = {"main.story": [
        block("label", name="start"),
        block("say", label="Cupa", content="Hello."),
        block("end"),
    ]}
    r = compile_project(PROJECT, files, ["main.story"])
    assert r.errors == []
    assert r.actions[0] == {"type": "meta", "action": "start", "id": 0}
    assert r.actions[1]["type"] == "label"
    assert r.actions[1]["label"] == "start"
    assert r.actions[2]["type"] == "dialogue"
    assert r.actions[3]["type"] == "finish_dialogue"
    assert [a["id"] for a in r.actions] == [0, 1, 2, 3]


def test_start_label_file_compiled_first_regardless_of_tab_order():
    files = {
        "a_idle.story": [block("idle")],
        "z_main.story": [block("label", name="start"), block("end")],
    }
    r = compile_project(PROJECT, files, ["a_idle.story", "z_main.story"])
    assert r.actions[1]["type"] == "label"
    assert r.actions[1]["label"] == "start"


def test_conditional_target_resolved_to_label_id():
    files = {"main.story": [
        block("label", name="start"),
        block("if", scope="MAID", var="seen.night", condition="equal", value="true", _target="night"),
        block("idle"),
        block("end"),
        block("label", name="night"),
        block("say", label="Cupa", content="Night."),
        block("end"),
    ]}
    r = compile_project(PROJECT, files, ["main.story"])
    assert r.errors == []
    cond = next(a for a in r.actions if a["type"] == "conditional")
    night = next(a for a in r.actions if a["type"] == "label" and a["label"] == "night")
    assert cond["end"] == night["id"]
    assert cond["scope"] == "MAID"
    assert cond["value"] is True, "value must be a real boolean"


def test_missing_jump_target_reports_suggestion():
    files = {"main.story": [
        block("label", name="start"),
        block("jump", target="go_nihgt"),
        block("label", name="go_to_night"),
        block("end"),
    ]}
    r = compile_project(PROJECT, files, ["main.story"])
    assert len(r.errors) == 1
    assert "go_nihgt" in r.errors[0]
    assert "go_to_night" in r.errors[0]


def test_duplicate_labels_across_files():
    files = {
        "a.story": [block("label", name="start")],
        "b.story": [block("label", name="start")],
    }
    r = compile_project(PROJECT, files, ["a.story", "b.story"])
    assert any("Duplicate label" in e for e in r.errors)


def test_missing_start_label():
    r = compile_project(PROJECT, {"main.story": [block("say", content="hi")]}, ["main.story"])
    assert any("Start label" in e for e in r.errors)


def test_studio_fields_stripped():
    files = {"main.story": [
        block("label", name="start"),
        block("if", var="x", condition="equal", value="1", _target="start"),
        block("end"),
    ]}
    r = compile_project(PROJECT, files, ["main.story"])
    for action in r.actions:
        assert not any(k.startswith("_") for k in action)


def test_sprite_defaults_match_engine():
    files = {"main.story": [
        block("label", name="start"),
        block("show", sprite="cupa", expression="happy", position="CENTER"),
        block("end"),
    ]}
    r = compile_project(PROJECT, files, ["main.story"])
    s = next(a for a in r.actions if a["type"] == "show_sprite")
    assert s["location"] == "cupa/happy.png"
    assert (s["wRatio"], s["hRatio"]) == (16, 9)
    assert (s["wFrameRatio"], s["hFrameRatio"]) == (4, 8)
    assert (s["column"], s["row"]) == (7, 1)


def test_choice_labels_validated():
    files = {"main.story": [
        block("label", name="start"),
        block("choice", choices=[{"label": "nope", "display": "Try"}]),
        block("end"),
    ]}
    r = compile_project(PROJECT, files, ["main.story"])
    assert any('Choice "Try"' in e for e in r.errors)


def test_unlock_labels_validated():
    files = {"main.story": [
        block("label", name="start"),
        block("unlock", labels=["idle_1"]),
        block("end"),
    ]}
    r = compile_project(PROJECT, files, ["main.story"])
    assert any('Unlock references "idle_1"' in e for e in r.errors)


def test_suggest_handles_transposition():
    assert suggest("go_nihgt", ["go_to_night", "idle", "start"]) == "go_to_night"
    assert suggest("zzzzzzzz", ["start", "idle"]) is None


@pytest.mark.parametrize(
    "raw,expected",
    [("true", True), ("false", False), ("192", 192), ("-4", -4), ("1.5", 1.5), ("Cupa", "Cupa"), ("", "")],
)
def test_parse_literal_types(raw, expected):
    assert parse_literal(raw) == expected


def test_full_spine_compiles_to_valid_json():
    """A realistic character file: night gate, achievement gate, idle pool."""
    files = {
        "main.story": [
            block("label", name="start"),
            block("if", scope="MAID", var="seen.night_01", condition="equal", value="false", _target="night_01"),
            block("if", scope="PLAYER", var="advancement.minecraft:nether", condition="equal", value="true", _target="nether_chat"),
            block("idle"),
            block("end"),
            block("label", name="night_01"),
            block("say", label="Cupa", content="It's late..."),
            block("end"),
            block("label", name="nether_chat"),
            block("say", label="Cupa", content="You went to the Nether?"),
            block("end"),
        ],
        "idle.story": [
            block("label", name="idle_1"),
            block("say", label="Cupa", content="Quiet today."),
            block("transition", action="jump", target="start") if False else block("end"),
        ],
    }
    r = compile_project(PROJECT, files, ["main.story", "idle.story"])
    assert r.errors == [], r.errors

    # Every conditional must point at a real action.
    ids = {a["id"] for a in r.actions}
    for action in r.actions:
        if action["type"] == "conditional":
            assert action["end"] in ids

    # Output must round-trip as JSON.
    json.dumps(r.actions)
