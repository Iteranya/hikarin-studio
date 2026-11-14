"""Convert old single-character .hikarin.zip bundles into one new-format project.

Old format: one zip = one character, with ``.story`` files at the root and a
``project.json`` describing a single script.

New format: one project (a pack) holds several stories, each in its own folder
with a ``story.json`` manifest.

Run:  uv run python tools/import_bundles.py
"""

from __future__ import annotations

import json
import shutil
import sys
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from hikarin import projects as store
from hikarin.variables import save_variables

DOWNLOADS = Path.home() / "Downloads"
PACK_SLUG = "touhou"
PACK_NAME = "Touhou Pack"

# The engine spells a shared variable "WORLD"; the studio says "GLOBAL". Stored
# blocks use the authoring word so the editor's Scope dropdown matches.
_SCOPE_FROM_OLD = {"WORLD": "GLOBAL", "MAID": "LOCAL", "SCENE": "LOCAL", "": "LOCAL"}


def read_bundle(path: Path) -> dict:
    zf = zipfile.ZipFile(path)
    meta = json.loads(zf.read("project.json"))
    files = {
        name: json.loads(zf.read(name))
        for name in meta.get("files") or []
        if name in zf.namelist()
    }
    return {"meta": meta, "files": files, "names": zf.namelist()}


def convert_scope(blocks: list[dict]) -> list[dict]:
    """Rewrite stored scope values into the studio's vocabulary."""
    out = []
    for block in blocks:
        data = block.get("data")
        if isinstance(data, dict) and "scope" in data:
            data = dict(data)
            data["scope"] = _SCOPE_FROM_OLD.get(
                str(data.get("scope") or "").upper(), "LOCAL"
            )
            block = {**block, "data": data}
        out.append(block)
    return out


def main() -> None:
    bundles = []
    for name in ("misha", "hestia"):
        path = DOWNLOADS / f"{name}.hikarin.zip"
        if not path.is_file():
            raise SystemExit(f"missing {path}")
        bundles.append((name, read_bundle(path)))

    # Start clean so a re-run is idempotent.
    root = store.PROJECTS_ROOT
    if (root / PACK_SLUG).exists():
        shutil.rmtree(root / PACK_SLUG)

    project = store.create_project(PACK_SLUG, {"packName": PACK_NAME})
    print(f"project: {project['slug']}")

    declared: dict[str, dict] = {}

    for name, bundle in bundles:
        meta = bundle["meta"]
        character = meta.get("character") or name

        story = store.create_story(PACK_SLUG, name, {"character": character})
        files = {
            fname: convert_scope(blocks) for fname, blocks in bundle["files"].items()
        }
        store.save_story(
            PACK_SLUG,
            name,
            {
                "character": character,
                "description": meta.get("description") or "",
                "startLabel": meta.get("startLabel") or "start",
                "files": list(files),
            },
            files,
        )

        # Seed the global registry from what the scripts actually use, so the
        # editor offers these names instead of asking to retype them.
        for blocks in files.values():
            for block in blocks:
                data = block.get("data") or {}
                var = data.get("var")
                if not var:
                    continue
                if str(data.get("scope") or "").upper() != "GLOBAL":
                    continue  # locals are not declared
                declared.setdefault(
                    var,
                    {
                        "name": var,
                        "type": "boolean" if data.get("value") in (True, False, "true", "false") else "number",
                        "description": "",
                    },
                )

        print(f"  story {name}: {len(files)} files, {sum(len(b) for b in files.values())} blocks")

    if declared:
        save_variables(store.project_dir(PACK_SLUG), list(declared.values()))
        print(f"globals declared: {sorted(declared)}")

    # Verify: every story must compile.
    for summary in store.load_project(PACK_SLUG)["stories"]:
        result = store.compile_slug(PACK_SLUG, summary["slug"])
        status = "ok" if result.ok else f"{len(result.errors)} ERRORS"
        print(f"  compile {summary['slug']}: {status}, {len(result.actions)} actions")
        for err in result.errors:
            print(f"      ! {err}")
        for warn in result.warnings:
            print(f"      ~ {warn}")


if __name__ == "__main__":
    main()