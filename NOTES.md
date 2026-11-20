# Design notes / known wrinkles

## Conditional jump targets are ids, not labels

The engine's `conditional` stores `"end": <id>` — the action id to jump to when
the test fails. The studio authors with **labels**, so the compiler must:

1. Emit every `If` block with a placeholder `end`
2. After all ids are assigned, resolve each `If`'s target label to that label's
   id and write it in

This is why `fromAction` for `if` cannot round-trip a target: reading a shipped
JSON gives you an id, not the label the author typed. Solution: keep the target
label in the source `.story` file as a studio-only field (`_target`), and strip
it at compile time.

Same applies to `night_choice` and `choice`, whose `label` fields are real
labels — those round-trip fine.

## choice labels are real labels

`{"label": "yes", "display": "Yes"}` — the `label` here is a jump target, not a
speaker. Do not confuse it with `dialogue.label`, which IS a speaker name.
Two different meanings for the same key name in the shipped format.

## Sprite paths

The engine resolves a sprite by `location`, e.g.
`characters/cupa/default/happy.png`, against `hikarin:textures/`, then the
framework's own art, then a legacy `mobtalkerredux:` namespace.

Three levels, matching the SDK's `characters.py`: character, outfit, emotion.
The outfit level is not optional — the 2024 mod never shipped outfit swapping,
but the SDK author added it as groundwork so scripts would not need rewriting
later. Skipping it here would have meant migrating every sprite reference once
outfits landed, so the studio emits it from day one.

## RM-derived VN variables carry `source: "rm"`

Resources flagged visible_to_vn are synced into `variables.json` on every RM
save, tagged `"source": "rm"`. `hikarin.variables.load_variables` drops unknown
keys when it rewrites the file, so RM syncs read the raw JSON instead — never
round-trip the registry through `load_variables`/`save_variables` if you need to
tell RM-derived entries from hand-registered ones.

Sync rules: RM-derived entries are replaced wholesale; hand-registered ones are
never touched; a VN name colliding with a hand-registered variable is a hard
error that refuses the save. The registry is append-only for humans, replace-set
for the RM editor.

## Unreachable reachability is a heuristic, not a proof

`rm_schema.validate_schema` seeds reachability from requirement-free nodes and
propagates outward (tech unlocks, effect targets, generator level unlocks, node
`connects_to`). A node *gated behind* a requirement but unlocked by another
node's completion still shows as unreachable when nothing references it — treat
the warning as "did you forget to wire this up?", not as a hard failure. It is
tagged `(warning)` and never blocks save or export.
