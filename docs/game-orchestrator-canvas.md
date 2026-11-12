# Route A Canvas — Visual Editor Spec for `.orch`

**Status:** Specification only. No code. This is the companion to
`game-orchestrator.md` §11. It defines the editor experience for
`world/script.orch` — a node canvas, not a block list — and the grid painter
for maps.

---

## 0. What is being edited

Two artifact kinds in the game editor, each with its own canvas:

| Artifact | Canvas type | Input |
|---|---|---|
| `world/*.orch` (script graph) | **Node canvas** — pan/zoom, nodes + wires | Route A full, as specified here |
| `maps.json` entries (`world/map.orch`-adjacent) | **Grid painter** — 16×16 cell board | Section 9 |

Everything below defines the node canvas; grid painter in section 9. They are
siblings, never one merged view — logic and geometry never share a canvas.

## 1. Principles

1. **One file = one finite graph.** The canvas never shows more than one
   `.orch` file. Cross-file links are compile-time only.
2. **Deterministic layout checker, not a layout engine.** Node positions are
   authored coordinates stored in the file. Auto-layout is best-effort on
   first draw (from-top-down BFS), never re-arranged behind the author's back.
3. **Compile-time validity ≥ canvas cosmetics.** The canvas is a friendly
   syntax for the same graph the compiler checks. If the canvas cannot draw
   it honestly, the file is wrong — canvas never hides semantics.
4. **Zero engine awareness.** No "Godot", no "tile size", no "M bytes"
   in the canvas. It is a graph editor with a JSON contract.
5. **Faithful round-trip** — save → load → save must be byte-stable except
   for node coordinates.

## 2. On-disk format (`.orch`)

```json
{
  "kind": "orch-graph",
  "start": "n_0001",
  "nodes": [
    { "id": "n_0001", "verb": "meta",  "fields": { "action": "start" }, "at": [0, 0] },
    { "id": "n_0002", "verb": "label", "fields": { "label": "start" }, "at": [0, 140] },
    { "id": "n_0003", "verb": "conditional", "fields": { "condition": "equal", "var": "@world.west_open", "value": "true", "end": "" }, "at": [0, 280] },
    …
  ],
  "wires": [
    { "from": ["n_0001", "out"],   "to": ["n_0002", "in"] },
    { "from": ["n_0002", "out"],   "to": ["n_0003", "in"] },
    { "from": ["n_0003", "true"],  "to": ["n_0010", "in"] },
    { "from": ["n_0003", "false"], "to": ["n_0011", "in"] }
  ]
}
```

- **Sequential-id rule dies here** — ids are stable-local (`n_` + counter);
  compile assigns global sequential ids for the engine. Coordinates and ids
  are preserved forever; no rename storms.
- **Wires reference node ids**, never indexes — order-free save, order-free
  load, no silent breakage on deletion.
- `at` is the canvas top-left in canvas pixels. The compiler ignores it.
- `end`-less `conditional` is a compile error in both world and hikarin —
  canvas renders the `end` field as a ghost socket showing unset state.

## 3. Canvas itself

- **Infinite pane**, dark themed, 24 px grid dots every 24 px (visual; no snap
  unless "snap" toggle on — default ON, 12 px).
- **Pan**: `Space` + drag, or middle-mouse drag. **Zoom**: wheel (25%–200%),
  keyboard `+`/`-`, and `F` = fit graph (edge-of-graph padding 48 px).
- **Select**: click node; drag on empty canvas = marquee rect; `Ctrl/Cmd`
  adds to selection; `Escape` clears. `Ctrl/Cmd+A` selects all.
- **Move**: drag selection; arrow keys nudge 12 px (`Shift` = 1 px).
- **Duplicate**: `Ctrl/Cmd+C` / `V` — duplicates with fresh ids, wires to
  duplicated nodes are dropped, offset +36 px.
- **Delete**: `Delete`/`Backspace` — deletes nodes + their wires. Wires are
  individually selectable (click the wire hit-path; shift-click multi-select
  wires).
- **Wire draw**: drag from an outlet socket; drop on any inlet. Validity
  preview while dragging (green = will connect, red = invalid target with a
  reason tooltip).
- **Shortcuts (full list)**: `Ctrl/Cmd+Z/Y` undo/redo (shallow stack, 50);
  `Ctrl/Cmd+S` save; `Ctrl/Cmd+Enter` validate; `F` fit; `L` toggle list
  view; `H` hide/show minimap; `?` shortcut sheet.
- **Minimap**: top-right, ghost blocks + viewport rectangle, drag to pan.
- **Status bar**: node count, wire count, zoom %, graph validation state
  (green `VALID` / amber `WARNINGS` / red `ERRORS (n)`), autosave clock
  matching hikarin-studio's.

## 4. Node anatomy

```
╭──────────────────────────────╮
│ ● label          [Flow]     │  ← header: verb + family tag; collapse toggle
├──────────────────────────────┤
│ label  [ start ]   ◄──────  │  ← body: inline field editors
│                              │
│                    out ╮   │  ← outlet(s), right side, labelled
╰──────────────────────────────╯
```

- **Header** — color-coded by family (Section 5). Collapse hides body; wires
  stay visible as a single stub line.
- **Body** — one row per field; field type dictates widget:
  - `label` — text box (hikarin-style monospace, existing labels as suggestions)
  - `var` — **dropdown of `world/variables.json` registry entries**; free text with warning-chip if registry missing or unset. Never an empty dropdown (an empty registry = every var is unknown = chip everything)
  - `condition`/`value` — dropdown (conditional)
  - `map` — dropdown of map ids from `world/maps.json` — **read-only; the
    map painter authors it**
  - `event` — dropdown of events roster
  - `x`, `y` — integer spinners
  - booleans/enums — checkbox / segmented control
- **Sockets** — inlets on the left, outlets on the right. `conditional` has
  two labelled outlets (`true` / `false`) — it is a **route selector**: it
  chooses which event to dispatch, never whether the story grants access.
  `jump`, `map`, `ending` have **no** outlet; `run_event`/`on_event_end`
  express the call-site flow explicitly as two nodes.
- **Ghost socket** on `conditional.end` when empty — renders dashed with a
  compact `end?` hint; connecting `false → end` behaves the same as textual
  `end`-via-jump in hikarin's grammar (both means of the same routing).
- **Badge** — top-right of node: `!` for compile error, `?` for warning,
  `✓` when validated clean. Click badge → inspector pins that issue.

## 5. Families and the complete node list

| family | color | nodes | shape |
|---|---|---|---|
| **Flow** | indigo | `meta (start)`, `label`, `jump`, `conditional` | control-flow spine |
| **World** | emerald | `map (load)`, `ending` | world ferry/terminus — no outlet on either |
| **Entity** | amber | `entity (begin)` | arm an entity handoff; paired with `run_event` |
| **Event** | violet | `run_event`, `on_event_end` | the only crossing to hikarin |
| **State** | sky | `set_world`, `save` | `@world` write channel + flush |
| **Debug** *(studio-only)* | rose | `log` | stdout marker; stripped at build |

That's the complete set — 11 nodes. No choice, no dialogue, no sprites. Any
temptation to add more means the verbs list is wrong, not the canvas.

**Drop from palette** = new node (disconnected, at drop point). **Double-click
on wire** = insert a node chooser popover between source and target (most
common flow authoring gesture). Re-drag existing wire ends to rewire.

## 6. Wire semantics & validation

- One wire per inlet. Multiple wires may leave one outlet except `conditional`
  outlets (per grammar: each path, exactly one target).
- `jump` outlet → any node's inlet; a cycle through `jump` is legal
  (quests loop) — no cycles through anything else (compile error).
- `map`, `ending`, `jump` — outlets forbidden; drawing an outlet from them is
  impossible (they have none rendered).
- `label` outlet feeds exactly one child, but that child may be **any verb** —
  it is the resume router vocabulary, not control flow; the wire is a
  "continue" edge.
- Validation runs every save + `Ctrl/Cmd+Enter`:
  1. `meta` exists, has outgoing wire, count of `meta` in file == 1.
     (Per-file rule — `world/` may hold several, but every `.orch` file must
       agree on one global `meta`; compiler enforces exactly one across all.)
  2. No duplicate node ids.
  3. Every wire end references a live node + legal socket.
  4. Every `conditional.end` non-empty or ghost-wired.
  5. Every `map.load` resolves to a `maps.json` map id; every map id unique.
  6. Every `run_event` slug resolves to a built event; every `entity.begin`
     references a static entity in that currently loaded map (cross-validated
     against `maps.json` entities).
  7. Every event's required return-flags are set somewhere in its own hikarin
     spine (hikarin already enforces via its compiler; orchestrator adds a
     lightweight check: if event declares `needs: [flag…]`, the invoking
     spine must have a conditional that reads it).
  8. Cycles: only through `jump`; everything else = error.
  9. Unused node with no inbound wire and no `meta` ancestry = warning.
  10. `ending` reachable but always shadowed by an unconditional edge = warning.

## 7. List ↔ canvas twin view

- `L` toggles to the vertical list (hikarin-style stacked cards) rendering the
  same graph linearized by reachability-from-`meta`. The list is a **read +
  light edit** surface (fields editable inline; add/remove via palette).
- The canonical save format is the canvas's `.orch` JSON both ways — no
  two-way diff problem; list view compiles a temporary pass.
- Purpose: accessibility, diff-friendliness in git, and power-editing without
  fighting the wires on big graphs.

## 8. Inspector (right panel)

- Pins the selected node's full detail (same fields the canvas shows inline,
  rendered big for accessibility), plus:
  - `Node id` (read-only, copy button)
  - `Wires in / out` (list; click-to-focus node on canvas)
  - Per-field help line from the verb reference (sourced from the same table
    as Section 5 — single source of truth in `docs/orchestrator-reference.md`).
- When a verb has a semantic sibling in hikarin (`conditional`), the
  inspector shows the hikarin grammar verbatim, not a re-skin.

## 9. Grid painter (maps sibling view)

- Toolbar chip: `Maps` → list of maps; new map / duplicate / rename.
- 16×16 cells (cosmetic smaller grid — switchable 8/16/32 via zoom), tile
  picker on the left sourced from `images/asset/` **flat folder** (hikarin
  convention — background flat assets stay flat).
- Brush modes: *paint*, *fill*, *marquee-fill*, *clear*, *eyedropper*.
- Collision palette tab: per-tile-type `traversable` toggle (binary, per
  locked decision) + `image` preview.
- Entity placement tab: clicked-cell drop of `gate_west`-style static entities
  (rect = hitbox in cells; default 1×1), backbone `visible_if` /
  `interact_if` strings, `event` dropdown.
- Spawn tab: player spawn cell + optional `facing` (default `down`).
- Save → `world/maps.json` (one file per project; not per map). Grid paint
  invalidates nothing in script — script is wired by id, map by id.

## 10. What Route A does NOT include

- No assets organizer (hikarin-studio asset manager untouched).
- No character graph (event flows stay in hikarin's block list unchanged).
- No multi-map world graph; maps chain only via `map.load` in script.
- No snapping smartlines, no auto-layout warnings beyond "graph too wide"
  (the fit button exists precisely for this; shrug and fit).
- No collaborative editing.

## 11. Delivery order (informational — not commitment)

1. `.orch` schema + compiler linearizer + validator (no UI; CLI compile on
   synthetic fixtures).
2. Canvas MVP: render nodes/wires from existing file, drag, rewire, delete,
   save round-trip.
3. Palette + drop + autosave wiring into studio shell; `Maps` tab with the
   painter; roster panel for events.
4. Inspector + problems panel + `L` list twin view.
5. `build/` export integration (game bundles) — last, because it is the only
   non-canvas piece.

---

*Spec only. No code has been written.*
