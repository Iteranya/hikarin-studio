"""Shared variable registry tests — real files in a temp directory."""

from __future__ import annotations

import pytest

from hikarin import projects as store
from hikarin import variables as variables


@pytest.fixture
def temp_root(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "PROJECTS_ROOT", tmp_path)
    return tmp_path


@pytest.fixture
def project(temp_root):
    store.create_project("touhou")
    return "touhou"


def _write(project, entries):
    return variables.save_variables(store.project_dir(project), entries)


def _read(project):
    return variables.load_variables(store.project_dir(project))


# ── storage ─────────────────────────────────────────────────────────────────


def test_no_registry_is_empty_not_an_error(project):
    assert _read(project) == []


def test_roundtrip(project):
    saved = _write(project, [
        {"name": "affection", "scope": "MAID", "type": "number", "description": "Fondness."},
        {"name": "seen_night", "scope": "WORLD", "type": "boolean", "description": ""},
    ])
    assert [v["name"] for v in saved] == ["affection", "seen_night"]
    assert [v["name"] for v in _read(project)] == ["affection", "seen_night"]


def test_written_file_is_a_json_object_with_a_variables_key(project, temp_root):
    _write(project, [{"name": "health"}])
    raw = (temp_root / "touhou" / "variables.json").read_text(encoding="utf-8")
    assert '"variables"' in raw
    assert '"health"' in raw


def test_entries_are_sorted_by_name(project):
    saved = _write(project, [{"name": n} for n in ("zeta", "alpha", "mid")])
    assert [v["name"] for v in saved] == ["alpha", "mid", "zeta"]


def test_defaults_are_filled_in(project):
    saved = _write(project, [{"name": "bare"}])
    assert saved[0]["type"] == "number"
    assert saved[0]["description"] == ""


def test_a_plain_string_entry_is_accepted(project):
    """Hand-editing variables.json should not be a trap."""
    (store.project_dir("touhou") / "variables.json").write_text(
        '{"variables": ["affection"]}', encoding="utf-8"
    )
    assert [v["name"] for v in _read(project)] == ["affection"]


def test_blank_names_are_dropped(project):
    saved = _write(project, [{"name": "  "}, {"name": ""}, {"name": "real"}])
    assert [v["name"] for v in saved] == ["real"]


# ── validation ──────────────────────────────────────────────────────────────


@pytest.mark.parametrize("bad", ["2legit", "has space", "dash-es", "a/b"])
def test_rejects_bad_names(project, bad):
    with pytest.raises(variables.VariableError):
        _write(project, [{"name": bad}])


def test_a_blank_name_is_dropped_not_rejected(project):
    """Clearing a row's name is how the manager deletes it.

    A blank entry is an empty row on its way out, so it is dropped silently;
    rejecting it would make the delete button unusable.
    """
    saved = _write(project, [{"name": "kept"}, {"name": ""}])
    assert [v["name"] for v in saved] == ["kept"]


@pytest.mark.parametrize("good", ["affection", "_private", "seen.night_01", "A1"])
def test_accepts_good_names(project, good):
    saved = _write(project, [{"name": good}])
    assert saved[0]["name"] == good


def test_rejects_duplicate_names(project):
    with pytest.raises(variables.VariableError):
        _write(project, [{"name": "affection"}, {"name": "affection"}])


def test_a_scope_field_is_ignored(project):
    """The registry is globals-only, so a legacy scope key is not an error.

    Older registries recorded one. Reading it back must not break a project that
    predates the two-scope model — the field is simply not part of the shape any
    more.
    """
    saved = _write(project, [{"name": "affection", "scope": "MAID"}])
    assert "scope" not in saved[0]


def test_rejects_unknown_type(project):
    with pytest.raises(variables.VariableError):
        _write(project, [{"name": "affection", "type": "float"}])


def test_only_name_type_and_description_are_kept(project):
    saved = _write(project, [
        {"name": "affection", "type": "boolean", "description": "Fond.", "extra": "dropped"}
    ])
    assert saved[0] == {"name": "affection", "type": "boolean", "description": "Fond."}


def test_a_bad_entry_leaves_the_file_untouched(project):
    """Validate before writing: no half-updated registry."""
    _write(project, [{"name": "good"}])
    with pytest.raises(variables.VariableError):
        _write(project, [{"name": "new"}, {"name": "2bad"}])
    assert [v["name"] for v in _read(project)] == ["good"]


# ── what the editor sees ────────────────────────────────────────────────────


def test_story_payload_carries_the_registry(project):
    """The editor must not need a second request per story open."""
    store.create_story("touhou", "cupa")
    _write(project, [{"name": "affection"}, {"name": "seen_night"}])

    story = store.load_story("touhou", "cupa")
    assert [v["name"] for v in story["variables"]] == ["affection", "seen_night"]


def test_registry_is_per_project(temp_root):
    """One pack's variables must not leak into another."""
    store.create_project("a")
    store.create_project("b")
    _write("a", [{"name": "affection"}])
    _write("b", [{"name": "health"}])

    assert [v["name"] for v in _read("a")] == ["affection"]
    assert [v["name"] for v in _read("b")] == ["health"]


def test_deleting_a_variable_does_not_touch_stories(project):
    """The registry is a convenience for the editor, not state the engine reads."""
    store.create_story("touhou", "cupa")
    _write(project, [{"name": "affection"}])

    blocks = [{"kind": "setVar", "data": {"var": "affection", "value": 1}}]
    store.save_story("touhou", "cupa", {"character": "cupa"}, {"main.story": blocks})

    _write(project, [])  # remove the declaration

    after = store.load_story("touhou", "cupa")
    assert after["files"]["main.story"][0]["data"]["var"] == "affection"
    assert after["variables"] == []


# ── the two scopes ──────────────────────────────────────────────────────────


def test_the_editor_offers_exactly_two_scopes():
    """Local and global. MAID and SCENE collapse into local.

    An author should not have to know which NBT compound a name lands in to
    decide whether a counter is per-story or per-conversation — both are "this
    story's business", and only the global ones need declaring.

    Read as text rather than parsed: the block carries a trailing comma, so there
    is no JSON document here to decode.
    """
    import re
    from pathlib import Path

    source = Path(__file__).resolve().parent.parent / "main.py"
    text = source.read_text(encoding="utf-8")
    start = text.index('"scopes": [')
    end = text.index("]", start)

    values = re.findall(r'"value":\s*("(?:[^"]*)"|[^\n,}]+)', text[start:end])
    assert [v.strip().strip('"') for v in values] == ["LOCAL", "GLOBAL"]

    labels = re.findall(r'"label":\s*"([^"]+)"', text[start:end])
    assert len(labels) == 2
    assert any("Local" in l for l in labels)
    assert any("Global" in l for l in labels)


# ── the scope translation seam ──────────────────────────────────────────────
#
# The studio says LOCAL/GLOBAL. The engine reads WORLD and bare names. That
# translation lives in one table; these tests are the guard rail on it, because
# getting it wrong does not raise — it just writes a scope the engine ignores and
# the flag quietly goes local.


def test_engine_scope_translation():
    from hikarin.blocks import engine_scope

    assert engine_scope("GLOBAL") == "WORLD"
    assert engine_scope("LOCAL") is None
    assert engine_scope("") is None
    assert engine_scope(None) is None
    # Legacy values an older project may still carry.
    assert engine_scope("MAID") is None
    assert engine_scope("SCENE") is None
    # Read-only, injected by the engine.
    assert engine_scope("PLAYER") == "PLAYER"
    # Case does not matter.
    assert engine_scope("global") == "WORLD"


def test_authoring_scope_translation():
    from hikarin.blocks import authoring_scope

    assert authoring_scope("WORLD") == "GLOBAL"
    assert authoring_scope(None) == "LOCAL"
    assert authoring_scope("") == "LOCAL"
    assert authoring_scope("MAID") == "LOCAL"
    assert authoring_scope("SCENE") == "LOCAL"


def test_a_local_variable_never_emits_a_scope_key(project):
    """A bare name is how the engine says local. Emitting scope="" would not be."""
    store.create_story("touhou", "cupa")
    blocks = [
        {"kind": "label", "data": {"name": "start"}},
        {"kind": "if", "data": {
            "var": "tick", "condition": "greater_than", "value": 3,
            "scope": "LOCAL", "_target": "start",
        }},
        {"kind": "end", "data": {}},
    ]
    store.save_story("touhou", "cupa", {"character": "cupa"}, {"main.story": blocks})

    result = store.compile_slug("touhou", "cupa")
    cond = next(a for a in result.actions if a["type"] == "conditional")
    assert "scope" not in cond, "local is a bare name, not an empty scope"
    assert cond["var"] == "tick"


def test_global_scope_is_the_world_prefix(project):
    """A declared global compiles with @world. so it really is shared."""
    assert variables.GLOBAL_SCOPE == "GLOBAL"
    from hikarin.blocks import engine_scope
    assert engine_scope("GLOBAL") == "WORLD"


def test_a_local_variable_needs_no_declaration(project):
    """Locals are typed straight into the block and compile as bare names."""
    store.create_story("touhou", "cupa")
    blocks = [
        {"kind": "label", "data": {"name": "start"}},
        {"kind": "setVar", "data": {"var": "tick", "value": 1, "operation": "increment_var"}},
        {"kind": "end", "data": {}},
    ]
    store.save_story("touhou", "cupa", {"character": "cupa"}, {"main.story": blocks})

    result = store.compile_slug("touhou", "cupa")
    assert result.ok
    written = next(a for a in result.actions if a["type"] == "modify_variable")
    assert written["var"] == "tick"
    assert "scope" not in written, "a local is bare — no prefix, no scope key"


def test_a_global_variable_compiles_with_the_engine_scope(project):
    """The studio says GLOBAL; the JSON says WORLD, because that is what the
    engine reads. The translation is the whole point of the seam."""
    store.create_story("touhou", "cupa")
    blocks = [
        {"kind": "label", "data": {"name": "start"}},
        {"kind": "setVar", "data": {
            "var": "story_complete", "value": True, "operation": "set", "scope": "GLOBAL",
        }},
        {"kind": "end", "data": {}},
    ]
    store.save_story("touhou", "cupa", {"character": "cupa"}, {"main.story": blocks})

    result = store.compile_slug("touhou", "cupa")
    written = next(a for a in result.actions if a["type"] == "modify_variable")
    assert written["var"] == "story_complete"
    assert written["scope"] == "WORLD"


def test_a_story_still_compiles_with_an_undeclared_variable(project):
    """Declaring is a convenience. The compiler never required it."""
    store.create_story("touhou", "cupa")
    blocks = [
        {"kind": "label", "data": {"name": "start"}},
        {"kind": "setVar", "data": {"var": "made_up", "value": 1, "operation": "set"}},
        {"kind": "end", "data": {}},
    ]
    store.save_story("touhou", "cupa", {"character": "cupa"}, {"main.story": blocks})

    result = store.compile_slug("touhou", "cupa")
    assert result.ok, result.errors
    assert any(a.get("var") == "made_up" for a in result.actions)