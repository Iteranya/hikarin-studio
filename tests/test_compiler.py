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


def test_sprite_path_matches_sdk_layout():
    """The SDK's characters.py is explicit about the three levels:
    textures/<character id>/<outfit>/<emotion>.png
    """
    files = {"main.story": [
        block("label", name="start"),
        block("show", sprite="cupa", outfit="default", expression="happy", position="CENTER"),
        block("end"),
    ]}
    r = compile_project(PROJECT, files, ["main.story"])
    assert r.errors == [], r.errors
    s = next(a for a in r.actions if a["type"] == "show_sprite")
    assert s["location"] == "characters/cupa/default/happy.png"
    assert (s["wRatio"], s["hRatio"]) == (16, 9)
    assert (s["wFrameRatio"], s["hFrameRatio"]) == (4, 8)
    assert (s["column"], s["row"]) == (7, 1)


def test_sprite_outfit_defaults_when_omitted():
    files = {"main.story": [
        block("label", name="start"),
        block("show", sprite="cupa", expression="happy"),
        block("end"),
    ]}
    r = compile_project(PROJECT, files, ["main.story"])
    s = next(a for a in r.actions if a["type"] == "show_sprite")
    assert s["location"] == "characters/cupa/default/happy.png"


def test_dyn_location_written_for_outfit_variable():
    files = {"main.story": [
        block("label", name="start"),
        block("show", sprite="cupa", outfit="default", expression="happy", outfit_var="cupa_outfit"),
        block("end"),
    ]}
    r = compile_project(PROJECT, files, ["main.story"])
    s = next(a for a in r.actions if a["type"] == "show_sprite")
    assert s["location"] == "characters/cupa/default/happy.png"
    assert s["dyn_location"] == "characters/cupa/<cupa_outfit>/happy.png"


@pytest.mark.parametrize("bad_field,bad_value", [
    ("sprite", "Cupa"),
    ("sprite", "cu pa"),
    ("expression", "Happy"),
    ("outfit", "Summer Clothes"),
])
def test_sprite_names_reject_uppercase_and_spaces(bad_field, bad_value):
    """The SDK rejects these because they become lowercase texture paths."""
    data = {"sprite": "cupa", "outfit": "default", "expression": "happy"}
    data[bad_field] = bad_value
    files = {"main.story": [
        block("label", name="start"),
        block("show", **data),
        block("end"),
    ]}
    r = compile_project(PROJECT, files, ["main.story"])
    assert any("lowercase" in e for e in r.errors), r.errors


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


# ── day / night: condition types, not variables ─────────────────────────────
#
# The original SDK writes:
#   {"type": "conditional", "condition": "night", "var": "Nyaaa~", ...}
# `var` is a placeholder it never reads. These tests pin that shape so the
# compiler cannot drift into treating day/night as a variable comparison.


def test_night_condition_writes_placeholder_var():
    files = {"main.story": [
        block("label", name="start"),
        block("if", condition="night", _target="done"),
        block("say", label="Cupa", content="The moon is out."),
        block("label", name="done"),
    ]}
    r = compile_project(PROJECT, files, ["main.story"])
    assert r.errors == [], r.errors
    cond = next(a for a in r.actions if a["type"] == "conditional")
    assert cond["condition"] == "night"
    assert cond["var"] == "Nyaaa~", "SDK writes a literal placeholder for day/night"
    assert "value" not in cond, "day/night takes no value"


def test_day_condition_takes_no_variable_or_scope():
    files = {"main.story": [
        block("label", name="start"),
        block("if", condition="day", scope="MAID", var="ignored", value="also ignored", _target="done"),
        block("label", name="done"),
    ]}
    r = compile_project(PROJECT, files, ["main.story"])
    cond = next(a for a in r.actions if a["type"] == "conditional")
    assert cond["condition"] == "day"
    assert cond["var"] == "Nyaaa~"
    assert "scope" not in cond
    assert "value" not in cond


def test_day_night_are_not_harvested_as_suggested_vars():
    """A day/night gate must not appear as settable state in the preview."""
    import main as app_module

    files = {"main.story": [
        block("label", name="start"),
        block("if", condition="night", _target="done"),
        block("if", var="affection", condition="less_than", value="10", _target="done"),
        block("label", name="done"),
    ]}
    vars_ = app_module._suggested_variables(files)
    names = [v["name"] for v in vars_]
    assert names == ["affection"], names


# ── image boxes: show_custom with a folder instead of a character ───────────
#
# The SDK branches on the argument type:
#
#   show_custom(cupa, "happy", 16,9,4,8,7,1)      -> characters/<id>/<outfit>/
#   show_custom("asset","old-dsl",16,9,10,6,6,1)  -> asset/old-dsl.png
#
# Both carry the same six grid numbers. Only the path and the slot name differ.


def test_image_box_matches_sdk_output():
    files = {"main.story": [
        block("label", name="start"),
        block("show", mode="box", folder="asset", image="old-dsl",
              layout={"preset": "CUSTOM", "wRatio": 16, "hRatio": 9,
                      "wFrameRatio": 10, "hFrameRatio": 6, "column": 6, "row": 1}),
        block("end"),
    ]}
    r = compile_project(PROJECT, files, ["main.story"])
    assert r.errors == [], r.errors

    s = next(a for a in r.actions if a["type"] == "show_sprite")
    assert s["location"] == "asset/old-dsl.png"
    assert s["sprite"] == "old-dsl", "a box's slot name is the image name"
    assert s["position"] == "CUSTOM"
    assert (s["wRatio"], s["hRatio"]) == (16, 9)
    assert (s["wFrameRatio"], s["hFrameRatio"]) == (10, 6)
    assert (s["column"], s["row"]) == (6, 1)
    assert "dyn_location" not in s, "a box has no outfit to swap"


def test_character_show_still_writes_dyn_location():
    files = {"main.story": [
        block("label", name="start"),
        block("show", mode="character", sprite="andr", outfit="default",
              expression="normal", outfit_var="andr_outfit"),
        block("end"),
    ]}
    r = compile_project(PROJECT, files, ["main.story"])
    s = next(a for a in r.actions if a["type"] == "show_sprite")
    assert s["location"] == "characters/andr/default/normal.png"
    assert s["dyn_location"] == "characters/andr/<andr_outfit>/normal.png"
    assert s["sprite"] == "andr"


def test_box_remove_targets_the_slot_name():
    """vn.remove("asset","old-dsl") emits sprite: "old-dsl"."""
    files = {"main.story": [
        block("label", name="start"),
        block("hide", sprite="old-dsl"),
        block("end"),
    ]}
    r = compile_project(PROJECT, files, ["main.story"])
    h = next(a for a in r.actions if a["type"] == "remove_sprite")
    assert h["sprite"] == "old-dsl"
    assert h["action"] == "remove"


# ── tabs are just files; one global label namespace ─────────────────────────


def test_jump_reaches_a_label_in_another_file():
    """A tab is a different .story, not a scope. Any label is fair game."""
    files = {
        "main.story": [
            block("label", name="start"),
            block("jump", target="night_beat"),
            block("end"),
            block("label", name="morning"),
            block("end"),
        ],
        "night.story": [
            block("label", name="night_beat"),
            block("jump", target="morning"),   # back into main.story
            block("end"),
        ],
    }
    r = compile_project(PROJECT, files, ["main.story", "night.story"])
    assert r.errors == [], r.errors
    assert r.labels["night_beat"] == "night.story"
    assert r.labels["morning"] == "main.story"


def test_jump_to_missing_label_is_still_an_error_across_files():
    files = {
        "main.story": [block("label", name="start"), block("jump", target="nowhere"), block("end")],
        "night.story": [block("label", name="night_beat"), block("end")],
    }
    r = compile_project(PROJECT, files, ["main.story", "night.story"])
    assert any("nowhere" in e for e in r.errors)


def test_jump_never_emits_a_file_field():
    """A file field would imply a boundary that does not exist, and it used to
    switch off label validation."""
    files = {"main.story": [
        block("label", name="start"),
        block("jump", target="start", file="main.story"),
        block("end"),
    ]}
    r = compile_project(PROJECT, files, ["main.story"])
    jump = next(a for a in r.actions if a["type"] == "transition")
    assert "file" not in jump
    assert jump["label"] == "start"


def test_next_checkpoint_crosses_files_too():
    files = {
        "main.story": [block("label", name="start"), block("end")],
        "night.story": [block("next", target="start"), block("end")],
    }
    r = compile_project(PROJECT, files, ["main.story", "night.story"])
    nxt = next(a for a in r.actions if a["type"] == "next")
    assert nxt["label"] == "start"
