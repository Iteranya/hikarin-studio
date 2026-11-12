"""World orchestrator compiler.

Parses the authored graph (``world/*.orch``) into the flat, sequential action
list the runtime engine consumes. The graph is a set of nodes linked by typed
wires; the compiler linearizes it from the single ``meta`` node, resolves
labels to sequential ids, and validates every edge.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

TARGET_ORCH_KIND = "orch-graph"
ALLOWED_VERBS = {
    "meta", "label", "jump", "conditional", "map",
    "entity", "run_event", "set_world", "save", "ending",
}
OUTLET_ORDER = ("true", "false", "out")


class OrchestratorError(Exception):
    """Raised for user-facing orchestrator problems (bad graph, missing files)."""


def _outlets(verb: str) -> list[str]:
    if verb == "conditional":
        return ["true", "false"]
    if verb in ("jump", "ending"):
        return []
    return ["out"]


def compile_orch_files(files: dict[str, Any], start_name: str = "start") -> dict[str, Any]:
    """Flatten the authored ``world/*.orch`` graphs into one action list.

    Args:
        files: {file name: parsed orch dict} — the raw file contents, not blocks.
        start_name: the required label of the start node.

    Returns:
        {"actions": [...], "errors": [...], "warnings": [...]}
    """
    errors: list[str] = []
    warnings: list[str] = []
    nodes: dict[str, dict] = {}
    wires: list[dict] = []

    for name, graph in files.items():
        if not isinstance(graph, dict) or "_error" in graph:
            detail = (graph or {}).get("_error", "not valid JSON") if isinstance(graph, dict) else "not a dict"
            errors.append(f"{name}: {detail}")
            continue
        kind = graph.get("kind")
        if kind != TARGET_ORCH_KIND:
            errors.append(f'{name}: expected kind "{TARGET_ORCH_KIND}", got {kind!r}')
            continue
        for node in graph.get("nodes") or []:
            node_id = node.get("id")
            if not node_id:
                errors.append(f"{name}: a node is missing its id")
                continue
            if node_id in nodes:
                errors.append(f"{name}: duplicate node id {node_id}")
                continue
            verb = node.get("verb")
            if verb not in ALLOWED_VERBS:
                errors.append(f"{name}: node {node_id} has invalid verb {verb!r}")
                continue
            nodes[node_id] = node
        wires.extend(graph.get("wires") or [])

    if errors:
        return {"actions": [], "errors": errors, "warnings": warnings}

    # ── index the graph ─────────────────────────────────────────────────────
    out_edges: dict[tuple[str, str], list[str]] = {}
    for wire in wires:
        try:
            src_node, src_socket = wire["from"]
            dst_node, _dst_socket = wire["to"]
        except Exception:
            errors.append(f"A wire is malformed: {wire!r}")
            continue
        if src_node not in nodes:
            errors.append(f"Wire from unknown node {src_node}")
            continue
        if dst_node not in nodes:
            errors.append(f"Wire to unknown node {dst_node}")
            continue
        out_edges.setdefault((src_node, src_socket), []).append(dst_node)
    if errors:
        return {"actions": [], "errors": errors, "warnings": warnings}

    start_nodes = [n for n in nodes.values() if n["verb"] == "meta"]
    if len(start_nodes) != 1:
        errors.append(f"Expected exactly one meta node (action=start), got {len(start_nodes)}")
        return {"actions": [], "errors": errors, "warnings": warnings}
    start_node = start_nodes[0]

    labels: dict[str, str] = {}          # label name -> node id
    for node in nodes.values():
        if node["verb"] == "label":
            label = (node.get("fields") or {}).get("label")
            if not label:
                errors.append(f"Node {node['id']}: label node is missing fields.label")
                continue
            if label in labels and labels[label] != node["id"]:
                errors.append(f'Duplicate label "{label}"')
                continue
            labels[label] = node["id"]
    if errors:
        return {"actions": [], "errors": errors, "warnings": warnings}

    start_action = (start_node.get("fields") or {}).get("action")
    if start_action != "start":
        errors.append(f'Start node {start_node["id"]} has action {start_action!r}; expected "start"')
    if labels and start_name not in labels and start_name != "":
        errors.append(f'Start label "{start_name}" not found')

    # ── linearize: DFS from start, emitting in pre-order ────────────────────
    order: list[str] = []
    visited: set[str] = set()

    def walk(node_id: str) -> None:
        if node_id in visited:
            node = nodes[node_id]
            if node["verb"] != "jump":
                errors.append(f'Unhandled cycle at "{node_id}" (wire returns to a non-jump node)')
            return
        visited.add(node_id)
        order.append(node_id)
        node = nodes[node_id]
        for socket in _outlets(node["verb"]):
            for target in out_edges.get((node_id, socket), []):
                walk(target)

    walk(start_node["id"])

    unreachable = sorted(set(nodes) - set(order))
    for node_id in unreachable:
        warnings.append(f"Node {node_id} ({nodes[node_id]['verb']}) is not reachable from start; dropped")

    id_of = {node_id: i for i, node_id in enumerate(order)}

    # ── emit flat actions ───────────────────────────────────────────────────
    actions: list[dict] = []
    pending: list[tuple[dict, "str | None"]] = []

    for node_id in order:
        node = nodes[node_id]
        verb = node["verb"]
        f = node.get("fields") or {}
        action: dict[str, Any] = {"id": id_of[node_id]}

        if verb == "meta":
            action.update({"type": "meta", "action": "start"})
        elif verb == "label":
            action.update({"type": "label", "action": "label", "label": f["label"]})
        elif verb == "jump":
            target = f.get("label")
            if not target:
                errors.append(f"Node {node_id}: jump has no label target")
                continue
            if target not in labels:
                errors.append(f'Node {node_id}: jump targets unknown label "{target}"')
                continue
            action.update({"type": "transition", "action": "jump", "label": target})
        elif verb == "conditional":
            false_targets = out_edges.get((node_id, "false"), [])
            if len(false_targets) > 1:
                errors.append(f"Node {node_id}: conditional has more than one false target; routing is ambiguous")
                continue
            false_target = false_targets[0] if false_targets else None
            action.update({
                "type": "conditional",
                "action": "conditional",
                "condition": f.get("condition", "equal"),
                "var": f.get("var", ""),
                "value": f.get("value", ""),
            })
            pending.append((action, false_target))
        elif verb == "map":
            m = f.get("map")
            if not m:
                errors.append(f"Node {node_id}: map block has no map id")
            x = f.get("x", 0)
            y = f.get("y", 0)
            if not isinstance(x, int) or not isinstance(y, int):
                errors.append(f"Node {node_id}: map x/y must be integers")
            action.update({"type": "map", "action": "load", "map": m, "x": int(x), "y": int(y)})
        elif verb == "entity":
            action.update({"type": "entity", "action": "begin", "entity": f.get("entity", "")})
        elif verb == "run_event":
            action.update({"type": "run_event", "action": "run_event", "event": f.get("event", "")})
        elif verb == "set_world":
            action.update({"type": "set_world", "action": "set_world", "var": f.get("var", ""), "value": f.get("value")})
        elif verb == "save":
            action.update({"type": "save", "action": "save"})
        elif verb == "ending":
            action.update({"type": "ending", "action": "ending"})

        actions.append(action)

    # ── resolve conditional false targets to ids ────────────────────────────
    for action, false_target in pending:
        if false_target is None:
            action["end"] = action["id"] + 1
        else:
            action["end"] = id_of[false_target]

    return {"actions": actions, "errors": errors, "warnings": warnings}


def load_orch_files(directory: Path) -> dict[str, Any]:
    """Read every ``*.orch`` under a world folder; malformed files carry _error."""
    out: dict[str, Any] = {}
    for path in sorted(directory.glob("*.orch")):
        try:
            out[path.name] = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as e:
            out[path.name] = {"_error": f"not valid JSON: {e}"}
    return out
