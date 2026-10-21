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
framework's own art, then `mobtalkerredux:`.

Three levels, matching the SDK's `characters.py`: character, outfit, emotion.
The outfit level is not optional — the 2024 mod never shipped outfit swapping,
but the SDK author added it as groundwork so scripts would not need rewriting
later. Skipping it here would have meant migrating every sprite reference once
outfits landed, so the studio emits it from day one.
