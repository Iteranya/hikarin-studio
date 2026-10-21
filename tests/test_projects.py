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


def test_create_project_scaffolds_mediafile_layout(temp_root):
    """The folder shape mirrors the SDK's mediafile directory."""
    p = store.create_project("cupa")
    root = temp_root / "cupa"

    assert p["slug"] == "cupa"
    assert (root / "project.json").is_file()
    assert (root / "main.story").is_file()
    assert "main.story" in p["files"]

    assert (root / "images" / "characters").is_dir()
    assert (root / "images" / "asset").is_dir()
    assert (root / "sounds" / "music").is_dir()
    assert (root / "sounds" / "sound").is_dir()

    # A note in each folder so the layout explains itself in Explorer.
    assert (root / "images" / "characters" / "Add Character Sprite Here.txt").is_file()
    assert (root / "images" / "asset" / "Add Background Here.txt").is_file()


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


def test_asset_inventory_reads_mediafile_layout(temp_root):
    """images/characters/<id>/<outfit>/<emotion>.png, per the SDK's mediafile."""
    store.create_project("cupa")
    root = temp_root / "cupa"

    default_dir = root / "images" / "characters" / "cupa" / "default"
    default_dir.mkdir(parents=True, exist_ok=True)
    (default_dir / "happy.png").write_bytes(b"x")
    (default_dir / "angry.png").write_bytes(b"x")

    summer_dir = root / "images" / "characters" / "cupa" / "summer"
    summer_dir.mkdir(parents=True, exist_ok=True)
    (summer_dir / "happy.png").write_bytes(b"x")

    (root / "images" / "asset" / "end.png").write_bytes(b"x")
    (root / "images" / "pack.png").write_bytes(b"x")
    (root / "sounds" / "sound" / "teleport.ogg").write_bytes(b"x")
    (root / "sounds" / "music" / "haggstrom.ogg").write_bytes(b"x")

    inventory = store.list_assets(root)
    assert inventory["characters"]["cupa"]["default"] == ["angry", "happy"]
    assert inventory["characters"]["cupa"]["summer"] == ["happy"]

    # Backgrounds keep their folder prefix: a script must write asset/end.png
    assert inventory["backgrounds"] == ["asset/end.png"]
    assert "pack.png" not in inventory["backgrounds"], "the pack icon is not a background"

    assert inventory["sounds"] == ["sound/teleport.ogg"]
    assert inventory["music"] == ["music/haggstrom.ogg"]


def test_asset_inventory_ignores_pack_icon(temp_root):
    """images/pack.png is the resource pack icon, not story content."""
    store.create_project("cupa")
    root = temp_root / "cupa"
    (root / "images" / "pack.png").write_bytes(b"x")

    inventory = store.list_assets(root)
    assert inventory["backgrounds"] == []
    assert inventory["characters"] == {}


def test_export_builds_real_resource_pack(temp_root):
    store.create_project("cupa")
    meta = {"character": "cupa", "packName": "Cupa's Story", "packFormat": 15}
    files = {"main.story": [
        {"kind": "label", "data": {"name": "start"}},
        {"kind": "say", "data": {"label": "Cupa", "content": "Hi."}},
        {"kind": "end", "data": {}},
    ]}
    store.save_project("cupa", meta, files)

    root = temp_root / "cupa"
    sprite = root / "images" / "characters" / "cupa" / "default"
    sprite.mkdir(parents=True, exist_ok=True)
    (sprite / "happy.png").write_bytes(b"PNGDATA")
    (root / "images" / "asset" / "end.png").write_bytes(b"BG")
    (root / "images" / "pack.png").write_bytes(b"ICON")
    (root / "sounds" / "music" / "haggstrom.ogg").write_bytes(b"OGG")

    result = compile_project(meta, files)
    payload = build_pack(meta, result, root)

    with zipfile.ZipFile(io.BytesIO(payload)) as zf:
        names = set(zf.namelist())

        assert "pack.mcmeta" in names
        assert "pack.png" in names, "images/pack.png becomes the pack icon"
        assert "assets/hikarin/cupa.json" in names

        # images/ -> textures/, structure preserved
        assert "assets/hikarin/textures/characters/cupa/default/happy.png" in names
        assert "assets/hikarin/textures/asset/end.png" in names
        assert "assets/hikarin/textures/pack.png" not in names, "icon must not ship twice"

        # sounds/ maps one-to-one
        assert "assets/hikarin/sounds/music/haggstrom.ogg" in names

        mcmeta = json.loads(zf.read("pack.mcmeta"))
        assert mcmeta["pack"]["pack_format"] == 15

        assert zf.read("assets/hikarin/textures/characters/cupa/default/happy.png") == b"PNGDATA"


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


def test_asset_inventory_indexes_plain_image_folders(temp_root):
    """images/asset/ doubles as the pool for show_custom boxes."""
    store.create_project("cupa")
    root = temp_root / "cupa"
    (root / "images" / "asset" / "old-dsl.png").write_bytes(b"x")
    (root / "images" / "asset" / "void.png").write_bytes(b"x")

    inventory = store.list_assets(root)
    assert inventory["folders"]["asset"] == ["old-dsl", "void"]
    # and still listed as backgrounds, since a Background block uses the same file
    assert "asset/old-dsl.png" in inventory["backgrounds"]
