# Hikarin script format — ground truth

Everything the studio writes must compile to exactly this. It is what the
runtime reads.

## Shipped format

One flat JSON array per character, at `assets/hikarin/<trigger>.json`.
The trigger is the file name: `cupa.json` is read by the character `cupa`.

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
| `command` | `command` | runs a console command |
| `play_level` | `level` | **PvZ Fusion extension:** leave the VN, play this custom level, then resume. Optional `on_complete` / `on_fail` labels; empty = fall through / retry |
| `give_item` | `item`, `amount` | |
| `take_item` | `item`, `amount` | |
| `play_music` | `music` | null stops |
| `play_sound` | `sound` | |
| `unlock_dialogues` | `events[]` | adds labels to the idle pool |
| `idle_chat` | — | jumps to a random unlocked label |
| `next` | `label` | **resume point** — the scene reopens at this label |
| `finish_dialogue` | — | closes the screen |

## `next` is a real save

`next` writes a checkpoint label. The next time this story's scene opens, the
engine jumps straight to that label instead of starting from the top. This
matches the 2024 engine, which stored `checkpoint` in `localVariables`, saved
them per entity, and jumped back to it in `loadProgress()`.

A checkpoint pointing at a label that no longer exists logs a warning, clears
itself, and starts from the top — rather than silently pretending to resume.

`end` (`finish_dialogue`) writes `WORLD` scope to disk. `MAID` and `SCENE`
values are in the story's NBT and save with the entity, so they do not depend on
`end` firing.

## Scopes

Bare names resolve to `SCENE`. Explicit prefixes select other scopes.

| scope | prefix | lifetime | writable |
|---|---|---|---|
| `SCENE` | `@scene.` | **per maid, survives scene close** (NBT) | yes |
| `MAID` | `@maid.` | per maid, survives everything else (NBT) | yes |
| `WORLD` | `@world.` | forever, profile JSON; survives new worlds | yes |
| `PLAYER` | `@player.` | injected fresh per scene, **read-only** | no

**The studio exposes two of these, not four.** An author chooses between *local*
and *global*, because those are the only two that change how you write: a local is
one story's own business, a global is shared and has to be declared so every story
offers the same spelling. `MAID` and `SCENE` differ in which NBT compound a name
lands in — a distinction the engine makes and an author should not have to. Both
compile to bare names from the studio; write `MAID` explicitly by hand if you need
it.

The studio's words are `LOCAL` and `GLOBAL`. `hikarin.blocks` translates on the
way out: `GLOBAL` becomes `"scope": "WORLD"`, and `LOCAL` emits no scope key at
all, because a bare name is how the engine spells local. The translation is one
table in one module — do not rename the output, the mod reads the literal string.

**`SCENE` is not ephemeral.** Despite the name, bare-name variables are stored
in the story's NBT under a `local` compound and outlive the conversation. This
matches the 2024 engine, where `localVariables` were written to disk per entity
by `saveProgress()` and restored by `loadProgress()`. A legacy script that
increments a bare variable across conversations still accumulates.

### The `local` and `@maid.` keyspaces are separate

Bare names live in the runtime's per-character state, `@maid.` values directly
in the character's own state.
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

## Sprites

Copied from the original SDK's `characters.py`, which states it directly:

```
# In minecraft, character sprite will be located in
# textures/character.id/character.outfit/emotion.png

# show(cupa, "happy")  ->  textures/cupa/default/happy.png
```

**Three levels, always: `<character>/<outfit>/<emotion>.png`.**

```json
{
  "type": "show_sprite",
  "action": "show",
  "sprite": "cupa",
  "location": "characters/cupa/default/happy.png",
  "dyn_location": "characters/cupa/<cupa_outfit>/happy.png",
  "position": "CENTER",
  "wRatio": 16, "hRatio": 9, "wFrameRatio": 4, "hFrameRatio": 8,
  "column": 7, "row": 1
}
```

`sprite` is the **slot name**, not a path: two shows with the same `sprite`
replace each other rather than stacking.

### On disk

```
assets/hikarin/textures/
   characters/
      cupa/
         default/
            normal.png        <- show(cupa, "normal")
            happy.png         <- show(cupa, "happy")
         summer/
            happy.png         <- outfit swap
      andr/
         default/
            normal.png
   room.png                    <- backgrounds sit flat
```

### `dyn_location` — outfit chosen at runtime

The SDK writes a second path with the outfit as a `<variable>` placeholder:

```
location      characters/cupa/default/happy.png    <- fallback
dyn_location  characters/cupa/<cupa_outfit>/happy.png
```

At show time the engine substitutes `<cupa_outfit>` from scene or world state.
If the variable is undefined, or the result is incomplete, it falls back to
`location` and logs a warning. That is how a character changes clothes mid-story
without the script branching its own Show blocks.

### Name rules

Sprite, outfit and emotion names are validated the way the SDK validates them:

```python
if re.search(r"[A-Z\s.,!?#@$*]", sprite):
    raise ValueError("Sprite name cannot contain special characters, "
                     "white space, or uppercase letters.")
```

Texture paths are lowercase-only. A capital or a space does not fail
loudly — it silently renders nothing, which reads as "the artist forgot a
file". The compiler rejects it instead.

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

A project is a pack. A story is one character's script inside it. A story's `.story`
files compile into one flat JSON.

```
<project>/
  project.json
  stories/
    cupa/
      story.json
      main.story
      night.story
      idle.story
      items/endrod.story
```

`project.json` is the pack manifest:

```json
{
  "packName": "Cupa's Story",
  "description": "Made with Hikarin Studio"
}
```

`stories/<story>/story.json` is the script manifest. `character` is the trigger
— it becomes the file name the runtime loads (`assets/hikarin/<character>.json`)
and must be unique inside the pack:

```json
{
  "character": "cupa",
  "description": "",
  "files": ["main.story", "night.story", "idle.story", "items/endrod.story"],
  "startLabel": "start"
}
```

Each `.story` file holds an array of the same action objects, but **without
`id`**. The compiler concatenates that story's files (the one containing
`startLabel` first), assigns sequential ids, and validates that every `label`
reference resolves.

The resource pack format version is not stored here. It is an export option —
pass `pack_format` when exporting, defaulting to 15.
