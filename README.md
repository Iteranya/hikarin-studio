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

## Why this exists

Oh god, finally, it's finished...

Anyway, hats off to Nvidia, Thinking Machine, and Baidu for the free AI tokens

God this thing is complex and really hard to make.

BUT ANYWAY, so, so, the whole point of this mess is simple:

I work from Monday to Saturday, and my day off is Wednesday and Sunday

One work day is 9 hours a day and commute takes 4 hours, do the math.

Now, with this kind of time, how do I achieve my hobby as a game developer???

THAT'S RIGHT BY MAKING A GAME ENGINE THAT RUNS ON MY PHONE!!!

Well, it's not exactly a game engine, don't get me wrong, it requires a 3rd Party runtime. BUT, if I just wanna write a VN or scripts or story line for a game???

Hikarin is the answer~

...

Okay it still requires a VPS, so this solution hyper-specific to my situation, sue me.

BUT, I did it, and with the help of AI.

Oh slop you say? Yeah I did the math, the math says I don't have enough time for what a puritan considers proper game development. I'd rather have AI slop than *nothing*. Not every one of us has the luxury of time to follow our passion, *Sue me I dare you, I double dare you mf (my friend), sue me*

Anyway, Hikarin is designed to be pure data and extremely modular. I want to make it a content pipeline for all interaction and VN-like cutscene in all my game. So all my game will be *extremely* data driven. Think DIY-ing my own RPG Maker.

(Now that I think about it, RPG Maker works kinda like this, hmmmmm... Eh, is fine)

But yeah, that's... that's the whole thing.

Anyway, about the game, here's a technical readme written by Viel

you might remember viel? Yeah, same girl, from https://github.com/Iteranya/viel-ai

Anyway, Viel, your turn

## What this actually is, technically

Alright, my turn.

Hikarin Studio is a small local web app. FastAPI on the back, vanilla JS on the
front, no build step, no database, no accounts. A project is a folder on disk and
the editor is static files. That is the whole deployment story.

The important architectural fact is the one that made the rest cheap: **the
compiler never learned about projects.** It takes a meta dict and a
`{file: blocks}` dict, and that is exactly one story's worth of data. When the
model grew a level, the compiler did not notice.

## Run it

```bash
uv sync
uv run serve.py
```

Open **http://127.0.0.1:8411** (override with `HIKARIN_PORT`). You land on the
project manager, not the editor. With no projects yet it says so and offers
**New project**, which is the correct first screen — an empty editor explains
nothing and looks broken.

Requires Python 3.12+ and [uv](https://docs.astral.sh/uv/).

`serve.py` runs uvicorn without the reloader. That is deliberate: the reloader's
module cache can keep serving stale routes after a backend edit, which reads as
"my change did not apply" and sends you hunting through the wrong file. For a
single-process local tool the reloader buys nothing and costs you an afternoon
once a month.

## The model

Three levels. The distinction is the design.

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
it. One story and six stories are the same shape, which is the point: adding a
maid must never mean restructuring anything.

Each story compiles to its own `assets/hikarin/<character>.json`. That is exactly
what the engine loads, so the export is not a translation of the model — it is
the model.

**Art is shared.** `images/` and `sounds/` belong to the project. Two stories in
one pack use the same sprites without duplicating files.

**Labels are scoped to a story.** A Jump in `main.story` can target a label in
`night.story`; it cannot reach into another maid's script. The compiler checks
every reference and offers a correction on a typo (`go_nihgt` → `go_to_night`).

**Tab order does not matter.** The file holding `startLabel` compiles first, so
you can reorganise tabs without changing execution order.

## Variables: two scopes, one of them declared

| scope | what it is | how you name it |
|---|---|---|
| **Local** (default) | working state inside one story — a counter, a scratch flag | typed straight into the block |
| **Global** | shared by every story in the pack | picked from the manager's **Variables** tab |

That is the whole model. The engine has four scopes and they differ in which NBT
compound a value lands in, which is not a distinction an author needs to make
while writing a joke about a maid. Two is what changes how you write.

A local compiles to a bare name with no scope key. A global compiles to
`"scope": "WORLD"` — the studio says GLOBAL and `hikarin.blocks` translates on
the way out, because that string is what the mod reads. The translation lives in
one table in one module. Do not "fix" it by renaming the output.

A global is declared once in the manager. That is what stops one flag ending up
spelled three ways across four stories — the failure where a conditional reads
`affection` while another block writes `affection.cupa`, silently, because the
engine treats those as different variables.

Declaring is a convenience for the editor, not state the engine reads. A story
using an undeclared global still compiles. Removing a declaration never touches
the blocks that reference it.

## Projects and stories

`/manager` is the front door. It lists projects, shows the stories inside one,
and is the only place structure changes: create, rename, duplicate, delete.

The editor lives at `/editor?project=<project>&story=<story>`. It edits exactly
one story, so a reload returns to the same place and a story can be linked to.
Opened with nothing it says so and points back at the manager rather than showing
a blank page.

**The editor cannot create, rename or delete anything.** Structure edits belong
where you can see the whole pack. A dropdown in the corner of a text editor is
where "project" starts meaning three different things.

**Assets are project-level.** A pack's `images/` and `sounds/` are shared, so
they are managed in the manager. The editor still reads them — every sprite and
background picker is built from the project's inventory — it just does not own
them.

## The loop

1. Add blocks from the palette — 21 blocks across 5 families
2. Edit them in the inspector
3. **Validate** (Ctrl+Enter) — errors surface with the file name
4. **Save** (Ctrl+S) — writes `.story` files to disk
5. **Play** — preview in the browser against simulated state
6. **Export** — pick a format, then export

Save is automatic. An edit marks the story dirty and starts a write-behind
timer; Ctrl+S flushes immediately. Two rules keep it honest: one PUT at a time,
so two overlapping writes cannot undo each other, and a save is flushed before
anything reads the files from disk — so switching stories cannot lose the last
second of typing.

### Play

`play.html?project=<project>&story=<story>` runs the compiled script through the
same compiler that builds the export, so what you test is what ships.

The state panel is the point. A story routes on conditionals, and many depend on
state you cannot reach by walking it — affection tiers, achievements, time of
day. Set a variable, watch the branch change:

```
affection unset (0)   -> less_than 10 passes  -> "Oh. It's you."
affection = 11        -> test fails, falls    -> "Master! You came back!"
```

Quick facts are derived from the script, not hardcoded. Each offers the value
that makes its test FAIL, because that is the branch you cannot reach normally.

**Day and night are not variables.** They are condition *types*:
`{"condition": "night"}` takes no variable, and the SDK writes a literal
placeholder (`"Nyaaa~"`) into the `var` slot because nothing reads it. Pick day or
night in the Test dropdown and the variable fields disappear, because there is
nothing to name.

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
"If true, jump to" inverted every gate built with it.

## Export

Export is a dialog, not a button. The format and its options are choices, and a
one-click export makes them silently — which is how a resource pack gets exported
and then imported as a project bundle.

The menu is drawn from `hikarin/export_formats.py`, which is data, not UI:

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

**A pack and a bundle are both `.zip`.** A pack is what the game loads
(`pack.mcmeta` and `assets/`); a bundle is what this tool re-imports
(`project.json` and `stories/`). Importing a pack explains that difference rather
than reporting a corrupt file.

The resource pack version is an export option, not project state. The same
scripts build for several runtime versions.

## Architecture

```
main.py                    FastAPI: static/, project+story CRUD, compile, export
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

**Why a server.** Compiling and zipping are filesystem work. Doing that in a
browser means either a Chromium-only file API or download-and-manually-unzip. On
the server it is `zipfile` from the standard library, and the same compiler runs
headlessly for CI.

**Why no build step.** Editing a `.js` and reloading is the whole development
loop. `main.py` sends `no-store` on every static response, because a cached
response makes an edit look like it did nothing — which has already sent me
hunting through the wrong file twice.

**Why SQLite-free.** There is no database. A project is a folder; `git init` it
if you want version control. The filesystem is already a database with worse
query performance and better debugging.

## Format

`FORMAT.md` is ground truth on the shipped JSON: action vocabulary, scopes,
conditions, injected variables, and the spine pattern both the editor and the
runtime are built against.

`NOTES.md` records the wrinkles: conditionals store action ids while authors type
labels; and `label` means *jump target* in a choice but *speaker* in dialogue.

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
a story. Each mutation returns the fresh inventory, so the asset window re-renders
from one source of truth instead of patching its own copy and hoping.

## Known sharp edges

Things that will bite you, written down so they only bite once:

- **`hidden` loses to `display: flex`.** The browser's `[hidden] { display: none }`
  is a UA rule; any author `display` beats it. Fixed three separate times in this
  project. If a pane will not hide, that is why — the fix is
  `.thing[hidden] { display: none; }`, not `!important` on the show rule.
- **A variable named `current` shadows `current()`.** The temporal dead zone turns
  the next call into a crash, and the field renders blank with no visible error.
  Name it `value`.
- **A rename must not rewrite blocks.** Renaming a story moves a folder; sending
  it through the save endpoint re-uploads every file. They are different
  operations and share no code.
- **A local variable is a bare name, and `scope: ""` is not the same thing.** An
  empty scope key still emits a key. Emit nothing at all.

## Test

```bash
uv run pytest -q
```

125 tests, real files in a temp directory, no mocks of the filesystem.

## Licence

AGPL-3.0, matching the original Hikarin framework.