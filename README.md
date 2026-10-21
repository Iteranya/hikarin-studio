# Hikarin Studio

Visual editor for Hikarin visual novel scripts — the content pipeline for
**TLM: Visual Novel Framework** (a Touhou Little Maid fold).

Write a story as a stack of blocks across as many `.story` tabs as you want.
Validate it, and export a resource pack Minecraft will load.

## Run

```bash
uv sync
uv run serve.py
```

Open **http://127.0.0.1:8411** (override with `HIKARIN_PORT`).

`serve.py` runs uvicorn without the reloader: a single-process local tool gains
nothing from it, and the reloader's module cache can keep serving stale routes
after backend edits — which reads as "my change did not apply" and sends you
hunting in the wrong file.

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
5. **Play** — preview in the browser against simulated state
6. **Export** — a resource pack zip, ready for `resourcepacks/`

### Play

`play.html?project=cupa` runs the compiled script with the same compiler that
builds the export, so what you test is what ships.

The state panel is the point. A story routes on conditionals, and many of them
depend on state you cannot reach by walking the story — affection tiers,
achievements, time of day. Set a variable and watch the branch change:

```
affection unset (0)   -> less_than 10 passes  -> "Oh. It's you."
affection = 11        -> test fails, falls    -> "Master! You came back!"
```

Quick facts are derived from the script, not hardcoded. Each offers the value
that makes its test FAIL, because that is the branch you cannot reach normally.

**Day and night are not variables.** They are condition *types*:
`{"condition": "night"}` takes no variable, and the SDK writes a literal
placeholder (`"Nyaaa~"`) into the `var` slot because nothing reads it. Pick day
or night in the Test dropdown and the variable fields disappear, because there
is nothing to name.

**Scenes do not silently lose their variables.** Despite the name, `SCENE`
(bare names like `visits`) persists in the maid's NBT and survives the
conversation closing, matching the 2024 engine where `localVariables` were
saved per entity. A script that increments a bare counter across conversations
keeps counting.

**`next` is a real resume point.** It stores a label; the next time the scene
opens, the engine jumps there instead of starting from the top.

## Conditional semantics — read this before writing anything

The engine **continues when the test passes** and **jumps to `end` when it
fails**:

```json
{ "type": "conditional", "var": "isNight", "condition": "equal", "value": true, "end": 9 }
```

```
isNight == true   ->  carry on to the next block
isNight != true   ->  jump to id 9
```

So `end` is the **otherwise** branch, not the "then" branch. Write the passing
path inline and point the conditional at where to go when it fails. The studio
labels that field "Otherwise, jump to" for this reason — an earlier label of
"If true, jump to" inverted every gate that was built with it.

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
