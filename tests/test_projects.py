"""Project storage and export tests — real files in a temp directory.

The model under test: a project is a pack, a character is one in-game person,
and a script is one of that character's conversations. A script's ``.story``
files are its tabs. Every test here builds real folders, because the whole
point of this module is the shape on disk: ``stories/<character>/<script>/``.
"""

from __future__ import annotations

import io
import json
import zipfile

import pytest

from hikarin import projects as store
from hikarin.compiler import compile_project
from hikarin.exporter import (
    DEFAULT_PACK_FORMAT,
    build_hikarin,
    build_pack,
    export_filename,
    script_slug,
    story_filename,
)


@pytest.fixture
def temp_root(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "PROJECTS_ROOT", tmp_path)
    return tmp_path


@pytest.fixture
def pack(temp_root):
    """A project with two characters — the shape the editor actually sees."""
    store.create_project("touhou", {"packName": "Touhou Pack"})
    store.create_script("touhou", "cupa", "main", {"character": "cupa"})
    store.create_script("touhou", "reimu", "main", {"character": "reimu"})
    return "touhou"


# ── the shape on disk ───────────────────────────────────────────────────────


def test_create_project_scaffolds_mediafile_layout(temp_root):
    """The folder shape mirrors the SDK's mediafile directory."""
    p = store.create_project("touhou")
    root = temp_root / "touhou"

    assert p["slug"] == "touhou"
    assert p["characters"] == [], "a new project has no characters yet"
    assert (root / "project.json").is_file()

    assert (root / "images" / "characters").is_dir()
    assert (root / "images" / "asset").is_dir()
    assert (root / "sounds" / "music").is_dir()
    assert (root / "sounds" / "sound").is_dir()

    # A note in each folder so the layout explains itself in Explorer.
    assert (root / "images" / "characters" / "Add Character Sprite Here.txt").is_file()
    assert (root / "images" / "asset" / "Add Background Here.txt").is_file()


def test_create_script_scaffolds_one_file(temp_root):
    store.create_project("touhou")
    s = store.create_script("touhou", "cupa", "main", {"character": "cupa"})

    root = temp_root / "touhou" / "stories" / "cupa" / "main"
    assert s["character"] == "cupa"
    assert s["script"] == "main"
    assert s["meta"]["character"] == "cupa"
    assert list(s["files"]) == ["main.story"]
    assert (root / "story.json").is_file()
    assert (root / "main.story").is_file()


def test_character_groups_multiple_scripts(temp_root):
    """One character, several scripts — the whole point of the nesting."""
    store.create_project("touhou")
    store.create_script("touhou", "miku", "main", {"character": "miku"})
    store.create_script("touhou", "miku", "night", {"character": "miku"})

    project = store.load_project("touhou")
    assert len(project["characters"]) == 1
    group = project["characters"][0]
    assert group["character"] == "miku"
    assert [s["script"] for s in group["scripts"]] == ["main", "night"]


def test_two_characters_can_share_a_script_name(temp_root):
    """The original bug: same script name under two characters must not collide."""
    store.create_project("touhou")
    store.create_script("touhou", "miku", "main", {"character": "miku"})
    store.create_script("touhou", "rue", "main", {"character": "rue"})

    project = store.load_project("touhou")
    keys = {f'{s["character"]}/{s["script"]}' for s in project["scripts"]}
    assert keys == {"miku/main", "rue/main"}


def test_project_lists_its_scripts(temp_root):
    """The manager draws this; it must not need to parse any blocks."""
    store.create_project("touhou")
    store.create_script("touhou", "cupa", "main", {"character": "cupa"})
    store.create_script("touhou", "reimu", "main", {"character": "reimu"})

    projects = store.list_projects()
    assert len(projects) == 1
    assert projects[0]["slug"] == "touhou"
    assert projects[0]["characterCount"] == 2
    assert projects[0]["scriptCount"] == 2
    assert [c["character"] for c in projects[0]["characters"]] == ["cupa", "reimu"]


def test_create_rejects_duplicate(temp_root):
    store.create_project("touhou")
    with pytest.raises(store.ProjectError):
        store.create_project("touhou")


def test_create_rejects_duplicate_script(temp_root):
    store.create_project("touhou")
    store.create_script("touhou", "cupa", "main", {"character": "cupa"})
    with pytest.raises(store.ProjectError):
        store.create_script("touhou", "cupa", "main", {"character": "cupa"})


def test_script_needs_a_project(temp_root):
    with pytest.raises(store.ProjectError):
        store.create_script("nonexistent", "cupa", "main")


@pytest.mark.parametrize("bad", ["../evil", "has space", "", "UPPER", "a/b"])
def test_create_rejects_bad_slugs(temp_root, bad):
    with pytest.raises(store.ProjectError):
        store.create_project(bad)


# ── save / load ─────────────────────────────────────────────────────────────


def test_save_and_load_roundtrip(temp_root):
    store.create_project("touhou")
    store.create_script("touhou", "cupa", "main", {"character": "cupa"})

    meta = {"character": "cupa", "startLabel": "start", "description": "Cupa route"}
    files = {
        "main.story": [
            {"kind": "label", "data": {"name": "start"}},
            {"kind": "say", "data": {"label": "Cupa", "content": "Hi."}},
            {"kind": "end", "data": {}},
        ]
    }
    store.save_script("touhou", "cupa", "main", meta, files)

    loaded = store.load_script("touhou", "cupa", "main")
    assert loaded["files"]["main.story"] == files["main.story"]
    assert loaded["meta"]["description"] == "Cupa route"
    assert loaded["projectSlug"] == "touhou"
    assert loaded["character"] == "cupa"
    assert loaded["script"] == "main"


def test_save_deletes_removed_files(temp_root):
    """Deleting a tab deletes the file, so a reload cannot resurrect it."""
    store.create_project("touhou")
    store.create_script("touhou", "cupa", "main", {"character": "cupa"})

    store.save_script("touhou", "cupa", "main", {"startLabel": "start"}, {
        "main.story": [{"kind": "label", "data": {"name": "start"}}],
        "night.story": [{"kind": "label", "data": {"name": "night"}}],
    })
    assert (temp_root / "touhou" / "stories" / "cupa" / "main" / "night.story").is_file()

    store.save_script("touhou", "cupa", "main", {"startLabel": "start"}, {
        "main.story": [{"kind": "label", "data": {"name": "start"}}],
    })
    assert not (temp_root / "touhou" / "stories" / "cupa" / "main" / "night.story").exists()


def test_save_refuses_a_deleted_script(temp_root):
    """The invariant: a save can never resurrect a script the user deleted."""
    store.create_project("touhou")
    store.create_script("touhou", "cupa", "main", {"character": "cupa"})
    store.delete_script("touhou", "cupa", "main")

    with pytest.raises(store.ProjectError):
        store.save_script("touhou", "cupa", "main", {}, {"main.story": []})


def test_script_labels_do_not_leak_into_another_script(temp_root):
    """Labels are script-scoped: two scripts may both have a 'start'."""
    store.create_project("touhou")
    store.create_script("touhou", "cupa", "main", {"character": "cupa"})
    store.create_script("touhou", "reimu", "main", {"character": "reimu"})

    # Same label name in both, which would be a duplicate error in one compile.
    for character in ("cupa", "reimu"):
        result = store.compile_script("touhou", character, "main")
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


def test_assets_are_shared_across_scripts(pack, temp_root):
    """A pack's art belongs to the project, so every script sees it."""
    root = temp_root / pack
    sprite = root / "images" / "characters" / "cupa" / "default"
    sprite.mkdir(parents=True, exist_ok=True)
    (sprite / "happy.png").write_bytes(b"x")

    for character in ("cupa", "reimu"):
        loaded = store.load_script(pack, character, "main")
        assert "cupa" in loaded["assets"]["characters"], f"{character} cannot see the sprite"


# ── export ──────────────────────────────────────────────────────────────────


def _compiled(pack):
    """Every script in a project, compiled, keyed by ``character/script``."""
    project = store.load_project(pack)
    out = {}
    for summary in project["scripts"]:
        character, script = summary["character"], summary["script"]
        loaded = store.load_script(pack, character, script)
        out[f"{character}/{script}"] = (loaded["meta"], store.compile_script(pack, character, script))
    return out


def _raw(pack):
    """Every script's authoring files, keyed by ``character/script``."""
    project = store.load_project(pack)
    out = {}
    for summary in project["scripts"]:
        character, script = summary["character"], summary["script"]
        loaded = store.load_script(pack, character, script)
        out[f"{character}/{script}"] = (loaded["meta"], loaded["files"])
    return out


def test_export_builds_real_resource_pack(pack, temp_root):
    root = temp_root / pack
    sprite = root / "images" / "characters" / "cupa" / "default"
    sprite.mkdir(parents=True, exist_ok=True)
    (sprite / "happy.png").write_bytes(b"PNGDATA")
    (root / "images" / "asset" / "end.png").write_bytes(b"BG")
    (root / "images" / "pack.png").write_bytes(b"ICON")
    (root / "sounds" / "music" / "haggstrom.ogg").write_bytes(b"OGG")

    meta = store.load_project(pack)["meta"]
    payload = build_pack(meta, _compiled(pack), root)

    with zipfile.ZipFile(io.BytesIO(payload)) as zf:
        names = set(zf.namelist())

        assert "pack.mcmeta" in names
        assert "pack.png" in names, "images/pack.png becomes the pack icon"

        # one flat JSON per script, named <character>_<script>
        assert "assets/hikarin/cupa_main.json" in names
        assert "assets/hikarin/reimu_main.json" in names

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

    root = store.project_dir(pack)

    default_pack = build_pack(project["meta"], _compiled(pack), root)
    newer_pack = build_pack(project["meta"], _compiled(pack), root, pack_format=99)

    def fmt_of(payload):
        with zipfile.ZipFile(io.BytesIO(payload)) as zf:
            return json.loads(zf.read("pack.mcmeta"))["pack"]["pack_format"]

    assert fmt_of(default_pack) == DEFAULT_PACK_FORMAT
    assert fmt_of(newer_pack) == 99, "the export argument must win"

    # and the project on disk is untouched by either export
    assert "packFormat" not in store.load_project(pack)["meta"]


# ── plain (runtime-agnostic) export ─────────────────────────────────────────


def test_hikarin_bundle_has_no_resource_pack_layout(pack, temp_root):
    """The whole point: another runtime should not need to know about packs."""
    root = temp_root / pack
    (root / "images" / "asset").mkdir(parents=True, exist_ok=True)
    (root / "images" / "asset" / "end.png").write_bytes(b"BG")
    (root / "images" / "pack.png").write_bytes(b"ICON")
    (root / "sounds" / "music").mkdir(parents=True, exist_ok=True)
    (root / "sounds" / "music" / "haggstrom.ogg").write_bytes(b"OGG")

    project = store.load_project(pack)
    payload = build_hikarin(project["meta"], _compiled(pack), root)

    with zipfile.ZipFile(io.BytesIO(payload)) as zf:
        names = set(zf.namelist())

        # A single-script character exports under the bare character name, flat
        # at the root — no assets/hikarin/ prefix.
        assert "cupa.json" in names
        assert "reimu.json" in names
        assert not any(n.startswith("assets/") for n in names), names

        # none of the resource-pack machinery
        assert "pack.mcmeta" not in names
        assert "pack.png" not in names

        # art keeps the folder names the author gave it
        assert "images/asset/end.png" in names
        assert "sounds/music/haggstrom.ogg" in names
        assert "assets/hikarin/textures/asset/end.png" not in names

        manifest = json.loads(zf.read("manifest.json"))
        assert manifest["format"] == "hikarin"
        assert {(s["character"], s["script"]) for s in manifest["scripts"]} == {
            ("cupa", "main"),
            ("reimu", "main"),
        }
        # Each single-script character's file is the bare character name.
        assert all(s["file"] == f'{s["character"]}.json' for s in manifest["scripts"])


def test_export_disambiguates_multi_script_characters(temp_root):
    """A character with several scripts uses <character>_<script>; a character
    with one script uses the bare character name.

    This is the whole point: the character prefix only appears when it has to
    disambiguate. miku has two scripts -> miku_main / miku_night; rue has one
    -> rue.json.
    """
    store.create_project("p", {"packName": "P"})
    store.create_script("p", "miku", "main", {"character": "miku"})
    store.create_script("p", "miku", "night", {"character": "miku"})
    store.create_script("p", "rue", "main", {"character": "rue"})

    project = store.load_project("p")
    data = build_hikarin(project["meta"], _compiled("p"), store.project_dir("p"))

    zf = zipfile.ZipFile(io.BytesIO(data))
    names = zf.namelist()
    # multi-script character: character-prefixed slugs
    assert "miku_main.json" in names
    assert "miku_night.json" in names
    # single-script character: bare name
    assert "rue.json" in names
    assert "rue_main.json" not in names


def test_single_script_export_is_bare_name(temp_root):
    """The hikarin export names a single-script character's file miku.json."""
    store.create_project("p")
    store.create_script("p", "miku", "miku", {"character": "miku"})
    project = store.load_project("p")
    data = build_hikarin(project["meta"], _compiled("p"), store.project_dir("p"))
    zf = zipfile.ZipFile(io.BytesIO(data))
    names = zf.namelist()
    assert "miku.json" in names
    assert "miku_miku.json" not in names


def test_export_refuses_empty_project(temp_root):
    store.create_project("touhou")
    meta = store.load_project("touhou")["meta"]
    with pytest.raises(ValueError):
        build_pack(meta, {}, temp_root / "touhou")


def test_export_refuses_broken_script(temp_root):
    store.create_project("touhou")
    store.create_script("touhou", "cupa", "main", {"character": "cupa"})
    meta = {"character": "cupa"}
    files = {"main.story": [
        {"kind": "label", "data": {"name": "start"}},
        {"kind": "jump", "data": {"target": "nowhere"}},
    ]}
    result = compile_project(meta, files)
    assert result.errors
    with pytest.raises(ValueError):
        build_pack(meta, {"cupa/main": (meta, result)}, temp_root / "touhou")


def test_script_slug_is_character_and_script():
    assert script_slug("cupa", "main") == "cupa_main"
    assert script_slug("Hong Meiling", "Night Scene") == "hong_meiling_night_scene"


def test_export_script_name_single_vs_multi():
    from hikarin.exporter import export_script_name

    # Single-script character: bare character name.
    assert export_script_name("miku", "miku", multi=False) == "miku"
    assert export_script_name("Hong Meiling", "main", multi=False) == "hong_meiling"
    # Multi-script character: character-prefixed slug.
    assert export_script_name("miku", "main", multi=True) == "miku_main"
    assert export_script_name("miku", "night", multi=True) == "miku_night"


def test_story_filename_is_the_trigger():
    # Deprecated single-script fallback: character alone when no script given.
    assert story_filename({"character": "Cupa"}) == "cupa"
    assert story_filename({"character": "Hong Meiling"}) == "hong_meiling"
    # With a distinct script, it becomes <character>_<script>.
    assert story_filename({"character": "cupa"}, slug="night") == "cupa_night"


def test_export_filename_is_safe():
    assert export_filename({"packName": "Cupa's Story"}) == "cupa-s-story.zip"
    assert export_filename({"packName": "Touhou Pack"}) == "touhou-pack.zip"
    assert export_filename({}) == "pack.zip"


def test_bundle_roundtrip_keeps_every_script(pack, temp_root):
    from hikarin.exporter import build_project_bundle

    project = store.load_project(pack)
    bundle = build_project_bundle(project["meta"], _raw(pack), temp_root / pack)

    # Bundle is the one export that nests: stories/<character>/<script>/.
    with zipfile.ZipFile(io.BytesIO(bundle)) as zf:
        names = set(zf.namelist())
        assert "stories/cupa/main/story.json" in names
        assert "stories/reimu/main/story.json" in names

    imported = store.import_project_zip("imported", bundle)
    assert imported["slug"] == "imported"
    keys = {f'{s["character"]}/{s["script"]}' for s in imported["scripts"]}
    assert keys == {"cupa/main", "reimu/main"}, "both scripts survive the import"
    assert (temp_root / "imported" / "stories" / "cupa" / "main" / "main.story").is_file()
    assert (temp_root / "imported" / "stories" / "reimu" / "main" / "main.story").is_file()