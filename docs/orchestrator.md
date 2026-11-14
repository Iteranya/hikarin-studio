# The Orchestrator — plan

Status: **proposal, nothing built.** Read this, approve or change it, then it gets written.

---

## What it is

The RPG Maker equivalent of a **Map**, where the **Story is the Event**.

An orchestrator is a named container holding an ordered list of events. Each event
points at a compiled story `.json` and says when it fires. There is no space in it
— no tiles, no coordinates, no canvas. It is a form.

```
chapter_1
  ├── prologue        autorun   → prologue.json
  ├── talk_to_cupa    action    → cupa_intro.json
  ├── hollow_door     action    → hollow_01.json
  └── after_boss      autorun   [if: chapter1_cleared] → epilogue.json
```

Where any of those things appear in the world is the engine's problem. The
orchestrator only says *what exists here* and *what wakes it up*.

## The one rule

> An orchestrator sees **names**, never **contents**.

It can fire a story or another orchestrator. It can never read either. No labels,
no blocks, no peeking. Same boundary the whole project already runs on: the
compiler never learned about projects, and the orchestrator never learns about
scripts.

Which is why an event's target is a name plus a kind, and nothing else.

---

## Data

### Where it lives

```
projects/<project>/
  project.json
  variables.json
  orchestrators/                 ← new
    chapter_1.json
    chapter_2.json
  stories/…
  images/…
  sounds/…
```

One file per orchestrator. A project can have any number of them.

Separate files rather than one `orchestrators.json` because they are independent
things that get renamed, diffed and deleted on their own — the same reason
`variables.json` is not a field on `project.json`.

### Shape

```json
{
  "id": "chapter_1",
  "name": "Chapter 1",
  "description": "",
  "events": [
    {
      "name": "prologue",
      "trigger": "autorun",
      "conditions": [],
      "target": "prologue.json",
      "targetKind": "story"
    },
    {
      "name": "to_chapter_2",
      "trigger": "action",
      "conditions": [
        { "var": "chapter1_cleared", "condition": "equal", "value": true }
      ],
      "target": "chapter_2",
      "targetKind": "orchestrator"
    }
  ]
}
```

`events` is ordered. Autoruns run top to bottom; action events are offered in the
same order.

### `trigger` — only two, because there is no space

| value | meaning |
|---|---|
| `autorun` | fires when the orchestrator starts, blocks the player |
| `action` | the player chooses it (talk to it, select it from a list) |

RPG Maker also has `player touch` and `parallel`. `touch` is meaningless without
positions — there is nothing to walk into — and `parallel` is a non-blocking
background process, which is a bigger feature than this needs. Both are noted as
*later*, not now.

### `conditions` — the gate, not the trigger

This is the distinction that matters. **Trigger is how it fires. Conditions are
whether it exists at all.**

Reuses the compiler's existing vocabulary verbatim — `equal`, `not_equal`,
`greater_than`, `less_than`, `greater_or_equal`, `less_or_equal`, `exists`,
`not_exists`, `night`, `day`. Same words as an `if` block. Two vocabularies for
"is this true" is how the variable-scope mess happened the first time.

Multiple conditions are ANDed. Empty list = always active.

Night and day take no `var` and no `value`, exactly like `exists`.

### `targetKind`

Explicit rather than inferred from the extension. `"story"` means the target is a
compiled filename (`cupa.json`); `"orchestrator"` means it is another
orchestrator's id. An extension check would work today and become a bug the first
time somebody names an orchestrator `chapter.json`.

---

## Validation

Errors, which block saving:

- id not slug-shaped (`[a-z0-9_-]`, ≤64 chars)
- `id` empty, or a file with that id already exists
- an event has no name
- two events in one orchestrator share a name
- an event has no target
- `targetKind: story` and the target is not among the project's compiled story
  filenames
- `targetKind: orchestrator` and no such orchestrator exists
- an event targets its own orchestrator (self-loop)
- an unknown `trigger` or unknown `condition`

Warnings, which do not block saving:

- a condition names a variable that is not declared in `variables.json`
  (consistent with stories — declaring is a convenience, not a requirement)
- an orchestrator has no `autorun` event

**Not checked on purpose: cycles across orchestrators.** A → B → A is legal. The
validator could walk it, but the whole design says an orchestrator never looks
inside another one, and a tool that starts doing exactly that is the first step
back to the thing that got thrown out. Direct self-reference is caught because
that is a single file, not a traversal.

---

## API

New routes, following the existing project-scoped pattern:

```
GET    /api/projects/{slug}/orchestrators                 list (id, name, event count)
POST   /api/projects/{slug}/orchestrators                 {"id": "...", "name": "..."}
GET    /api/projects/{slug}/orchestrators/{id}            the whole thing
PUT    /api/projects/{slug}/orchestrators/{id}            save (validated first)
DELETE /api/projects/{slug}/orchestrators/{id}
POST   /api/projects/{slug}/orchestrators/{id}/rename     {"new_id": "..."}
GET    /api/projects/{slug}/orchestrators/{id}/validate   errors + warnings
```

Save is a whole-file `PUT`, like a story. Validation runs on the server and a
failure is a 400 with the error list, not a silent partial write.

---

## UI

**Manager gets a third tab:** `Stories | Variables | Orchestrators`.

The Orchestrators tab lists them with event count, and is the only place they are
created, renamed or deleted — same division as stories. Structure changes in the
manager, content changes in the editor.

**Clicking one opens `/orchestrator?project=<slug>&id=<id>`** — a separate page,
mirroring `/editor`. It is a form, not a canvas:

- a name field and the list of events, one row each
- each row: name, trigger dropdown, target picker, conditions
- the target picker offers two groups — compiled stories from this project's
  other stories, and the other orchestrators in this project
- conditions edited with the same widgets the story inspector already uses
  (`variableField`, the condition dropdown, the value field)
- add / remove / reorder events
- Save, and a Validate button that shows errors inline

No drag-to-connect, no lines, no nodes. If a row needs to move, it moves with
buttons.

---

## Export

The Hikarin bundle gains an `orchestrators/` folder and a manifest entry:

```json
"orchestrators": [
  { "id": "chapter_1", "file": "orchestrators/chapter_1.json", "events": 4 }
]
```

The runtime reads the manifest, picks an orchestrator by id, and executes it.

**Resource pack export does not include orchestrators.** A pack is a set of
compiled scripts for a runtime that already has its own flow; the orchestrator is
Hikarin's idea of flow and travels with the Hikarin bundle. If that turns out
wrong, it is one line to add.

---

## Files

| file | change |
|---|---|
| `hikarin/orchestrators.py` | **new** — storage, validation, the trigger/kind vocabularies |
| `main.py` | 7 routes, plus the orchestrator bundle in the export |
| `hikarin/exporter.py` | ship `orchestrators/` in `build_hikarin`, add the manifest key |
| `static/manager.html` `.js` `.css` | third tab, list, create/rename/delete |
| `static/orchestrator.html` `.js` `.css` | **new** — the form |
| `main.py` | `GET /orchestrator` page route |
| `tests/test_orchestrators.py` | **new** — real files in a temp dir, no mocks |
| `README.md` | a section on the orchestrator + the API list |
| `FORMAT.md` | the on-disk shape |

## Deliberately not doing

- **No positions.** Decided. A list of names.
- **No `touch` / `parallel` triggers.** Consequence of no positions.
- **No execution engine.** The orchestrator is data. Godot runs it. Anything that
  simulates a playthrough here would be a second runtime to keep in sync.
- **No cross-orchestrator analysis.** See validation above.
- **No changes to `playLevel`.** Already neutral; that was handled.

---

## Settled

- **No display label on events.** The name is the only identifier; what the player
  reads is the runtime's to decide. Presentation is a renderer job, and a second
  field here would just move a renderer decision into the data.
- **No simulate panel in v1.** Previewing which events light up is gameplay /
  testing simulation, not authoring. It belongs with the rest of the test tooling,
  once everything else is done.
