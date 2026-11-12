# Orchestrator — universal verbs (ground truth for the compiler)

The verb set is **wholly separate** from hikarin's dialogue vocabulary. Structural
ideas are shared (labels, sequential ids, composed `.orch` files), never the
noun-set. See `docs/game-orchestrator.md` for the engine-agnostic framing.

| verb | `type` in `game.json` | required fields | notes |
|---|---|---|---|
| `meta` | `meta` | `action: start` | exactly one per game project; `id: 0` |
| `label` | `label` | `label` | jump target |
| `jump` | `transition` | `action: jump`, `label` | |
| `conditional` | `conditional` | `condition`, `var` (`@world.` or bare, mapped), `value`, `end` | hikarin grammar; **route selector only** |
| `map` | `map` | `map`, `x`, `y` | player position restore |
| `entity` | `entity` | `entity` | arm interact handoff |
| `run_event` | `run_event` | `event` (slug) | blocks; hikarin runs full spine; returns |
| `set_world` | `set_world` | `var`, `value` | `@world.*` write channel |
| `save` | `save` | - | flush profile |
| `ending` | `ending` | - | terminal |

`conditional.end` is resolved to the id of the first node reached on the false
branch (fall-through = pass), so order in the flat array cannot break routing.

## `.orch` file shape (editable by canvas; load tolerantly)

```json
{
  "kind": "orch-graph",
  "start": "n_0001",
  "nodes": [ { "id": "n_0001", "verb": "meta", "fields": {...}, "at": [0,0] } ],
  "wires": [ { "from": ["n_0001", "out"], "to": ["n_0002", "in"] } ]
}
```

Ids are `n_` + 4-digit local. Wires reference node ids. Cycles legal via `jump`.
