"""Migrate flat stories/<slug>/ projects to nested stories/<character>/<script>/.

Old: stories/<slug>/story.json  (character field = the real character)
New: stories/<character>/<script>/story.json  (character field kept)

A flat slug becomes a script under the character it named. When two flat slugs
share a character (e.g. nyarla + nyarla-night), they become two scripts under
one nyarla/ folder.

Run: uv run python tools/migrate_nested.py
"""
from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from hikarin import projects as store

PROJECTS = ["minecraft", "touhou", "example_project"]


def migrate(slug: str) -> None:
    root = store.project_dir(slug)
    stories = root / "stories"
    if not stories.is_dir():
        print(f"  {slug}: no stories/, skip")
        return

    # Read every flat story first, then rebuild.
    flat = []  # (slug, character, folder)
    for entry in sorted(stories.iterdir()):
        if not entry.is_dir():
            continue
        manifest = entry / "story.json"
        if not manifest.is_file():
            continue
        meta = json.loads(manifest.read_text(encoding="utf-8"))
        character = meta.get("character") or entry.name
        flat.append((entry.name, character, entry))

    if not flat:
        print(f"  {slug}: no stories to migrate")
        return

    # Detect old vs new: a new project already has character folders whose
    # children hold story.json. Skip if already nested.
    already = any(
        (child / "story.json").is_file()
        for entry in stories.iterdir() if entry.is_dir()
        for child in entry.iterdir() if child.is_dir()
    )
    if already:
        print(f"  {slug}: already nested, skip")
        return

    tmp = stories.parent / "stories_new"
    for slug_name, character, folder in flat:
        dest = tmp / character / slug_name
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(folder, dest)
        # Ensure character field is set.
        mfile = dest / "story.json"
        meta = json.loads(mfile.read_text(encoding="utf-8"))
        meta["character"] = character
        mfile.write_text(
            json.dumps(meta, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        print(f"  {slug}: {slug_name} -> {character}/{slug_name}")

    shutil.rmtree(stories)
    tmp.rename(stories)


if __name__ == "__main__":
    targets = sys.argv[1:] or PROJECTS
    for slug in targets:
        try:
            migrate(slug)
        except Exception as e:
            print(f"  {slug}: ERROR {e}")