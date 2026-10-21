# Hikarin Studio

Visual editor for Hikarin visual novel scripts — the content pipeline for
**TLM: Visual Novel Framework**.

Write a story as a stack of blocks, hit Play to test it with simulated state,
export a resource pack and drop it into Minecraft.

## Status

Phase 1 in progress: compiler done and tested, editor UI being built.

## Layout

```
src/blocks.js      the block palette — 19 blocks, grouped into 5 families
src/compiler.js    .story files -> one flat JSON the Minecraft engine reads
test/              node --test
FORMAT.md          ground truth on the shipped JSON format and the engine's
                   action vocabulary, scopes and conditions
NOTES.md           design wrinkles: conditional id targets, label vs speaker
```

## The model

A project is a folder of `.story` files. Each is a tab in the editor.

```
cupa/
  project.json    character, pack name, file order, start label
  main.story      the spine — day/night, affection tiers, achievement gates
  night.story
  idle.story      40 idle lines get their own tab; they compile into the same
                  flat file but never clog the story you're reading
  items/
    endrod.story
```

Labels are global across files, so a Jump in `main.story` can target a label
defined in `night.story`. The compiler validates every reference and suggests a
correction on typos.

## Compile

```bash
npm test
```

```
stories/*.story  ->  concat (startLabel's file first)
                 ->  assign sequential ids
                 ->  resolve conditional targets to ids
                 ->  validate labels, choices, unlocks
                 ->  assets/hikarin/<character>.json
```

## Why one flat file

The engine reads one file per character. Many source files exist for humans —
organising 40 idle lines separately from the story spine — and the compiler
merges them. Authoring structure and shipped structure are different problems.

## Licence

AGPL-3.0 (matches the original Hikarin framework).
