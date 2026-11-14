# Hikarin Studio

Visual editor for Hikarin visual novel scripts — the content pipeline for
**TLM: Visual Novel Framework** (a Touhou Little Maid fold).

Write a story as a stack of blocks across as many `.story` tabs as you want.
Validate it, and export a resource pack the runtime will load.

## Run

```bash
uv sync
uv run serve.py
```

Open **http://127.0.0.1:8411** (override with `HIKARIN_PORT`). That lands on the
project manager — with no projects yet it says so and offers **New project**,
rather than dropping you into an empty editor.

`serve.py` runs uvicorn without the reloader: a single-process local tool gains
nothing from it, and the reloader's module cache can keep serving stale routes
after backend edits — which reads as "my change did not apply" and sends you
hunting in the wrong file.

Requires Python 3.12+ and [uv](https://docs.astral.sh/uv/).

## The model

Three levels, and the difference matters:

```
projects/<project>/          a project = one resource pack
  project.json               pack name, pack format, description
  stories/
    <story>/                 a story = one character's script
      story.json             character (the trigger), start label, file order
      main.story             the spine: night gate, achievement gate, idle fallback
      night.story
      idle.story             forty idle lines get their own tab
  images/                    shared by every story in the pack
    pack.png                 the resource pack icon
    characters/cupa/default/happy.png
    asset/room.png
  sounds/
    music/haggstrom.ogg
    sound/click.ogg
```

A **project** is what the runtime installs. A **story** is one character inside it. A
project with one story and a project with six are the same shape — adding a story
must not mean restructuring anything. Each story compiles to its own
`assets/hikarin/<character>.json`, which is exactly what the engine reads.

**Art is shared.** `images/` and `sounds/` belong to the project, so two stories
in one pack use the same sprites without duplicating files.

Labels are scoped to a story. A Jump in `main.story` can target a label
defined in `night.story`; it can never reach into another story's script. The
compiler validates every reference and suggests a correction on a typo
(`go_nihgt` → `go_to_night`).

**Two scopes, and only one of them is declared.**

| scope | what it is | how you name it |
|---|---|---|
| **Local** (default) | working state inside one story — a counter, a scratch flag | typed straight into the block |
| **Global** | shared by every story in the pack | picked from the manager's **Variables** tab |

A local compiles to a bare name with no scope key. A global compiles to
`"scope": "WORLD"` — the studio says GLOBAL and `hikarin.blocks` translates, so the
engine gets the string it reads. Either way a global is declared once in the
manager, which is what stops it ending up spelled three ways across four stories
(the failure a conditional reading `affection` while another block writes
`affection.cupa` produces, silently, because the engine treats them as different
variables).

Declaring is a convenience for the editor, not state the engine reads: a story
that uses an undeclared global still compiles, and removing a declaration never
touches the blocks that reference it.

**Tab order does not matter.** The file containing `startLabel` is compiled
first, so you can reorganise tabs freely without changing execution order.

## Projects and stories

`http://127.0.0.1:8411/` **is** the launcher — it redirects to `/manager`, which
is the front door. It lists projects, shows the stories inside one, and is the
only place projects and stories are created, renamed, duplicated or deleted.
Opening a story hands off to the editor.

The editor lives at `/editor` and edits exactly one story —
`/editor?project=<project>&story=<story>` — so a reload returns to the same place
and a story can be linked to. Opened with no story it says so and links back to
the manager, rather than showing a blank page.

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
(bare names like `visits`) persists in the story's NBT and survives the
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
main.py             FastAPI: serves static/, project+story CRUD, compile, export
hikarin/blocks.py   block -> engine action mapping (the vocabulary)
hikarin/compiler.py many .story files -> one flat JSON (per story)
hikarin/projects.py folder storage: projects contain stories
hikarin/exporter.py resource pack zip builder (one JSON per story)
static/manager.*    the launcher: projects, stories, assets, and variables
static/assets.js    the asset window (mounted by whichever page needs it)
hikarin/variables.py  the shared variable registry
static/             the editor (vanilla JS, no build step)
tests/              pytest
```

`hikarin/compiler.py` never learned about projects or stories, and should not:
it takes a meta dict and a `{file: blocks}` dict, which is exactly one story.
That is why the three-level model cost so little — the compiler already had the
right shape for the innermost level.

**Why a server:** compiling and zipping are filesystem work. Doing that in a
browser means either a Chromium-only file API or download-and-manually-unzip.
On the server it is `zipfile` from the standard library, and the same compiler
runs headlessly for CI.

## Format

`FORMAT.md` is ground truth on the shipped JSON: action vocabulary, scopes,
conditions, injected variables, and the spine pattern both the editor and the
runtime are built against.

`NOTES.md` records the wrinkles: conditionals store action ids while authors
type labels; and `label` means *jump target* in a choice but *speaker* in
dialogue.


## Project management

The **manager** (`/manager`) is where structure changes. The editor deliberately
cannot create, rename or delete anything — structure edits belong somewhere you
can see the whole pack, not in a dropdown in the corner of a text editor.

Per project: **assets** (characters, images, audio), **global variables**, rename
(title, description), duplicate, delete, export the pack.

Assets belong to the project, not to a story — a pack's `images/` and `sounds/`
are shared by every story in it. So they are managed here, in the manager, and
not from inside a story. The editor still reads them (every sprite and background
picker is built from the project's inventory), it just does not own them.

Per story: create, open, rename, duplicate, delete. Deleting a story leaves the
shared `images/` and `sounds/` alone, because the art belongs to the pack.

API:

```
GET    /api/projects                              list, with story counts
POST   /api/projects                              create a pack
GET    /api/projects/{slug}                       pack + its stories
PUT    /api/projects/{slug}                       pack metadata
DELETE /api/projects/{slug}
POST   /api/projects/{slug}/duplicate             {"new_slug": "..."}
POST   /api/projects/{slug}/rename                {"new_slug": "..."}
POST   /api/projects/import-zip?slug=...          (body: .hikarin.zip)

GET    /api/projects/{slug}/variables             declared global variables
PUT    /api/projects/{slug}/variables             replace them (validated first)

GET    /api/projects/{slug}/stories               list stories
POST   /api/projects/{slug}/stories               {"slug": "...", "meta": {...}}
GET    /api/projects/{slug}/stories/{story}       story + blocks + assets
PUT    /api/projects/{slug}/stories/{story}       save blocks
DELETE /api/projects/{slug}/stories/{story}
POST   /api/projects/{slug}/stories/{story}/duplicate
POST   /api/projects/{slug}/stories/{story}/rename
```

## Export formats

`GET /api/projects/{slug}/export?format=...`

The pack export is project-level: it compiles every story and writes one JSON
per story.

```
GET /api/projects/{slug}/export?format=pack     # default
GET /api/projects/{slug}/export?format=bundle
```

| format | output |
|---|---|
| `pack` | Resource pack `.zip` — every story, one JSON per story |
| `bundle` | Project bundle `.hikarin.zip`, re-importable, carries blocks not actions |

The resource pack version is an export option, not a property of the project —
the same scripts can be built for several runtime versions. Pass it on the
export call; it defaults to 15 (1.20.1).

```
GET /api/projects/{slug}/export?format=pack&pack_format=15
```

A single story exports on its own, which is what the editor's Export button does:

```
GET /api/projects/{slug}/stories/{story}/export?format=json   # default
GET /api/projects/{slug}/stories/{story}/export?format=txt
GET /api/projects/{slug}/stories/{story}/export?format=md
```

## Test

```bash
uv run pytest -q
```

## Licence

AGPL-3.0, matching the original Hikarin framework.
