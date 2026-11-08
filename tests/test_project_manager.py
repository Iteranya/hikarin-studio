"""Project manager + export format tests."""

from __future__ import annotations

import json
import zipfile
import io

import pytest

from hikarin import projects as store
from hikarin.compiler import compile_project
from hikarin.exporter import build_json, build_markdown, build_project_bundle, build_text, export_filename_for


@pytest.fixture
def temp_root(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "PROJECTS_ROOT", tmp_path)
    return tmp_path


def test_duplicate_project_copies_stories(temp_root):
    store.create_project("cupa")
    dup = store.duplicate_project("cupa", "cupa-copy")
    assert dup["slug"] == "cupa-copy"
    assert (temp_root / "cupa-copy" / "project.json").is_file()
    assert (temp_root / "cupa-copy" / "main.story").is_file()
    with pytest.raises(store.ProjectError):
        store.duplicate_project("cupa", "cupa-copy")


def test_rename_project_moves_folder(temp_root):
    store.create_project("cupa")
    r = store.rename_project("cupa", "moriya")
    assert r["slug"] == "moriya"
    assert not (temp_root / "cupa").exists()
    assert (temp_root / "moriya" / "project.json").is_file()


def test_import_bundle_roundtrip(temp_root):
    store.create_project("cupa")
    loaded = store.load_project("cupa")
    meta, files = loaded["meta"], loaded["files"]
    bundle = build_project_bundle(meta, files, temp_root / "cupa")
    imported = store.import_project_zip("cupa-imported", bundle)
    assert imported["slug"] == "cupa-imported"
    assert (temp_root / "cupa-imported" / "main.story").is_file()


def test_import_rejects_bad_zip(temp_root):
    with pytest.raises(store.ProjectError):
        store.import_project_zip("bad", b"not a zip")


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
