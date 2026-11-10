"""The asset manager's file operations.

Everything the window can do to a project's media folders, without a browser:
create characters and outfits, make folders, drop files, delete, and the guards
that keep a path from walking out of the project.
"""

from __future__ import annotations

import base64

import pytest

from hikarin import assets, projects as store


@pytest.fixture
def project(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "PROJECTS_ROOT", tmp_path)
    store.create_project("cupa")
    return tmp_path / "cupa"


# ── names ───────────────────────────────────────────────────────────────────

def test_clean_name_makes_a_texture_safe_filename():
    assert assets.clean_name("Happy.PNG") == "happy.png"
    # Spaces and punctuation become dashes; dots inside a stem are legal in a
    # resource location, so they stay.
    assert assets.clean_name("Screenshot 2024-01-01 at 12.00.00.png") == (
        "screenshot-2024-01-01-at-12.00.00.png"
    )
    # No usable stem left: still produces something addressable.
    assert assets.clean_name("!!!.png") == "file.png"


def test_rel_parts_refuses_escapes(project):
    with pytest.raises(assets.AssetError):
        assets.resolve(project, "../outside.png")
    with pytest.raises(assets.AssetError):
        assets.resolve(project, "project.json")
    assert assets.resolve(project, "images/asset/end.png").name == "end.png"


# ── characters ──────────────────────────────────────────────────────────────

def test_create_character_scaffolds_an_outfit_folder(project):
    created = assets.create_character(project, "Cupa")

    assert created["character"] == "cupa", "names are lowercased on the way in"
    assert created["outfit"] == "default"
    assert (project / created["dir"]).is_dir()

    char_dir = project / "images" / "characters" / "cupa"
    assert [p.name for p in char_dir.iterdir()] == ["default"]


def test_create_character_twice_is_an_error(project):
    assets.create_character(project, "cupa")
    with pytest.raises(assets.AssetError):
        assets.create_character(project, "cupa")


def test_create_outfit_needs_an_existing_character(project):
    with pytest.raises(assets.AssetError):
        assets.create_outfit(project, "nobody", "summer")

    assets.create_character(project, "cupa")
    created = assets.create_outfit(project, "cupa", "Summer")
    assert created["dir"] == "images/characters/cupa/summer"


def test_create_folder(project):
    created = assets.create_folder(project, "images/ui")
    assert created["dir"] == "images/ui"
    assert (project / "images" / "ui").is_dir()

    with pytest.raises(assets.AssetError):
        assets.create_folder(project, "sounds/extra")


# ── uploads ─────────────────────────────────────────────────────────────────

def test_write_uploads_cleans_names_and_reports_renames(project):
    written = assets.write_uploads(
        project,
        "images/characters/cupa/default",
        [("Very Happy.PNG", b"png-bytes"), ("very-happy.png", b"other")],
    )

    assert [w["name"] for w in written] == ["very-happy", "very-happy"]
    assert written[0]["renamedFrom"] == "Very Happy.PNG"
    assert written[0]["overwrote"] is False
    assert written[1]["overwrote"] is True, "second write replaces the first"
    assert (project / "images/characters/cupa/default/very-happy.png").read_bytes() == b"other"


def test_write_uploads_refuses_wrong_extension(project):
    with pytest.raises(assets.AssetError):
        assets.write_uploads(project, "images/asset", [("notes.txt", b"hello")])


def test_upload_lands_in_the_inventory(project):
    assets.create_character(project, "cupa")
    assets.write_uploads(project, "images/characters/cupa/default", [("Happy.png", b"x")])

    inventory = assets.inventory(project)
    assert inventory["characters"]["cupa"]["default"] == ["happy"]
    assert inventory["characterTree"][0]["outfits"][0]["images"][0]["filename"] == "happy.png"


def test_decode_upload_accepts_a_data_url():
    blob = base64.b64encode(b"hi").decode()
    assert assets.decode_upload(f"data:image/png;base64,{blob}") == b"hi"
    assert assets.decode_upload(blob) == b"hi"


# ── delete ──────────────────────────────────────────────────────────────────

def test_delete_file_and_folder(project):
    assets.write_uploads(project, "images/asset", [("end.png", b"x")])
    assert assets.delete_path(project, "images/asset/end.png")["kind"] == "file"
    assert not (project / "images" / "asset" / "end.png").exists()

    assets.create_character(project, "cupa")
    assert assets.delete_path(project, "images/characters/cupa")["kind"] == "folder"
    assert inventory_characters(project) == []


def inventory_characters(project):
    return assets.inventory(project)["characterTree"]


def test_delete_refuses_the_scaffold(project):
    for protected in ("images", "images/characters", "sounds/music"):
        with pytest.raises(assets.AssetError):
            assets.delete_path(project, protected)
    assert (project / "images" / "characters").is_dir()


def test_delete_missing_file_is_an_error(project):
    with pytest.raises(assets.AssetError):
        assets.delete_path(project, "images/asset/ghost.png")
