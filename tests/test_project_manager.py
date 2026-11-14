"""Project manager + export format tests."""

from __future__ import annotations

import json

import pytest

from hikarin import projects as store
from hikarin.compiler import compile_project
from hikarin.exporter import (
    build_json,
    build_markdown,
    build_project_bundle,
    build_text,
    export_filename_for,
)


@pytest.fixture
def temp_root(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "PROJECTS_ROOT", tmp_path)
    return tmp_path


@pytest.fixture
def pack(temp_root):
    store.create_project("touhou", {"packName": "Touhou Pack"})
    store.create_story("touhou", "cupa", {"character": "cupa"})
    return "touhou"


# ── project-level management ────────────────────────────────────────────────


def test_duplicate_project_copies_every_story(pack, temp_root):
    store.create_story("touhou", "reimu", {"character": "reimu"})

    dup = store.duplicate_project("touhou", "touhou-copy")
    assert dup["slug"] == "touhou-copy"
    assert (temp_root / "touhou-copy" / "project.json").is_file()
    assert (temp_root / "touhou-copy" / "stories" / "cupa" / "main.story").is_file()
    assert (temp_root / "touhou-copy" / "stories" / "reimu" / "main.story").is_file()
    assert [s["slug"] for s in dup["stories"]] == ["cupa", "reimu"]

    with pytest.raises(store.ProjectError):
        store.duplicate_project("touhou", "touhou-copy")


def test_rename_project_moves_folder(pack, temp_root):
    r = store.rename_project("touhou", "moriya")
    assert r["slug"] == "moriya"
    assert not (temp_root / "touhou").exists()
    assert (temp_root / "moriya" / "project.json").is_file()
    assert (temp_root / "moriya" / "stories" / "cupa" / "main.story").is_file()


def test_delete_project_removes_every_story(pack, temp_root):
    store.create_story("touhou", "reimu")
    store.delete_project("touhou")
    assert not (temp_root / "touhou").exists()


# ── story-level management ──────────────────────────────────────────────────


def test_duplicate_story(pack, temp_root):
    dup = store.duplicate_story("touhou", "cupa", "cupa2")
    assert dup["slug"] == "cupa2"
    assert dup["meta"]["character"] == "cupa2", "a duplicate is its own story"
    assert (temp_root / "touhou" / "stories" / "cupa2" / "main.story").is_file()


def test_rename_story(pack, temp_root):
    renamed = store.rename_story("touhou", "cupa", "cirno")
    assert not (temp_root / "touhou" / "stories" / "cupa").exists()
    assert (temp_root / "touhou" / "stories" / "cirno" / "story.json").is_file()
    assert [s["slug"] for s in store.list_projects()[0]["stories"]] == ["cirno"]
    # The character was the folder name, so it follows: the story still exports
    # under the name you just gave it.
    assert renamed["meta"]["character"] == "cirno"


def test_rename_story_keeps_a_deliberate_character(pack, temp_root):
    """A character name the author chose is a decision, not a default."""
    store.save_story("touhou", "cupa", {"character": "sakuya"}, {"main.story": []})
    renamed = store.rename_story("touhou", "cupa", "sakuya_route")
    assert renamed["meta"]["character"] == "sakuya", "an explicit trigger survives a rename"
    assert renamed["slug"] == "sakuya_route"


def test_rename_story_never_touches_blocks(pack, temp_root):
    """Renaming is a folder move, not a rewrite.

    The story's blocks must survive a rename byte-for-byte. Doing this through
    the save endpoint instead would re-upload every file, and an empty or
    partial upload would silently destroy the script.
    """
    blocks = [
        {"kind": "label", "data": {"name": "start"}},
        {"kind": "say", "data": {"label": "Cupa", "content": "Do not lose me."}},
        {"kind": "end", "data": {}},
    ]
    store.save_story("touhou", "cupa", {"character": "cupa"}, {"main.story": blocks})

    store.rename_story("touhou", "cupa", "cupa_main", character="cupa")
    after = store.load_story("touhou", "cupa_main")
    assert after["files"]["main.story"] == blocks, "renaming must not rewrite the script"


def test_rename_story_can_set_a_different_character(pack, temp_root):
    """The character is independent of the folder name, and one call sets both."""
    blocks = [{"kind": "label", "data": {"name": "start"}}]
    store.save_story("touhou", "cupa", {"character": "cupa"}, {"main.story": blocks})

    store.rename_story("touhou", "cupa", "cupa_alt", character="sakuya")
    after = store.load_story("touhou", "cupa_alt")
    assert after["slug"] == "cupa_alt"
    assert after["meta"]["character"] == "sakuya"
    assert after["files"]["main.story"] == blocks


def test_delete_story_leaves_the_project(pack, temp_root):
    store.delete_story("touhou", "cupa")
    assert not (temp_root / "touhou" / "stories" / "cupa").exists()
    assert (temp_root / "touhou" / "project.json").is_file()
    assert store.load_project("touhou")["stories"] == []


def test_delete_story_leaves_shared_assets(pack, temp_root):
    """Assets belong to the pack, so removing a story must not remove the art."""
    (temp_root / "touhou" / "images" / "asset" / "end.png").write_bytes(b"x")
    store.delete_story("touhou", "cupa")
    assert (temp_root / "touhou" / "images" / "asset" / "end.png").is_file()


# ── bundle import ───────────────────────────────────────────────────────────


def test_import_bundle_roundtrip(pack, temp_root):
    project = store.load_project("touhou")
    stories = {}
    for summary in project["stories"]:
        loaded = store.load_story("touhou", summary["slug"])
        stories[summary["slug"]] = (loaded["meta"], loaded["files"])

    bundle = build_project_bundle(project["meta"], stories, temp_root / "touhou")
    imported = store.import_project_zip("touhou-imported", bundle)

    assert imported["slug"] == "touhou-imported"
    assert [s["slug"] for s in imported["stories"]] == ["cupa"]


def test_import_rejects_bad_zip(temp_root):
    with pytest.raises(store.ProjectError):
        store.import_project_zip("bad", b"not a zip")


# ── single-story export formats ─────────────────────────────────────────────


def _compiled():
    meta = {"character": "cupa", "packName": "Cupa's Story"}
    files = {"main.story": [
        {"kind": "label", "data": {"name": "start"}},
        {"kind": "say", "data": {"label": "Cupa", "content": "Oh hey!"}},
        {"kind": "choice", "data": {"choices": [{"label": "yes", "display": "Yes"}]}},
        {"kind": "label", "data": {"name": "yes"}},
        {"kind": "say", "data": {"label": "Cupa", "content": "Great!"}},
        {"kind": "end", "data": {}},
    ]}
    return meta, compile_project(meta, files)


def test_export_json_is_compiled_actions():
    meta, result = _compiled()
    assert result.errors == []
    actions = json.loads(build_json(meta, result))
    assert actions[0]["type"] == "meta"
    assert any(a["type"] == "dialogue" and a["content"] == "Oh hey!" for a in actions)


def test_export_txt_and_md_are_readable():
    meta, result = _compiled()
    txt = build_text(meta, result).decode("utf-8")
    md = build_markdown(meta, result).decode("utf-8")
    assert "Cupa: Oh hey!" in txt
    assert "## start" in md
    assert "**Cupa:** Oh hey!" in md
    assert "Yes -> yes" in md


def test_export_filename_for_formats():
    meta = {"packName": "Cupa's Story", "character": "cupa"}
    assert export_filename_for(meta, "json") == "cupa.json"
    assert export_filename_for(meta, "txt") == "cupa-s-story.txt"
    assert export_filename_for(meta, "md") == "cupa-s-story.md"
    assert export_filename_for(meta, "bundle") == "cupa-s-story.hikarin.zip"
    assert export_filename_for(meta, "pack") == "cupa-s-story.zip"