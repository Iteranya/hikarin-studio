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
    store.create_script("touhou", "cupa", "main", {"character": "cupa"})
    return "touhou"


# ── project-level management ────────────────────────────────────────────────


def test_duplicate_project_copies_every_script(pack, temp_root):
    store.create_script("touhou", "reimu", "main", {"character": "reimu"})

    dup = store.duplicate_project("touhou", "touhou-copy")
    assert dup["slug"] == "touhou-copy"
    assert (temp_root / "touhou-copy" / "project.json").is_file()
    assert (temp_root / "touhou-copy" / "stories" / "cupa" / "main" / "main.story").is_file()
    assert (temp_root / "touhou-copy" / "stories" / "reimu" / "main" / "main.story").is_file()
    assert {f'{s["character"]}/{s["script"]}' for s in dup["scripts"]} == {
        "cupa/main",
        "reimu/main",
    }

    with pytest.raises(store.ProjectError):
        store.duplicate_project("touhou", "touhou-copy")


def test_rename_project_moves_folder(pack, temp_root):
    r = store.rename_project("touhou", "moriya")
    assert r["slug"] == "moriya"
    assert not (temp_root / "touhou").exists()
    assert (temp_root / "moriya" / "project.json").is_file()
    assert (temp_root / "moriya" / "stories" / "cupa" / "main" / "main.story").is_file()


def test_delete_project_removes_every_script(pack, temp_root):
    store.create_script("touhou", "reimu", "main", {"character": "reimu"})
    store.delete_project("touhou")
    assert not (temp_root / "touhou").exists()


# ── script-level management ─────────────────────────────────────────────────


def test_duplicate_script(pack, temp_root):
    dup = store.duplicate_script("touhou", "cupa", "main", "alt")
    assert dup["script"] == "alt"
    assert dup["meta"]["character"] == "cupa"
    assert (temp_root / "touhou" / "stories" / "cupa" / "alt" / "main.story").is_file()


def test_rename_script(pack, temp_root):
    renamed = store.rename_script("touhou", "cupa", "main", "intro")
    assert not (temp_root / "touhou" / "stories" / "cupa" / "main").exists()
    assert (temp_root / "touhou" / "stories" / "cupa" / "intro" / "story.json").is_file()
    assert [f'{s["character"]}/{s["script"]}' for s in store.load_project("touhou")["scripts"]] == [
        "cupa/intro"
    ]
    assert renamed["script"] == "intro"


def test_rename_script_keeps_blocks_byte_for_byte(pack, temp_root):
    """Renaming is a folder move, not a rewrite.

    The script's blocks must survive a rename byte-for-byte. Doing this through
    the save endpoint instead would re-upload every file, and an empty or
    partial upload would silently destroy the script.
    """
    blocks = [
        {"kind": "label", "data": {"name": "start"}},
        {"kind": "say", "data": {"label": "Cupa", "content": "Do not lose me."}},
        {"kind": "end", "data": {}},
    ]
    store.save_script("touhou", "cupa", "main", {"character": "cupa"}, {"main.story": blocks})

    store.rename_script("touhou", "cupa", "main", "intro")
    after = store.load_script("touhou", "cupa", "intro")
    assert after["files"]["main.story"] == blocks, "renaming must not rewrite the script"


def test_rename_script_can_move_to_another_character(pack, temp_root):
    """A script can move under a different character in one call."""
    blocks = [{"kind": "label", "data": {"name": "start"}}]
    store.save_script("touhou", "cupa", "main", {"character": "cupa"}, {"main.story": blocks})

    store.rename_script("touhou", "cupa", "main", "main", new_character="sakuya")
    # cupa now has no scripts, so its folder is gone.
    assert not (temp_root / "touhou" / "stories" / "cupa").exists()
    after = store.load_script("touhou", "sakuya", "main")
    assert after["meta"]["character"] == "sakuya"
    assert after["files"]["main.story"] == blocks


def test_delete_script_leaves_the_project(pack, temp_root):
    store.delete_script("touhou", "cupa", "main")
    assert not (temp_root / "touhou" / "stories" / "cupa").exists()
    assert (temp_root / "touhou" / "project.json").is_file()
    assert store.load_project("touhou")["scripts"] == []


def test_delete_script_leaves_shared_assets(pack, temp_root):
    """Assets belong to the pack, so removing a script must not remove the art."""
    (temp_root / "touhou" / "images" / "asset" / "end.png").write_bytes(b"x")
    store.delete_script("touhou", "cupa", "main")
    assert (temp_root / "touhou" / "images" / "asset" / "end.png").is_file()


def test_delete_character_removes_every_script(pack, temp_root):
    store.create_script("touhou", "cupa", "night", {"character": "cupa"})
    store.delete_character("touhou", "cupa")
    assert not (temp_root / "touhou" / "stories" / "cupa").exists()
    assert store.load_project("touhou")["scripts"] == []


# ── bundle import ───────────────────────────────────────────────────────────


def test_import_bundle_roundtrip(pack, temp_root):
    project = store.load_project("touhou")
    raw = {}
    for summary in project["scripts"]:
        loaded = store.load_script("touhou", summary["character"], summary["script"])
        raw[f'{summary["character"]}/{summary["script"]}'] = (loaded["meta"], loaded["files"])

    bundle = build_project_bundle(project["meta"], raw, temp_root / "touhou")
    imported = store.import_project_zip("touhou-imported", bundle)

    assert imported["slug"] == "touhou-imported"
    assert [f'{s["character"]}/{s["script"]}' for s in imported["scripts"]] == ["cupa/main"]


def test_import_rejects_bad_zip(temp_root):
    with pytest.raises(store.ProjectError):
        store.import_project_zip("bad", b"not a zip")


# ── single-script export formats ────────────────────────────────────────────


def _compiled():
    meta = {"character": "cupa", "script": "main", "packName": "Cupa's Story"}
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