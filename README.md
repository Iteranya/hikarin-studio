# Hikarin Studio

Visual editor for Hikarin visual novel scripts — the content pipeline for
**TLM: Visual Novel Framework** (a Touhou Little Maid fold).

Write a story as a stack of blocks across as many `.story` tabs as you want.
Validate it, and export a resource pack Minecraft will load.

## Run

```bash
uv sync
uv run main.py
```

Open **http://127.0.0.1:8411**

Requires Python 3.12+ and [uv](https://docs.astral.sh/uv/).

## The model

A project is a folder under `projects/`. The folder *is* the project — `git init`
it if you want version control.

```
projects/cupa/
  project.json     character, pack name, file order, start label
  main.story       the spine: night gate, achievement gate, idle fallback
  night.story
  idle.story       forty idle lines get their own tab
  items/
    endrod.story
  assets/
    cupa/happy.png         sprites, grouped by character folder
    room.png               backgrounds (flat)
    click.ogg
```

**Labels are global across files.** A Jump in `main.story` can target a label
defined in `night.story`. The compiler validates every reference and suggests a
correction on a typo (`go_nihgt` → `go_to_night`).

**Tab order does not matter.** The file containing `startLabel` is compiled
first, so you can reorganise tabs freely without changing execution order.

## The loop

1. Add blocks from the palette — 19 blocks across 5 families
2. Edit them in the inspector
3. **Validate** (Ctrl+Enter) — compile errors surface with the file name
4. **Save** (Ctrl+S) — writes `.story` files to disk
5. **Export** — a resource pack zip, ready for `resourcepacks/`

## Architecture

```
main.py             FastAPI: serves static/, project CRUD, compile, export
hikarin/blocks.py   block -> engine action mapping (the vocabulary)
hikarin/compiler.py many .story files -> one flat JSON
hikarin/projects.py folder storage, asset inventory
hikarin/exporter.py resource pack zip builder
static/             the editor (vanilla JS, no build step)
tests/              pytest
```

**Why a server:** compiling and zipping are filesystem work. Doing that in a
browser means either a Chromium-only file API or download-and-manually-unzip.
On the server it is `zipfile` from the standard library, and the same compiler
runs headlessly for CI.

## Format

`FORMAT.md` is ground truth on the shipped JSON: action vocabulary, scopes,
conditions, injected variables, and the spine pattern both the editor and the
Minecraft mod are built against.

`NOTES.md` records the wrinkles: conditionals store action ids while authors
type labels; and `label` means *jump target* in a choice but *speaker* in
dialogue.

## Test

```bash
uv run pytest -q
```

## Licence

AGPL-3.0, matching the original Hikarin framework.
