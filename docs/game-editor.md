# Hikarin Game Editor — Design (settled)

**Status:** Implemented in hikarin-studio. This document is the ground truth for
the game-editor architecture; when it disagrees with a spec or a README,
**this** wins.

**Intent.** A game project = many hikarin scripts + one world definition.
There is no secondary logic language. Hikarin's conditional blocks already are
the world's branching. The only thing that exists the story side does not know
about is a map — and a map is *data*, exactly like a background sprite.

---

## 1. The three layers

```
[ event scripts ]     ← hikarin stories compiled per event (events/<slug>/*.json)
                        The engine runs these for triggers on the map.
[ game.json ]         ← { meta, maps } — the world definition; data, not code
[ runtime (engine) ]  ← loads game.json + events; renders the grid; runs
                        scripts on interaction; persists @world.* in the profile
```

`.story` files remain the authoring surface. The engine never sees them.

## 2. Project layout

```
projects/my-game/
  project.json          { "kind": "game", "packName": ..., "startMap": "home" }
  world/
    variables.json      the registry — every @world.* flag in this game
    maps.json           grid maps: tiles, palette, entities, spawn
  events/
    hestia/
      project.json      { "kind": "story", ... }
      main.story
  images/ sounds/       shared assets
  build/                ← gitignored export output
    game.json           { meta, maps } — engine boot file
    events/hestia.json  compiled, hikarin verbatim
    images/...
```

## 3. `game.json` (compiled) shape

```json
{
  "meta": {
    "packName": "My Game",
    "description": "",
    "version": 1,
    "startMap": "home",
    "variables": [
      { "name": "hestia_met", "type": "boolean", "default": false, "desc": "..." }
    ]
  },
  "maps": {
    "startMap": "home",
    "maps": {
      "home": {
        "cols": 16, "rows": 16,
        "tiles": ["grass", "tree", ...],          // cols*rows ids
        "palette": {
          "grass": { "image": "asset/grass.png", "traversable": true },
          "tree":  { "image": "asset/tree.png",  "traversable": false }
        },
        "entities": [
          { "id": "statue", "kind": "static", "col": 11, "row": 3, "event": "hestia" }
        ],
        "spawn": { "col": 2, "row": 8, "facing": "down" }
      }
    }
  }
}
```

- `variables` is the registry compiled in; the engine seeds absent keys on
  boot (hikarin's `create_global` semantics).
- `maps` is passed verbatim from `world/maps.json` after validation.
- There is **no** orchestrator/script section: map switches are hikarin
  actions inside event scripts.

## 4. The one new hikarin action: `map`

```json
{ "type": "map", "action": "switch", "map": "home", "x": 2, "y": 8, "facing": "down" }
```

- A hikarin-like block — added to the flow palette as **Map Switch**.
- `x`/`y` are the player's spawn cell for the target map (row 1 = top).
- `facing` optional: `up|down|left|right`, defaults to `down`.
- Engines that do not know `map` ignore it, as they ignore unknown types.
- Round-trips through the editor like any other block (load/ship/edit).

## 5. Maps — data, not code

- **Tiles** are ids; **tile types** live in `palette` with `image` and a
  binary `traversable`. No other per-tile properties exist at v1.
- **Grid** `tiles[]` is `cols*rows` sequential ids, row-major.
- **Spawn** is one cell + facing per map.
- **Entities** are *interactable blocks* with:

| field | required | meaning |
|---|---|---|
| `id` | yes | unique per map; lowercase slug |
| `kind` | yes | `static` (pinned to col,row) or `non-static` (engine binds it — a maid, a quest marker…) |
| `col`,`row` | static only | cell position, 0-indexed |
| `event` | yes | slug of a compiled event (`build/events/<slug>.json`) |
| `visible_if`,`interact_if` | no | hikarin conditional grammar; absent = always |
| `attach` | non-static only | free string the runtime interprets |

- Static entities live on the map grid and render as hotspots; non-static
  ones are bound by the engine to whatever it likes — the editor shows them
  in the entity tray, not on the canvas. Either way, access control
  happens **inside the event** (hikarin's `conditional` spine), never in the
  world layer — the world can only route.

## 6. Gates: who decides what

| Layer | Decision | Fork mechanism |
|---|---|---|
| World (`visible_if`/`interact_if`) | Is the hotspot visible/clickable? | entity presence on grid |
| Event spine (hikarin `conditional`) | May the player through? | hikarin `conditional` inside the story |
| Story (idle/ending) | Does the scene behave per state? | hikarin `conditional` + `next` resume |

No doorman at the world layer for story access. The event always decides.

## 7. Saves

- `@world.*` — the shared registry — literal profile JSON (cross-cartridge).
- Map position = engine runtime state; respawn from map change/event end.
- Mid-map death = reload from last checkpoint (or map load, by engine choice).

## 8. Compiler contract (studio → engine)

1. **One `game.json`** per game project (+ one JSON per event + shared assets).
2. **Event slugs resolve** — `entities[].event` must have `build/events/<slug>.json`.
3. **Tile ids resolve** — every `tiles[]` entry must exist in `palette`.
4. **Grid math holds** — `len(tiles) == cols * rows`.
5. **Unused registry entries warn** at export; undeclared references warn.
   Nothing blocks on this — the event spine decides story access.
6. **`startMap` exists** in `maps` or the engine has nothing to load.

## 9. What this is NOT

- Not a graph: no nodes, no wires, no `.orch`, no orchestrator language.
- Not RPG-Maker: no levelling, stats, items, or combat vocabulary in the
  engine (they live inside events if the author wants them).
- Not a map-zones system: gates are conditionals, not areas.
- No NPC pathfinding; everything except the player is static.
