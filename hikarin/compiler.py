"""Compiler: many .story files -> one flat JSON the Minecraft engine reads.

The engine reads a single file per character, keyed by file name (the "trigger").
Authors want many files for sanity — forty idle lines get their own tab so they
do not bury the story spine. This module merges them.

Pipeline:
    1. order files so the one holding startLabel comes first
    2. collect every label, detect duplicates
    3. emit actions with sequential ids, starting with meta/start
    4. resolve If-block label targets to the action ids the engine expects
    5. validate every jump, choice, unlock and checkpoint reference
    6. strip studio-only fields

Nothing here knows about the UI. It takes plain dicts, which makes it testable
and usable from CI without a browser.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .blocks import BUILDERS


@dataclass
class CompileResult:
    actions: list[dict] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    labels: dict[str, str] = field(default_factory=dict)  # label -> file

    @property
    def ok(self) -> bool:
        return not self.errors


def compile_project(
    project: dict[str, Any],
    files: dict[str, list[dict]],
    order: list[str] | None = None,
) -> CompileResult:
    """Compile a project.

    Args:
        project: the parsed project.json (character, startLabel, file order).
        files:   {file name: [block, ...]}, block = {"kind": str, "data": dict}
        order:   file order; defaults to project["files"] then any extras.
    """
    result = CompileResult()
    start_label = project.get("startLabel") or "start"

    names = _ordered_names(order, project, files, start_label, result)

    # ── pass 1: collect labels ──────────────────────────────────────────────
    for name in names:
        for block in files.get(name) or []:
            if block.get("kind") == "label":
                label = (block.get("data") or {}).get("name")
                if not label:
                    continue
                if label in result.labels:
                    result.errors.append(
                        f'Duplicate label "{label}" in {name} '
                        f'(already defined in {result.labels[label]})'
                    )
                else:
                    result.labels[label] = name

    if start_label not in result.labels:
        result.errors.append(
            f'Start label "{start_label}" does not exist. '
            f'Add a Label block named "{start_label}".'
        )

    # ── pass 2: emit actions with ids ───────────────────────────────────────
    actions: list[dict] = []
    pending_conditionals: list[tuple[dict, dict, str]] = []  # (action, block data, file)
    next_id = 0

    for name in names:
        for block in files.get(name) or []:
            kind = block.get("kind")
            data = block.get("data") or {}
            builder = BUILDERS.get(kind)
            if builder is None:
                result.errors.append(f'Unknown block kind "{kind}" in {name}')
                continue

            if not actions:
                actions.append({"type": "meta", "action": "start", "id": next_id})
                next_id += 1

            action = builder(data)
            action["id"] = next_id
            next_id += 1

            if action.get("type") in ("conditional", "conditional_global"):
                pending_conditionals.append((action, data, name))

            actions.append(action)

    # ── pass 3: conditional targets -> ids ──────────────────────────────────
    ids_by_label: dict[str, int] = {}
    for action in actions:
        if action.get("type") == "label":
            ids_by_label[action.get("label", "")] = action["id"]

    for action, data, name in pending_conditionals:
        target = data.get("_target") or data.get("target") or ""
        if not target:
            result.warnings.append(f"{name}: an If block has no jump target; it will fall through.")
            action["end"] = action["id"] + 1
            continue
        if target not in ids_by_label:
            suggestion = suggest(target, list(ids_by_label))
            hint = f' Did you mean "{suggestion}"?' if suggestion else ""
            result.errors.append(
                f'{name}: If block jumps to "{target}" which does not exist.{hint}'
            )
            action["end"] = action["id"] + 1
            continue
        action["end"] = ids_by_label[target]

    # ── pass 4: validate references ─────────────────────────────────────────
    known = set(result.labels)

    for action in actions:
        if action.get("type") == "transition" and action.get("action") == "jump":
            target = action.get("label")
            if not target:
                result.errors.append("A Jump block has no target.")
            elif action.get("file"):
                # Cross-file jumps resolve in the engine, not here.
                continue
            elif target not in known:
                suggestion = suggest(target, list(known))
                hint = f' Did you mean "{suggestion}"?' if suggestion else ""
                result.errors.append(f'Jump to "{target}" which does not exist.{hint}')

        elif action.get("type") == "unlock_dialogues":
            for event in action.get("events") or []:
                if event not in known:
                    result.errors.append(f'Unlock references "{event}" which is not a label.')

        elif action.get("type") in ("choice", "night_choice"):
            for choice in action.get("choice") or []:
                label = choice.get("label")
                if label not in known:
                    result.errors.append(
                        f'Choice "{choice.get("display", label)}" points at '
                        f'"{label}" which is not a label.'
                    )

        elif action.get("type") == "next":
            label = action.get("label")
            if label and label not in known:
                result.warnings.append(
                    f'Checkpoint "{label}" is not a label; it will be remembered '
                    f"but nothing jumps to it."
                )

    # ── pass 5: strip studio-only fields ────────────────────────────────────
    result.actions = [_strip(action) for action in actions]

    # sanity: ids must be 0..n-1
    for index, action in enumerate(result.actions):
        if action.get("id") != index:
            result.errors.append(f"Internal error: id mismatch at position {index}")
            break

    return result


def _ordered_names(
    order: list[str] | None,
    project: dict[str, Any],
    files: dict[str, list[dict]],
    start_label: str,
    result: CompileResult,
) -> list[str]:
    """File order for compilation: the startLabel's file goes first.

    Tab order is a reading convenience. Execution order is determined by where
    the start label lives, so a writer can reorganise tabs freely.
    """
    names = list(order or project.get("files") or files.keys())
    names = [n for n in names if n in files]
    # Include files that exist but were not listed, so nothing is silently lost.
    for extra in files:
        if extra not in names:
            names.append(extra)
            result.warnings.append(f'{extra} is not listed in project.json but was compiled.')

    holder = None
    for name in names:
        for block in files.get(name) or []:
            data = block.get("data") or {}
            if block.get("kind") == "label" and data.get("name") == start_label:
                holder = name
                break
        if holder:
            break

    if holder is None:
        result.warnings.append(
            f'No file defines the start label "{start_label}"; using file order as-is.'
        )
        return names

    return [holder] + [n for n in names if n != holder]


def _strip(action: dict) -> dict:
    """Drop editor-only keys (leading underscore) before shipping."""
    return {k: v for k, v in action.items() if not k.startswith("_")}


# ── typo suggestions ────────────────────────────────────────────────────────

def suggest(value: str, candidates: list[str]) -> str | None:
    """Find the closest label, for "did you mean" errors.

    Raw edit distance is the wrong measure: transposing a word costs a full
    block swap, so a genuine typo like "go_nihgt" vs "go_to_night" scores 5
    against an 8-character name and would be rejected. Scoring by similarity
    ratio (1 - distance / longer) with a prefix bonus matches how a human reads
    the mistake.
    """
    if not value or not candidates:
        return None

    lowered = value.lower()
    best: str | None = None
    best_score = 0.0

    for candidate in candidates:
        other = candidate.lower()
        longer = max(len(lowered), len(other))
        if longer == 0:
            continue
        ratio = 1.0 - _edit_distance(lowered, other) / longer
        prefix = lowered[: max(3, len(lowered) // 2)]
        bonus = 0.15 if other.startswith(prefix) else 0.0
        score = ratio + bonus
        if score > best_score:
            best_score = score
            best = candidate

    return best if best_score >= 0.4 else None


def _edit_distance(a: str, b: str) -> int:
    if not a:
        return len(b)
    if not b:
        return len(a)
    previous = list(range(len(b) + 1))
    for i, ca in enumerate(a, start=1):
        current = [i]
        for j, cb in enumerate(b, start=1):
            current.append(
                min(
                    previous[j] + 1,
                    current[j - 1] + 1,
                    previous[j - 1] + (0 if ca == cb else 1),
                )
            )
        previous = current
    return previous[-1]
