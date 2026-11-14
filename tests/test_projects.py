"""Project storage and export tests — real files in a temp directory.

The model under test: a project is a pack, a story is one character's script inside
it, and ``.story`` files are the tabs of that script. Every test here builds
real folders, because the whole point of this module is the shape on disk.
"""

from __future__ import annotations

import io
import json
import zipfile

import pytest

from hikarin import projects as store
from hikarin.compiler import compile_project
from hikarin.exporter import DEFAULT_PACK_FORMAT, build_pack, export_filename, story_filename


@pytest.fixture
def temp_root(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "PROJECTS_ROOT", tmp_path)
    return tmp_path


@pytest.fixture
def pack(temp_root):
    """A project with two stories in it — the shape the editor actually sees."""
    store.create_project("touhou", {"packName": "Touhou Pack"})
    store.create_story("touhou", "cupa", {"character": "cupa"})
    store.create_story("touhou", "reimu", {"character": "reimu"})
    return "touhou"


# ── the shape on disk ───────────────────────────────────────────────────────


def test_create_project_scaffolds_mediafile_layout(temp_root):
    """The folder shape mirrors the SDK's mediafile directory."""
    p = store.create_project("touhou")
    root = temp_root / "touhou"

    assert p["slug"] == "touhou"
    assert p["stories"] == [], "a new project has no stories yet"
    assert (root / "project.json").is_file()

    assert (root / "images" / "characters").is_dir()
    assert (root / "images" / "asset").is_dir()
    assert (root / "sounds" / "music").is_dir()
    assert (root / "sounds" / "sound").is_dir()

    # A note in each folder so the layout explains itself in Explorer.
    assert (root / "images" / "characters" / "Add Character Sprite Here.txt").is_file()
    assert (root / "images" / "asset" / "Add Background Here.txt").is_file()


def test_create_story_scaffolds_one_file(temp_root):
    store.create_project("touhou")
    s = store.create_story("touhou", "cupa", {"character": "cupa"})

    root = temp_root / "touhou" / "stories" / "cupa"
    assert s["slug"] == "cupa"
    assert s["meta"]["character"] == "cupa"
    assert list(s["files"]) == ["main.story"]
    assert (root / "story.json").is_file()
    assert (root / "main.story").is_file()


def test_project_lists_its_stories(temp_root):
    """The manager draws this; it must not need to parse any blocks."""
    store.create_project("touhou")
    store.create_story("touhou", "cupa", {"character": "cupa"})
    store.create_story("touhou", "reimu", {"character": "reimu"})

    projects = store.list_projects()
    assert len(projects) == 1
    assert projects[0]["slug"] == "touhou"
    assert projects[0]["storyCount"] == 2
    assert [s["slug"] for s in projects[0]["stories"]] == ["cupa", "reimu"]


def test_create_rejects_duplicate(temp_root):
    store.create_project("touhou")
    with pytest.raises(store.ProjectError):
        store.create_project("touhou")


def test_create_rejects_duplicate_story(temp_root):
    store.create_project("touhou")
    store.create_story("touhou", "cupa")
    with pytest.raises(store.ProjectError):
        store.create_story("touhou", "cupa")


def test_story_needs_a_project(temp_root):
    with pytest.raises(store.ProjectError):
        store.create_story("nonexistent", "cupa")


@pytest.mark.parametrize("bad", ["../evil", "has space", "", "UPPER", "a/b"])
def test_create_rejects_bad_slugs(temp_root, bad):
    with pytest.raises(store.ProjectError):
        store.create_project(bad)


# ── save / load ─────────────────────────────────────────────────────────────


def test_save_and_load_roundtrip(temp_root):
    store.create_project("touhou")
    store.create_story("touhou", "cupa")

    meta = {"character": "cupa", "startLabel": "start", "description": "Cupa route"}
    files = {
        "main.story": [
            {"kind": "label", "data": {"name": "start"}},
            {"kind": "say", "data": {"label": "Cupa", "content": "Hi."}},
            {"kind": "end", "data": {}},
        ]
    }
    store.save_story("touhou", "cupa", meta, files)

    loaded = store.load_story("touhou", "cupa")
    assert loaded["files"]["main.story"] == files["main.story"]
    assert loaded["meta"]["description"] == "Cupa route"
    assert loaded["projectSlug"] == "touhou"


def test_save_deletes_removed_files(temp_root):
    """Deleting a tab deletes the file, so a reload cannot resurrect it."""
    store.create_project("touhou")
    store.create_story("touhou", "cupa")

    store.save_story("touhou", "cupa", {"startLabel": "start"}, {
        "main.story": [{"kind": "label", "data": {"name": "start"}}],
        "night.story": [{"kind": "label", "data": {"name": "night"}}],
    })
    assert (temp_root / "touhou" / "stories" / "cupa" / "night.story").is_file()

    store.save_story("touhou", "cupa", {"startLabel": "start"}, {
        "main.story": [{"kind": "label", "data": {"name": "start"}}],
    })
    assert not (temp_root / "touhou" / "stories" / "cupa" / "night.story").exists()


def test_save_refuses_a_deleted_story(temp_root):
    """The invariant: a save can never resurrect a story the user deleted."""
    store.create_project("touhou")
    store.create_story("touhou", "cupa")
    store.delete_story("touhou", "cupa")

    with pytest.raises(store.ProjectError):
        store.save_story("touhou", "cupa", {}, {"main.story": []})


def test_story_labels_do_not_leak_into_another_story(temp_root):
    """Labels are story-scoped: two stories may both have a 'start'."""
    store.create_project("touhou")
    for name in ("cupa", "reimu"):
        store.create_story("touhou", name)

    # Same label name in both, which would be a duplicate error in one compile.
    for name in ("cupa", "reimu"):
        result = store.compile_slug("touhou", name)
        assert result.ok, result.errors


# ── assets ──────────────────────────────────────────────────────────────────


def test_asset_inventory_reads_mediafile_layout(temp_root):
    """images/characters/<id>/<outfit>/<emotion>.png, per the SDK's mediafile."""
    store.create_project("touhou")
    root = temp_root / "touhou"

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
    store.create_project("touhou")
    root = temp_root / "touhou"
    (root / "images" / "pack.png").write_bytes(b"x")

    inventory = store.list_assets(root)
    assert inventory["backgrounds"] == []
    assert inventory["characters"] == {}


def test_asset_inventory_indexes_plain_image_folders(temp_root):
    """images/asset/ doubles as the pool for show_custom boxes."""
    store.create_project("touhou")
    root = temp_root / "touhou"
    (root / "images" / "asset" / "old-dsl.png").write_bytes(b"x")
    (root / "images" / "asset" / "void.png").write_bytes(b"x")

    inventory = store.list_assets(root)
    assert inventory["folders"]["asset"] == ["old-dsl", "void"]
    # and still listed as backgrounds, since a Background block uses the same file
    assert "asset/old-dsl.png" in inventory["backgrounds"]


def test_assets_are_shared_across_stories(pack, temp_root):
    """A pack's art belongs to the project, so every story sees it."""
    root = temp_root / pack
    sprite = root / "images" / "characters" / "cupa" / "default"
    sprite.mkdir(parents=True, exist_ok=True)
    (sprite / "happy.png").write_bytes(b"x")

    for story in ("cupa", "reimu"):
        loaded = store.load_story(pack, story)
        assert "cupa" in loaded["assets"]["characters"], f"{story} cannot see the sprite"


# ── export ──────────────────────────────────────────────────────────────────


def test_export_builds_real_resource_pack(pack, temp_root):
    root = temp_root / pack
    sprite = root / "images" / "characters" / "cupa" / "default"
    sprite.mkdir(parents=True, exist_ok=True)
    (sprite / "happy.png").write_bytes(b"PNGDATA")
    (root / "images" / "asset" / "end.png").write_bytes(b"BG")
    (root / "images" / "pack.png").write_bytes(b"ICON")
    (root / "sounds" / "music" / "haggstrom.ogg").write_bytes(b"OGG")

    stories = {}
    for summary in store.load_project(pack)["stories"]:
        meta = store.load_story(pack, summary["slug"])["meta"]
        stories[summary["slug"]] = (meta, store.compile_slug(pack, summary["slug"]))

    meta = store.load_project(pack)["meta"]
    payload = build_pack(meta, stories, root)

    with zipfile.ZipFile(io.BytesIO(payload)) as zf:
        names = set(zf.namelist())

        assert "pack.mcmeta" in names
        assert "pack.png" in names, "images/pack.png becomes the pack icon"

        # one JSON per story, named by the trigger
        assert "assets/hikarin/cupa.json" in names
        assert "assets/hikarin/reimu.json" in names

        # images/ -> textures/, structure preserved
        assert "assets/hikarin/textures/characters/cupa/default/happy.png" in names
        assert "assets/hikarin/textures/asset/end.png" in names
        assert "assets/hikarin/textures/pack.png" not in names, "icon must not ship twice"

        # sounds/ maps one-to-one
        assert "assets/hikarin/sounds/music/haggstrom.ogg" in names

        mcmeta = json.loads(zf.read("pack.mcmeta"))
        assert mcmeta["pack"]["pack_format"] == 15

        assert zf.read("assets/hikarin/textures/characters/cupa/default/happy.png") == b"PNGDATA"


def test_pack_format_is_an_export_option_not_a_project_field(pack, temp_root):
    """The same scripts can be built for several runtime versions.

    Nothing about the project changes when the target format changes — only the
    export call does.
    """
    project = store.load_project(pack)
    assert "packFormat" not in project["meta"], "pack format is not project state"

    stories = {}
    for summary in project["stories"]:
        loaded = store.load_story(pack, summary["slug"])
        stories[summary["slug"]] = (loaded["meta"], store.compile_slug(pack, summary["slug"]))

    root = store.project_dir(pack)

    default_pack = build_pack(project["meta"], stories, root)
    newer_pack = build_pack(project["meta"], stories, root, pack_format=99)

    def fmt_of(payload):
        with zipfile.ZipFile(io.BytesIO(payload)) as zf:
            return json.loads(zf.read("pack.mcmeta"))["pack"]["pack_format"]

    assert fmt_of(default_pack) == DEFAULT_PACK_FORMAT
    assert fmt_of(newer_pack) == 99, "the export argument must win"

    # and the project on disk is untouched by either export
    assert "packFormat" not in store.load_project(pack)["meta"]


def test_export_refuses_empty_project(temp_root):
    store.create_project("touhou")
    meta = store.load_project("touhou")["meta"]
    with pytest.raises(ValueError):
        build_pack(meta, {}, temp_root / "touhou")


def test_export_refuses_broken_story(temp_root):
    store.create_project("touhou")
    store.create_story("touhou", "cupa")
    meta = {"character": "cupa"}
    files = {"main.story": [
        {"kind": "label", "data": {"name": "start"}},
        {"kind": "jump", "data": {"target": "nowhere"}},
    ]}
    result = compile_project(meta, files)
    assert result.errors
    with pytest.raises(ValueError):
        build_pack(meta, {"cupa": (meta, result)}, temp_root / "touhou")


def test_export_refuses_two_stories_with_one_trigger(pack):
    """Two stories compiling to the same file name would overwrite in the zip."""
    meta = store.load_project(pack)["meta"]
    files = {"main.story": [{"kind": "label", "data": {"name": "start"}}]}

    # Same character name, different story slugs.
    store.save_story(pack, "cupa", {"character": "same"}, files)
    store.save_story(pack, "reimu", {"character": "same"}, files)

    stories = {
        "cupa": ({"character": "same"}, compile_project({"character": "same"}, files)),
        "reimu": ({"character": "same"}, compile_project({"character": "same"}, files)),
    }
    with pytest.raises(ValueError):
        build_pack(meta, stories, store.project_dir(pack))


def test_story_filename_is_the_trigger():
    assert story_filename({"character": "Cupa"}) == "cupa"
    assert story_filename({"character": "Hong Meiling"}) == "hong_meiling"
    assert story_filename({"slug": "fallback"}) == "fallback"


def test_export_filename_is_safe():
    assert export_filename({"packName": "Cupa's Story"}) == "cupa-s-story.zip"
    assert export_filename({"packName": "Touhou Pack"}) == "touhou-pack.zip"
    assert export_filename({}) == "pack.zip"


def test_bundle_roundtrip_keeps_both_stories(pack, temp_root):
    from hikarin.exporter import build_project_bundle

    project = store.load_project(pack)
    stories = {}
    for summary in project["stories"]:
        loaded = store.load_story(pack, summary["slug"])
        stories[summary["slug"]] = (loaded["meta"], loaded["files"])

    bundle = build_project_bundle(project["meta"], stories, temp_root / pack)

    imported = store.import_project_zip("imported", bundle)
    assert imported["slug"] == "imported"
    assert imported["meta"]["stories"] == ["cupa", "reimu"], "both stories survive the import"
    assert (temp_root / "imported" / "stories" / "cupa" / "main.story").is_file()
    assert (temp_root / "imported" / "stories" / "reimu" / "main.story").is_file()