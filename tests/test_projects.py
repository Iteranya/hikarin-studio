"""Project storage and export tests — real files in a temp directory."""

from __future__ import annotations

import io
import json
import zipfile

import pytest

from hikarin import projects as store
from hikarin.compiler import compile_project
from hikarin.exporter import build_pack, export_filename


@pytest.fixture
def temp_root(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "PROJECTS_ROOT", tmp_path)
    return tmp_path


def test_create_project_writes_scaffold(temp_root):
    p = store.create_project("cupa")
    assert p["slug"] == "cupa"
    assert (temp_root / "cupa" / "project.json").is_file()
    assert (temp_root / "cupa" / "main.story").is_file()
    assert (temp_root / "cupa" / "assets").is_dir()
    assert "main.story" in p["files"]


def test_create_rejects_duplicate(temp_root):
    store.create_project("cupa")
    with pytest.raises(store.ProjectError):
        store.create_project("cupa")


@pytest.mark.parametrize("bad", ["../evil", "has space", "", "UPPER", "a/b"])
def test_create_rejects_bad_slugs(temp_root, bad):
    with pytest.raises(store.ProjectError):
        store.create_project(bad)


def test_save_and_load_roundtrip(temp_root):
    store.create_project("cupa")
    meta = {"character": "cupa", "startLabel": "start", "packName": "Cupa's Story"}
    files = {
        "main.story": [
            {"kind": "label", "data": {"name": "start"}},
            {"kind": "say", "data": {"label": "Cupa", "content": "Hi."}},
            {"kind": "end", "data": {}},
        ]
    }
    store.save_project("cupa", meta, files)
    loaded = store.load_project("cupa")
    assert loaded["files"]["main.story"] == files["main.story"]
    assert loaded["meta"]["packName"] == "Cupa's Story"


def test_save_deletes_removed_files(temp_root):
    store.create_project("cupa")
    store.save_project("cupa", {"startLabel": "start"}, {
        "main.story": [{"kind": "label", "data": {"name": "start"}}],
        "night.story": [{"kind": "label", "data": {"name": "night"}}],
    })
    assert (temp_root / "cupa" / "night.story").is_file()

    store.save_project("cupa", {"startLabel": "start"}, {
        "main.story": [{"kind": "label", "data": {"name": "start"}}],
    })
    assert not (temp_root / "cupa" / "night.story").exists(), "deleted tab must not linger on disk"


def test_asset_inventory_reads_sdk_layout(temp_root):
    """characters/<id>/<outfit>/<emotion>.png, per the original SDK."""
    store.create_project("cupa")
    assets = temp_root / "cupa" / "assets"

    default_dir = assets / "characters" / "cupa" / "default"
    default_dir.mkdir(parents=True)
    (default_dir / "happy.png").write_bytes(b"x")
    (default_dir / "angry.png").write_bytes(b"x")

    summer_dir = assets / "characters" / "cupa" / "summer"
    summer_dir.mkdir(parents=True)
    (summer_dir / "happy.png").write_bytes(b"x")
    (assets / "room.png").write_bytes(b"x")
    (assets / "click.ogg").write_bytes(b"x")

    inventory = store.list_assets(temp_root / "cupa")
    assert inventory["characters"]["cupa"]["default"] == ["angry", "happy"]
    assert inventory["characters"]["cupa"]["summer"] == ["happy"]
    assert inventory["backgrounds"] == ["room.png"]
    assert inventory["sounds"] == ["click.ogg"]


def test_asset_inventory_tolerates_two_level_folders(temp_root):
    """Hand-made <id>/<emotion>.png folders read as outfit "default"."""
    store.create_project("cupa")
    assets = temp_root / "cupa" / "assets"
    (assets / "cupa").mkdir(parents=True)
    (assets / "cupa" / "happy.png").write_bytes(b"x")

    inventory = store.list_assets(temp_root / "cupa")
    assert inventory["characters"]["cupa"]["default"] == ["happy"]


def test_export_builds_real_resource_pack(temp_root):
    store.create_project("cupa")
    meta = {"character": "cupa", "packName": "Cupa's Story", "packFormat": 15}
    files = {"main.story": [
        {"kind": "label", "data": {"name": "start"}},
        {"kind": "say", "data": {"label": "Cupa", "content": "Hi."}},
        {"kind": "end", "data": {}},
    ]}
    store.save_project("cupa", meta, files)

    assets = temp_root / "cupa" / "assets"
    (assets / "cupa").mkdir(exist_ok=True)
    (assets / "cupa" / "happy.png").write_bytes(b"PNGDATA")

    result = compile_project(meta, files)
    payload = build_pack(meta, result, temp_root / "cupa")

    with zipfile.ZipFile(io.BytesIO(payload)) as zf:
        names = set(zf.namelist())
        assert "pack.mcmeta" in names
        assert "assets/hikarin/cupa.json" in names
        assert "assets/hikarin/textures/cupa/happy.png" in names

        mcmeta = json.loads(zf.read("pack.mcmeta"))
        assert mcmeta["pack"]["pack_format"] == 15

        story = json.loads(zf.read("assets/hikarin/cupa.json"))
        assert story[0]["type"] == "meta"
        assert any(a["type"] == "dialogue" for a in story)

        assert zf.read("assets/hikarin/textures/cupa/happy.png") == b"PNGDATA"


def test_export_refuses_broken_story(temp_root):
    meta = {"character": "cupa"}
    files = {"main.story": [
        {"kind": "label", "data": {"name": "start"}},
        {"kind": "jump", "data": {"target": "nowhere"}},
    ]}
    result = compile_project(meta, files)
    assert result.errors
    with pytest.raises(ValueError):
        build_pack(meta, result, temp_root)


def test_export_filename_is_safe():
    assert export_filename({"packName": "Cupa's Story"}) == "cupa-s-story.zip"
    assert export_filename({"character": "cupa"}) == "cupa.zip"
    assert export_filename({}) == "story.zip"
