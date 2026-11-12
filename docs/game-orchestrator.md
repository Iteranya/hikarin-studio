# Game Orchestrator — Design (Layer 1)

**Status:** Decision stage. No code. This document is the bridge between
**hikarin studio** (where the game is authored) and **any runtime** (Godot
incl., but nothing about this document assumes it). Read that sentence again —
when it says "universal", it means it.

**Working title:** `game-orchestrator`. **Intent:** hikarin is the dialogue
engine; the orchestrator is the world around it. The bullet-hell cartridge, the
VN cartridge, every next genre — all run on this one layer.

---

## 1. The three layers, restated

```
[ event scripts ]     ← hikarin, one compiled JSON per event (hestia.json-style),
                        no awareness of maps, triggers, or engines
[ Game Orchestrator ] ← ONE compiled JSON (game.json): the world graph,
                        entry, gates, trigger dispatch, endings
[ runtime (Godot) ]   ← render grid, move avatar, detect interact, run scripts,
                        persist profile
```

**Orchestrator does not reference `.story` sources.** It references compiled
*events* by slug — `hestia`, `stinger_wave`, `ending_credits` — and nothing
else. The events are treated as finished artifacts. This is the same rule
Godot uses: it knows JSON, it does not know hikarin.

**Events never reference the orchestrator.** They exit to the router by
returning (`finish_dialogue`), with any flags already written via hikarin's
own `modify_global`. The router is re-entered from its current resume label.

## 2. Project layout (hikarin-studio game project)

```
projects/my-game/
  project.json          { kind: "game", packName, events: [...], start: "start", ... }
  world/                ← the orchestrator, composed of .orch files, like .story compiles
    map.orch            ← map definitions, zones, gates
    script.orch         ← the runtime action list
    entities.orch       ← spawns/markers/interacts
  events/               ← nested hikarin projects — one playable script each
    hestia/
      project.json      { kind: "story", character: "hestia", files: [...], startLabel: "start" }
      main.story
      ...
    stinger_wave/
      main.story
  images/               shared assets (tiles, sprites, backgrounds)
  sounds/               shared sounds
  build/                ← export output, gitignored
    game.json
    events/hestia.json
    events/stinger_wave.json
    images/…            (copied verbatim)
    sounds/…
```

**Shared assets at root, scripts isolated per event.** Events may render other
events' sprites — asset resolution is always relative to the shared tree.

**One project = one orchestrator.** Project compile produces ONE `game.json`
plus one JSON per event — never merged into a single file, never split
differently.

## 3. `game.json` — compiled shape

```json
{
  "meta":   { "packName": "my-game", "version": 1, "start": "start" },
  "maps":   { "home": { … }, "wastes": { … } },
  "script": [ … actions ]
}
```

Three sections, re-read every load. `meta` carries the start *label* — the
resume router hikarin already uses — so the game always re-enters the
orchestrator the way it left.

### 3.1 Tiles as data, not code

```json
{
  "maps": {
    "home": {
      "cols": 16, "rows": 16,
      "tiles": [ "grassstone", "grassstone", "wall.a", "wall.b", … ],
      "palette": {
        "grassstone": { "image": "images/asset/grass_stone.png", "traversable": true  },
        "wall.a":     { "image": "images/asset/wall_a.png",     "traversable": false }
      }
    }
  }
}
```

Collision lives on the **tile type**, not per placement — editing `wall.a`
flips every wall in every map. Tile traversability is the *entire* surface
model: **a cell is either traversable or it is not. Nothing else.** No tile
metadata beyond `image` and `traversable`. **Non-goal:** zones are out. Every gate is expressed as a `conditional`
inside the spine, or a static requirement on an entity. The map has no area
vocabulary of its own.

## 4. Universal verbs — the wholly separate set

The orchestrator **does not inherit hikarin's vocabulary**. It shares only the
*structural* ideas (labels, conditions, sequential ids, composed files), never
the noun-set. There is no `dialogue`, no `show_sprite`, no `command`.

| verb | required fields | reads / writes | notes |
|---|---|---|---|
| `meta` | `action`: `start` | — | anchors the file; the resume router label |
| `label` | `label` | — | jump target, exactly as in hikarin |
| `jump` | `label` | — | unconditional transfer; ping-pongs are compile errors |
| `conditional` | `condition`, `var`, `value`, `end` | `@world.*` only | same grammar as hikarin; **route selector only** — chooses *which script should run*, never *whether access is granted*; blocking lives inside the event's spine |
| `map` | `action`: `load`, `map`, `x`, `y` | world state | player-teleport; the only way a map changes; optional `facing` on the map def, default `down` |
| `entity` | `action`: `begin`, `entity` | world state | "interact with entity `entity` in current map" — sets up the event handoff |
| `run_event` | `event` (slug) | — | call a compiled event, block the orchestrator until it returns |
| `on_event_end` | `event`, `label` | — | landing point after `run_event`; one per (event, end) call-site |
| `set_world` | `var`, `value` | `@world.*` write | orchestrator's only world mutation channel; forbidden in events |
| `save` | — | profile | force-persist now; otherwise autosave on map change and event completion |
| `ending` | — | — | terminal; runtime stops; no implicit quit |

**`run_event` is the only engine ↔ hikarin crossing.** The orchestrator calls
an event; hikarin runs its full spine; `finish_dialogue` returns control; the
orchestrator resumes at its `on_event_end` label. Nothing else crosses.

**Gate ownership, settled: blocking decision lives inside the script.**
The three layers never substitute for each other:

| Gate | Owner | Semantics | What it does NOT do |
|---|---|---|---|
| `visible_if` / `interact_if` on an entity | **Orchestrator** | World-level presence — does the block exist/click now? Falls back gracefully: hidden → nothing to press | Grants or denies *story* access |
| `conditional` in orchestrator spine | **Orchestrator** | **Route selector only** — picks which event to dispatch (`start → A` vs `start → B`) by hkarin-grammar world-fact test | Blocking (story refuses the beat); that never happens here |
| `conditional` spine inside the event | **Hkarin** | Story access control — the real "you may not / not yet"; falls to the fallback arm and closes | Route selection |

The orchestrator is deliberately **permissive about sequencing**: it will happily
trigger `event` at the wrong time, too early, too often. Hkarin is the
access control layer — an event that is not ready for you plays its "not yet"
arm and closes. That is how the game stays playable even with every gate
wide open, and why no spine can lock forward-progress permanently through
the world layer.

**Both layers may be used on the same trigger, neither is mandatory.** World
presence for flavor, story gate for law. There is no third gate.

## 4.5 World-variable registry — one table, no scopes

The game editor (the main project editor) owns a **single registry** of
variables for the whole game. Every `var` field in the studio — the hikarin
block editor *and* the orchestrator canvas — is a **dropdown of registry
entries**, never a free-text scratchpad, unless the registry is missing (then
users may type freely, with a warning chip attached).

**Rules, locked:**

- **`@world.*` only.** No `@maid.`, no `@scene.`, no `@player.` in the
  registry. Everything is global; there is no localised scope on purpose.
  One table, one namespace, one mental model.
- **Types are JSON primitives** (`string` | `number` | `boolean`). No
  schemas, no objects, no arrays — hikarin's own loose typing preserved.
  `type` is editor UX metadata (sensible default widgets); the engine will not
  enforce them at runtime.
- **Defaults are real.** Each declared entry compiles into the built game as
  auto-seed instructions — the orchestrator emits one invisible `create_global`
  per declared variable on first load, so anything the game writes can rely on
  the key existing with a sane value.
- **Compile warns** on: registry entry never referenced by any script or
  trigger (`unused_world_variable`), and every `var`-reference in a
  story/event source has a registry match **or** is flagged on save (free text
  is allowed, hika-style, but chipped).
- **File:** `world/variables.json` inside the game project:

```json
{
  "variables": [
    { "name": "hestia_met",  "type": "boolean", "default": false, "desc": "Met Hestia in the home map" },
    { "name": "west_open",   "type": "boolean", "default": false, "desc": "West gate opened" },
    { "name": "affection",   "type": "number",  "default": 0,     "desc": "Hestia affection scalar" }
  ]
}
```

Names live **without the `@world.` prefix** in the table — the prefix is the
engine's way of naming the scope, not the author's. The registry is the
authority on what exists in the game at all.

### Compile behaviour

1. Duplicate names → error.
2. Invalid JSON primitive types → error.
3. Unused entries → warning at export.
4. Story sources reference unknown names → warning, never error.
5. `game.json` receives `meta.variables[]` — the orchestrator walks it at
   boot and seeds any absent keys (`create_global` semantics).

### What this unlocks

- Dropdowns everywhere a variable is needed — hikarin's `variable`/`conditional`
  inspectors, orchestrator canvas field editors, visible_if/interact_if
  conditions, the future list-twin view.
- Export hints: hikarin's runtime can pre-create everything without load-order
  games.
- A single place for the designer to see every cross-script flag in the game —
  the "scope map" you'd otherwise need a debugger to reconstruct.

## 5. Entities — static, non-static, no motion

An **entity** is an interactable block. The player interacts with a cell;
nothing in the world moves. There is no NPC pathfinding, no "idle wander" —
the only moving thing in the game is the player.

Entities come in two flavours that are **indistinguishable in hikarin-studio**
and only differ in how a runtime attaches them:

| kind | placement | runtime treatment |
|---|---|---|
| `static` | painted into a specific map at a fixed cell — it is part of that map's decor | rendered as map art; interactable as a fixed hotspot (signpost, statue, chest, door) |
| `non-static` | not painted into the map grid; it exists *regardless of map* | the runtime binds it to whatever it likes: a maid, a quest marker, a flying familiar — the orchestrator never knows, and does not need to |

In the studio both are just **event blocks** sitting at a position in the
orchestrator's world model. The difference is one field on the entity, and it
is a *hint to the runtime*, never a branch in the story logic:

```json
{
  "entities": [
    {
      "id": "gate_west",
      "kind": "static",
      "map": "home",
      "rect": [1, 6, 1, 6],
      "event": "stinger_gate",
      "visible_if": "@world.west_open != true",
      "interact_if": "@world.west_open != true"
    },
    {
      "id": "quest_hint",
      "kind": "non-static",
      "attach": "quest",
      "event": "stinger_hint",
      "visible_if": "@world.quest_hint_available == true"
    }
  ]
}
```

- **`visible_if`** / **`interact_if`** — hikarin conditional grammar; absent =
  always. The fail case is not a lock message — silence. Any message you want
  IS an event, gate-gated at its start.
- **`event`** — the compiled event slug; the orchestrator dispatches it blind.
- **`attach`** — free-form string, runtime interprets it
  (`maid`, `quest`, `familiar`, `encounter`…). The orchestrator stores it,
  never parses it. Absent on static entities.
- `map`/`rect` are required for `static`, forbidden for `non-static`.

### No motion, decided

There is no `move` verb, no `patrol`, no `chase`. An entity's position is
authored, never computed. If a story wants a monster "roaming", the honest
answer is two static hunters in two cells, both firing the same event with
different gates — not pathfinding.

## 6. Saves — the honest contract

- **`@world.*`** lives in the shared profile (`ProfileSave`), written on
  `set_world`, `save`, on every `map` change and at every event completion.
  Cross-cartridge by design — the SHIFT rule holds.
- **Event locals** (hikarin SCENE/MAID) stay inside each event file’s runtime
  — a checkpoint belongs to its event, not the world. The world's save is only
  the profile flags plus the map/layer position.
- **No mid-map autosave in v1.** Resume = last map change or event end.
  Mid-map deaths reload from there. It is a limitation, deliberately, to keep
  v1's promise: walk, interact, trigger script. Refinement later.
- **`save`** is force-flush; **`map`** implies save after teleport. So a normal
  run never loses more than one event's work.

## 7. hikarin-studio wiring (what gets built to support this)

Only the pieces the document demands — the attack surface is small:

1. `project.json` gains `kind: "game"` (default `"story"`).
2. Loader walks `world/*.orch`, `events/*/`, compiles per event via existing
   hikarin compiler, assembles `game.json`.
3. Export: `build/game.json` + `build/events/*.json` + shared `images/…`
   `sounds/…`; `build/` gitignored; optional `.hikarin.zip` bundle later.
4. Editor: new game-editor surface — roster panel (events), world tabs
   (.orch), start label, build. Route A canvas — specified after this doc.
5. Validator: every `run_event` slug must resolve to a built event; every
   `map`'s `tiles` values must exist in palette; every `visible_if` is a parse
   of hikarin's conditional grammar (shared parser, not a re-implementation);
   no entity id reused within a map; `start` exists and is a label.

## 8. Test project (the acceptance test)

A game project, `projects/test-map/`, content-only — no Godot anywhere:
- Map `home` 16×16, spawn in yard.
- One entity `statue` at the yard center → `run_event "hestia"` →
  a short two-line hikarin event.
- One `conditional` spine: `@world.west_open == true` → `map wastes`.
- One `ending` in `wastes`.
- Game runs end-to-end in studio preview: walk → interact → dialogue → resume
  → conditional edge open → walk → ending. No networking, no engine, no art
  beyond placeholder tiles.

If that loop clicks, `projects/testing/` Hestia pattern is confirmed standing
on the orchestrator, and the bullet-hell cartridge is reduced to: a map,
entities that clear spawners, and an `ending`.

## 9. Non-goals (v1)

- No battles, stats, levelling, items, health meters.
- No mid-map autosave; no per-entity override saves inside events.
- No multiple start points; no branching world graph (single path + conditional
  edges).
- No engine-verb language (`play_level`, `command`) — hikarin may keep them
  for its own game, but the orchestrator does not.
- No zones or area vocabulary — every gate is a `conditional` in the spine.

## 10. Locked calls

1. **`script.orch` as code-as-data** — the world's logic is JSON; nothing
   leaves `world/`. Settled.
2. **Conditional grammar sharing** — literal hikarin grammar; one shared
   parser between hikarin and the orchestrator. Settled.
3. **`facing`** — not on the verb; optional field on the *map definition*,
   default `down`. Settled.
4. **`build/` inside the project** — regenerated wholesale; gitignored. Settled.
5. **Zones** — retired; spine conditionals and entity gates only. Settled.
6. **`needs:` contract** — dropped. Blocking is the event's job; hikarin's
   spine already cannot lock forward-progress. No cross-compiler contract.
   Settled.
7. **Orchestrator `conditional`** — route selector, never story access
   control. Settled.
8. **World-variable registry** — one global `@world.*`-only table in
   `world/variables.json`; JSON primitives; defaults compiled in and seeded by
   the orchestrator at boot; `var` edits are dropdowns of registry entries;
   unused → export warning. Settled.

## 11. Open items

1. **Canvas spec** (Route A, full) — to be written next; deliverable #2.
2. **Enqueue order after spec** — implementation plan for the game-editor
   surface, phased (model → compile → UI → Godot runtime).
