"""Resource management: schema coherence, VN variable sync, rmkit export."""

from __future__ import annotations

import io
import json
import zipfile

import pytest

from hikarin import resource_management as rm
from hikarin import variables as variable_store
from hikarin.rm_exporter import build_rmkit
from hikarin.rm_schema import ResourceManagementSchema, is_clean, validate_schema


def make_project(tmp_path) -> Path:
    """A bare project folder: project.json only."""
    project = tmp_path / "demo"
    project.mkdir()
    (project / "project.json").write_text(json.dumps({"packName": "Demo"}), encoding="utf-8")
    return project


def vn_resource(**overrides):
    res = {
        "id": "affection",
        "name": "Affection",
        "base_cap": 1000,
        "visible_to_vn": True,
        "description": "Fondness for the player",
    }
    res.update(overrides)
    return res


def test_load_missing_file_returns_empty_schema(tmp_path):
    project = make_project(tmp_path)
    schema = rm.load_rm(project)
    assert schema.resources == []
    assert schema.generators == []


def test_save_and_reload_roundtrip(tmp_path):
    project = make_project(tmp_path)
    schema = ResourceManagementSchema.model_validate(
        {"resources": [{"id": "gold", "name": "Gold", "base_cap": 5000}]}
    )
    rm.save_rm(project, schema)
    loaded = rm.load_rm(project)
    assert [r.id for r in loaded.resources] == ["gold"]
    assert loaded.resources[0].base_cap == 5000


def test_visible_resource_syncs_into_variables_registry(tmp_path):
    project = make_project(tmp_path)
    schema = ResourceManagementSchema.model_validate({"resources": [vn_resource()]})
    rm.save_rm(project, schema)

    names = variable_store.variable_names(project)
    assert "affection" in names

    raw = json.loads((project / "variables.json").read_text(encoding="utf-8"))
    rm_entries = [v for v in raw["variables"] if v.get("source") == "rm"]
    assert [v["name"] for v in rm_entries] == ["affection"]
    assert rm_entries[0]["type"] == "number"


def test_sync_preserves_manual_variables_and_drops_stale_rm_entries(tmp_path):
    project = make_project(tmp_path)
    variable_store.save_variables(
        project, [{"name": "boss_defeated", "type": "boolean", "description": "hand-written"}]
    )

    schema = ResourceManagementSchema.model_validate({"resources": [vn_resource()]})
    rm.save_rm(project, schema)

    raw = json.loads((project / "variables.json").read_text(encoding="utf-8"))
    by_name = {v["name"]: v for v in raw["variables"]}
    assert by_name["boss_defeated"].get("source") != "rm"
    assert by_name["affection"]["source"] == "rm"

    # Hide it from the VN: the rm-derived entry disappears, manual stays.
    schema2 = ResourceManagementSchema.model_validate(
        {"resources": [vn_resource(visible_to_vn=False)]}
    )
    rm.save_rm(project, schema2)
    raw = json.loads((project / "variables.json").read_text(encoding="utf-8"))
    names = {v["name"] for v in raw["variables"]}
    assert "affection" not in names
    assert "boss_defeated" in names


def test_vn_name_collision_with_manual_variable_refuses_save(tmp_path):
    project = make_project(tmp_path)
    variable_store.save_variables(project, [{"name": "affection", "type": "number"}])

    schema = ResourceManagementSchema.model_validate({"resources": [vn_resource()]})
    with pytest.raises(rm.ResourceManagementError):
        rm.save_rm(project, schema)

    # File untouched: no rm schema was written.
    assert not (project / "resource_management.json").exists()


def test_unknown_resource_in_generator_output_is_a_hard_error(tmp_path):
    project = make_project(tmp_path)
    schema = ResourceManagementSchema.model_validate(
        {
            "generators": [
                {
                    "id": "mine",
                    "name": "Mine",
                    "levels": [{"level": 1, "output": {"unobtanium": 10}}],
                }
            ]
        }
    )
    problems = validate_schema(schema)
    assert any("unobtanium" in p for p in problems)
    assert not is_clean(problems)
    with pytest.raises(rm.ResourceManagementError):
        rm.save_rm(project, schema)


def test_unreachable_tech_is_a_warning_not_a_blocker(tmp_path):
    project = make_project(tmp_path)
    schema = ResourceManagementSchema.model_validate(
        {
            "tech_nodes": [
                {"id": "genesis", "name": "Genesis"},
                {"id": "orphan_tech", "name": "Orphan", "requirements": [{"type": "custom", "data": {"key": "never"}}]},
            ]
        }
    )
    problems = validate_schema(schema)
    assert any("orphan_tech" in p and "(warning)" in p for p in problems)
    assert is_clean(problems)


def test_recipe_referencing_missing_resource_fails_validation(tmp_path):
    project = make_project(tmp_path)
    schema = ResourceManagementSchema.model_validate(
        {
            "resources": [{"id": "iron", "name": "Iron"}],
            "converters": [
                {
                    "id": "smelter",
                    "name": "Smelter",
                    "recipes": [
                        {"id": "smelt", "name": "Smelt", "inputs": {"iron": 10}, "outputs": {"steel": 5}}
                    ],
                }
            ],
        }
    )
    problems = validate_schema(schema)
    assert any("steel" in p for p in problems)


def test_rmkit_export_contains_schema_and_json_schema(tmp_path):
    project = make_project(tmp_path)
    schema = ResourceManagementSchema.model_validate(
        {"resources": [{"id": "gold", "name": "Gold"}]}
    )
    rm.save_rm(project, schema)

    payload = build_rmkit(project)
    zf = zipfile.ZipFile(io.BytesIO(payload))
    assert set(zf.namelist()) == {"resource_management.json", "schema.json", "README.md"}
    exported = json.loads(zf.read("resource_management.json"))
    assert exported["resources"][0]["id"] == "gold"
    json_schema = json.loads(zf.read("schema.json"))
    assert "resources" in json.dumps(json_schema)


def test_rmkit_export_refuses_broken_schema(tmp_path):
    project = make_project(tmp_path)
    (project / "resource_management.json").write_text(
        json.dumps(
            {
                "generators": [
                    {"id": "mine", "name": "Mine", "levels": [{"level": 1, "output": {"nope": 1}}]}
                ]
            }
        ),
        encoding="utf-8",
    )
    with pytest.raises(ValueError):
        build_rmkit(project)
