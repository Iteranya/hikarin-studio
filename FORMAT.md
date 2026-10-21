# Hikarin script format — ground truth

Everything the studio writes must compile to exactly this. It is what the
Minecraft runtime (`TLM: Visual Novel Framework`) reads.

## Shipped format

One flat JSON array per character, at `assets/hikarin/<trigger>.json`.
The trigger is the file name: `cupa.json` is read by a maid named `cupa`.

```json
[
  { "type": "meta", "action": "start", "id": 0 },
  { "type": "label", "action": "label", "label": "start", "id": 1 },
  { "type": "dialogue", "action": "say", "label": "Cupa", "content": "Oh hey!", "id": 2 },
  { "type": "finish_dialogue", "action": "finish_dialogue", "id": 3 }
]
```

Ids are sequential from 0 and unique. The engine looks actions up by id.

## Action vocabulary

| type | required fields | notes |
|---|---|---|
| `meta` | `action` | `start`, `declare`, `create_var`, `create_global` |
| `label` | `label` | jump target |
| `dialogue` | `label`, `content` | optional `voice` |
| `show_sprite` | `sprite`, `location` | optional `position`, ratios, column/row |
| `remove_sprite` | `sprite` | |
| `modify_background` | `background` | path under textures |
| `clear_background` | — | |
| `modify_variable` | `var`, `action`, `value` | `scope` optional |
| `modify_global` | `var`, `action`, `value` | legacy, forces WORLD |
| `conditional` | `condition`, `var`, `value`, `end` | `scope` optional |
| `conditional_global` | same | legacy, forces WORLD |
| `choice` | `choice[]` | each `{label, display}` |
| `night_choice` | `choice[]` | only shown at night |
| `transition` | `action: "jump"`, `label` | optional `file` for cross-scene |
| `command` | `command` | runs a Minecraft command |
| `give_item` | `item`, `amount` | |
| `take_item` | `item`, `amount` | |
| `play_music` | `music` | null stops |
| `play_sound` | `sound` | |
| `unlock_dialogues` | `events[]` | adds labels to the idle pool |
| `idle_chat` | — | jumps to a random unlocked label |
| `next` | `label` | **resume point** — the scene reopens at this label |
| `finish_dialogue` | — | closes the screen |

## `next` is a real save

`next` writes a checkpoint label. The next time this maid's scene opens, the
engine jumps straight to that label instead of starting from the top. This
matches the 2024 engine, which stored `checkpoint` in `localVariables`, saved
them per entity, and jumped back to it in `loadProgress()`.

A checkpoint pointing at a label that no longer exists logs a warning, clears
itself, and starts from the top — rather than silently pretending to resume.

`end` (`finish_dialogue`) writes `WORLD` scope to disk. `MAID` and `SCENE`
values are in the maid's NBT and save with the entity, so they do not depend on
`end` firing.

## Scopes

Bare names resolve to `SCENE`. Explicit prefixes select other scopes.

| scope | prefix | lifetime | writable |
|---|---|---|---|
| `SCENE` | `@scene.` | **per maid, survives scene close** (NBT) | yes |
| `MAID` | `@maid.` | per maid, survives everything else (NBT) | yes |
| `WORLD` | `@world.` | forever, profile JSON; survives new worlds | yes |
| `PLAYER` | `@player.` | injected fresh per scene, **read-only** | no |

**`SCENE` is not ephemeral.** Despite the name, bare-name variables are stored
in the maid's NBT under a `local` compound and outlive the conversation. This
matches the 2024 engine, where `localVariables` were written to disk per entity
by `saveProgress()` and restored by `loadProgress()`. A legacy script that
increments a bare variable across conversations still accumulates.

Use `SCENE` for per-maid working values, `MAID` for explicitly per-maid flags,
`WORLD` for player-wide progress, and `PLAYER` for read-only world facts.

### The `local` and `@maid.` keyspaces are separate

Bare names live in `TlmVnState.local`, `@maid.` values directly in `TlmVnState`.
So `affection` and `@maid.affection` are two different variables and will not
collide. This is deliberate: an explicit scope and a bare name should never
overwrite each other by accident.

### Injected every time a scene opens

`SCENE`: `isDay`, `isNight`, `heldItem`, `playerName`, `dimension`

`PLAYER` (eager): `health`, `max_health`, `absorption`, `food`, `saturation`,
`xp_level`, `air`, `is_sleeping`, `is_sprinting`, `is_creative`, `is_spectator`,
`gamemode`, `difficulty`, `is_hardcore`, `dimension`, `pos_x`, `pos_y`, `pos_z`,
`time_of_day`, `day`, `is_raining`, `is_thundering`, `moon_phase`

`PLAYER` (lazy, computed on read):
`advancement.<id>` — e.g. `advancement.minecraft:nether`
`inventory_has.<item>` — e.g. `inventory_has.minecraft:end_rod`

## Conditions

`equal`, `not_equal`, `less_than`, `greater_than`, `less_or_equal`,
`greater_or_equal`, `exists`, `not_exists`, `day`, `night`

## The spine pattern

The character file is a router. It is the only entry point.

```
[label start]
  If @maid.seen.night_01 == false  -> jump night_01
  If @player.advancement.minecraft:nether == true -> jump nether_chat
  If @world.affection.cupa >= 384  -> jump tier_4
  If isNight                       -> jump night_generic
  idle_chat
  End
```

Unlock is a flag. Progress is a conditional. There is no separate gating system.

## Source format (what the studio edits)

A project is a folder of `.story` files that compile into one flat JSON.

```
cupa/
  project.json
  main.story
  night.story
  idle.story
  items/endrod.story
```

`project.json`:

```json
{
  "character": "cupa",
  "packName": "Cupa's Story",
  "packFormat": 15,
  "displayName": "Cupa",
  "files": ["main.story", "night.story", "idle.story", "items/endrod.story"],
  "startLabel": "start"
}
```

Each `.story` file holds an array of the same action objects, but **without
`id`**. The compiler concatenates the files (the one containing `startLabel`
first), assigns sequential ids, and validates that every `label` reference
resolves.
