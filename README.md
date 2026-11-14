# Hikarin Studio

A visual editor for branching dialogue scripts.

You write a scene as a stack of blocks — someone speaks, a sprite appears, a
choice is offered, a flag is set — and the studio compiles it into the flat JSON
a visual novel runtime loads. No scripting language, no line numbers, no
hand-written ids: every reference is a label name, so you can reorder freely and
the compiler resolves it.

It is a content pipeline, not a game engine. It does not run the story; it
produces the files something else runs. That something else is a resource pack
loader: a pack is a folder of compiled scripts plus the art they reference, which
is what the studio exports.

```
blocks in the editor  ->  compile  ->  one JSON per character  ->  resource pack
```

Because a pack can hold several characters, a project holds several stories, and
the art is shared between them. More on that below.

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
  project.json               pack name, description
  variables.json             declared global variables
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

A **project** is what the runtime installs. A **story** is one character inside
it. A project with one story and a project with six are the same shape — adding
a story must not mean restructuring anything. Each story compiles to its own
`assets/hikarin/<character>.json`, which is exactly what the engine reads.

**Art is shared.** `images/` and `sounds/` belong to the project, so two stories
in one pack use the same sprites without duplicating files.

Labels are scoped to a story. A Jump in `main.story` can target a label defined
in `night.story`; it can never reach into another story's script. The compiler
validates every reference and suggests a correction on a typo
(`go_nihgt` → `go_to_night`).

**Tab order does not matter.** The file containing `startLabel` is compiled
first, so you can reorganise tabs freely without changing execution order.

## Variables: two scopes, one of them declared

| scope | what it is | how you name it |
|---|---|---|
| **Local** (default) | working state inside one story — a counter, a scratch flag | typed straight into the block |
| **Global** | shared by every story in the pack | picked from the manager's **Variables** tab |

A local compiles to a bare name with no scope key. A global compiles to
`"scope": "WORLD"` — the studio says GLOBAL and `hikarin.blocks` translates, so
the engine gets the string it reads. A global is declared once in the manager,
which is what stops one flag ending up spelled three ways across four stories
(the failure a conditional reading `affection` while another block writes
`affection.cupa` produces, silently, because the engine treats them as different
variables).

Declaring is a convenience for the editor, not state the engine reads: a story
that uses an undeclared global still compiles, and removing a declaration never
touches the blocks that reference it.

## Projects and stories

`http://127.0.0.1:8411/` **is** the launcher — it redirects to `/manager`, the
front door. It lists projects, shows the stories inside one, and is the only
place projects and stories are created, renamed, duplicated or deleted. Opening
a story hands off to the editor.

The editor lives at `/editor` and edits exactly one story —
`/editor?project=<project>&story=<story>` — so a reload returns to the same place
and a story can be linked to. Opened with no story it says so and links back to
the manager, rather than showing a blank page.

Per project: **assets** (characters, images, audio), **global variables**, rename,
duplicate, delete, export.

Per story: create, open, rename, duplicate, delete. Deleting a story leaves the
shared `images/` and `sounds/` alone, because the art belongs to the pack.

The editor deliberately cannot create, rename or delete anything — structure
edits belong somewhere you can see the whole pack, not in a dropdown in the
corner of a text editor.

**Assets are project-level.** A pack's `images/` and `sounds/` are shared by
every story in it, so they are managed in the manager. The editor still reads
them (every sprite and background picker is built from the project's inventory),
it just does not own them.

## The loop

1. Add blocks from the palette — 21 blocks across 5 families
2. Edit them in the inspector
3. **Validate** (Ctrl+Enter) — compile errors surface with the file name
4. **Save** (Ctrl+S) — writes `.story` files to disk
5. **Play** — preview in the browser against simulated state
6. **Export** — pick a format, then export

Save is automatic: an edit marks the story dirty, and a write-behind timer
flushes it. Ctrl+S still works and flushes immediately. Switching stories flushes
the one you are leaving first, so an edit inside the debounce window cannot be
lost.

### Play

`play.html?project=<project>&story=<story>` runs the compiled script with the
same compiler that builds the export, so what you test is what ships.

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

## Export

Export is a dialog, not a button: the format and its options are choices, and a
one-click export makes them silently. The pack format version in particular
belongs to the format you picked, not in the header of every project.

The menu is drawn from `hikarin/export_formats.py` — a registry, not a list in
the UI. An entry declares its own id, label, extension, scope, hint and
parameters, and the manager draws the options and their inputs from it:

```python
{
    "id": "pack",
    "label": "Resource pack",
    "extension": ".zip",
    "scope": "project",          # or "story"
    "hint": "What the runtime loads…",
    "params": [
        {"key": "pack_format", "label": "Format version",
         "type": "number", "default": 15, "hint": "…"}
    ],
}
```

Adding a format means adding an entry there. Param types are `number`, `text`
and `select`, so a format needing a name, a target or a variant needs no new UI
code. `main.py` maps an id to a builder; the registry knows how to *describe* a
format, never how to build one.

| scope | id | output |
|---|---|---|
| project | `pack` | Resource pack `.zip` — every story, one JSON each, plus shared textures and sounds |
| project | `bundle` | Project bundle `.hikarin.zip` — re-importable, carries blocks not actions |
| story | `json` | Compiled actions for one story |
| story | `txt` | Plain-text script |
| story | `md` | Markdown script, labels as `##` headings |

API:

```
GET /api/projects/{slug}/export?format=pack&pack_format=15
GET /api/projects/{slug}/export?format=bundle
GET /api/projects/{slug}/stories/{story}/export?format=json
GET /api/projects/{slug}/stories/{story}/export?format=txt
GET /api/projects/{slug}/stories/{story}/export?format=md
```

`GET /api/meta` returns the registry, so a client can build the same menu.

**A pack and a bundle are both `.zip`.** A pack is what the game loads
(`pack.mcmeta` and `assets/`); a bundle is what this tool re-imports
(`project.json` and `stories/`). Importing a pack explains the difference
rather than reporting a corrupt file.

The resource pack version is an export option, not project state — the same
scripts build for several runtime versions.

## Architecture

```
main.py                    FastAPI: serves static/, project+story CRUD, compile, export
hikarin/blocks.py          block -> engine action mapping (the vocabulary)
hikarin/compiler.py        many .story files -> one flat JSON (per story)
hikarin/projects.py        folder storage: projects contain stories
hikarin/exporter.py        resource pack zip builder (one JSON per story)
hikarin/variables.py       the shared global variable registry
hikarin/export_formats.py  the export registry (what can be built, as data)
static/manager.*           the launcher: projects, stories, assets, variables, export
static/assets.js           the asset window (mounted by whichever page needs it)
static/                    the editor (vanilla JS, no build step)
tests/                     pytest
tools/                     one-off migration scripts
```

`hikarin/compiler.py` never learned about projects or stories, and should not:
it takes a meta dict and a `{file: blocks}` dict, which is exactly one story.
That is why the three-level model cost so little — the compiler already had the
right shape for the innermost level.

**Why a server:** compiling and zipping are filesystem work. Doing that in a
browser means either a Chromium-only file API or download-and-manually-unzip.
On the server it is `zipfile` from the standard library, and the same compiler
runs headlessly for CI.

**Why no build step:** the editor is vanilla JS served as files. Editing a
`.js` and reloading is the whole development loop, and `main.py` sends
`no-store` so a change cannot hide behind a cached response.

## Format

`FORMAT.md` is ground truth on the shipped JSON: action vocabulary, scopes,
conditions, injected variables, and the spine pattern both the editor and the
runtime are built against.

`NOTES.md` records the wrinkles: conditionals store action ids while authors
type labels; and `label` means *jump target* in a choice but *speaker* in
dialogue.

## API

```
GET    /api/meta                                  blocks, conditions, export registry
GET    /api/projects                              list, with story lists
POST   /api/projects                              create a pack
GET    /api/projects/{slug}                       pack + its stories
PUT    /api/projects/{slug}                       pack metadata
DELETE /api/projects/{slug}
POST   /api/projects/{slug}/duplicate             {"new_slug": "..."}
POST   /api/projects/{slug}/rename                {"new_slug": "..."}
POST   /api/projects/import-zip?slug=...          (body: .hikarin.zip bundle)

GET    /api/projects/{slug}/variables             declared global variables
PUT    /api/projects/{slug}/variables             replace them (validated first)

GET    /api/projects/{slug}/stories               list stories
POST   /api/projects/{slug}/stories               {"slug": "...", "meta": {...}}
GET    /api/projects/{slug}/stories/{story}       story + blocks + assets + variables
PUT    /api/projects/{slug}/stories/{story}       save blocks
DELETE /api/projects/{slug}/stories/{story}
POST   /api/projects/{slug}/stories/{story}/duplicate
POST   /api/projects/{slug}/stories/{story}/rename

GET    /api/projects/{slug}/stories/{story}/compile   validate
GET    /api/projects/{slug}/stories/{story}/play      compiled actions for preview
GET    /api/projects/{slug}/stories/{story}/export    json | txt | md

GET    /api/projects/{slug}/asset-list            the media inventory
POST   /api/projects/{slug}/assets/character      {"character": "...", "outfit": "..."}
POST   /api/projects/{slug}/assets/outfit         {"character": "...", "outfit": "..."}
POST   /api/projects/{slug}/assets/folder         {"path": "images/asset"}
POST   /api/projects/{slug}/assets/upload         {"dir": "...", "files": [...]}
DELETE /api/projects/{slug}/assets?path=...
GET    /api/projects/{slug}/assets/{path}         serve one media file
```

Assets are project-level, so every asset route hangs off the project rather than
a story. Each mutation returns the fresh inventory, so the asset window
re-renders from one source of truth instead of patching its own copy.

## Test

```bash
uv run pytest -q
```

## Licence

AGPL-3.0, matching the original Hikarin framework.