"""Block palette and action mapping.

Every block maps to exactly one action in the shipped JSON format. FORMAT.md is
the source of truth; this module is the translation layer between what the
editor shows and what the Minecraft engine reads.

The editor sends blocks as ``{"kind": "say", "data": {...}}``. The compiler
turns each into an action dict. Unknown keys in the shipped format are ignored
by the engine, and unknown block kinds are a compile error.
"""

from __future__ import annotations

from typing import Any

# ── condition vocabulary ──────────────────────────────────────────────────────
#
# The original SDK's heading for these is instructive:
#
#     def condNight(self, actions):
#         result = {"type": "conditional", "action": "conditional",
#                   "var": "Nyaaa~", "condition": "night", "actions": actions}
#
# `var` there is a literal placeholder — the author typed a cat noise because
# the field is never read. The `condition` value IS the whole test. Day and
# night take no variable and no value, exactly like `exists` takes none.
#
# `needs_var` says whether the writer has to name a variable at all.

CONDITIONS: dict[str, dict[str, Any]] = {
    "equal": {"label": "is", "needs_value": True, "needs_var": True},
    "not_equal": {"label": "is not", "needs_value": True, "needs_var": True},
    "greater_than": {"label": "is more than", "needs_value": True, "needs_var": True},
    "less_than": {"label": "is less than", "needs_value": True, "needs_var": True},
    "greater_or_equal": {"label": "is at least", "needs_value": True, "needs_var": True},
    "less_or_equal": {"label": "is at most", "needs_value": True, "needs_var": True},
    "exists": {"label": "exists", "needs_value": False, "needs_var": True},
    "not_exists": {"label": "does not exist", "needs_value": False, "needs_var": True},
    "night": {"label": "it is night", "needs_value": False, "needs_var": False},
    "day": {"label": "it is day", "needs_value": False, "needs_var": False},
}

# What the SDK writes into `var` for conditions that do not read it.
PLACEHOLDER_VAR = "Nyaaa~"

POSITIONS = [
    {"value": "CENTER", "label": "Centre"},
    {"value": "LEFT", "label": "Left"},
    {"value": "RIGHT", "label": "Right"},
    {"value": "CUSTOM", "label": "Custom grid"},
]

# Default sprite geometry, matching the engine's documented defaults:
# 16x9 screen, 4x8 frame, column 7 row 1 = centred character sprite.
SPRITE_DEFAULTS: dict[str, int] = {
    "wRatio": 16,
    "hRatio": 9,
    "wFrameRatio": 4,
    "hFrameRatio": 8,
    "column": 7,
    "row": 1,
}


def parse_literal(raw: Any) -> Any:
    """Convert an editor text value to the JSON type the engine expects.

    ``"true"`` -> True, ``"192"`` -> 192, everything else stays a string.
    Without this, a conditional comparing ``5`` to ``"5"`` silently fails.
    """
    if raw is None or isinstance(raw, (bool, int, float, dict, list)):
        return raw
    text = str(raw).strip()
    if text == "":
        return ""
    if text == "true":
        return True
    if text == "false":
        return False
    try:
        return int(text)
    except ValueError:
        pass
    try:
        return float(text)
    except ValueError:
        return text


# ── block -> action ──────────────────────────────────────────────────────────

def _to_action_say(d: dict) -> dict:
    action = {
        "type": "dialogue",
        "action": "say",
        "label": d.get("label") or "",
        "content": d.get("content") or "",
    }
    if d.get("voice"):
        action["voice"] = d["voice"]
    return action


def _to_action_choice(d: dict) -> dict:
    return {
        "type": "choice",
        "action": "choice",
        "choice": [
            {"label": c.get("label", ""), "display": c.get("display", "")}
            for c in d.get("choices") or []
        ],
    }


def _to_action_night_choice(d: dict) -> dict:
    return {
        "type": "night_choice",
        "action": "choice",
        "choice": [
            {"label": c.get("label", ""), "display": c.get("display", "")}
            for c in d.get("choices") or []
        ],
    }


def _to_action_idle(_: dict) -> dict:
    return {"type": "idle_chat", "action": "idle_chat"}


def sprite_path(character: str, outfit: str, emotion: str) -> str:
    """Build a sprite path the way the original SDK does.

    The SDK's characters.py states it plainly:

        # In minecraft, character sprite will be located in
        # textures/character.id/character.outfit/emotion.png
        # show(cupa, "happy")  ->  textures/cupa/default/happy.png

    Three levels, always: character id, outfit, emotion. Outfit is not
    optional even though the 2024 mod never shipped outfit swapping — the SDK
    author added it as groundwork so scripts would not need rewriting later.
    """
    return f"characters/{character}/{outfit}/{emotion}.png"


def _to_action_show(d: dict) -> dict:
    # A show is one of two things, and the SDK picks by argument type:
    #
    #   show_custom(cupa, "happy", ...)          <- a Character object
    #       location = characters/<id>/<outfit>/<emotion>.png
    #       sprite   = <id>                       (dyn_location also written)
    #
    #   show_custom("asset", "old-dsl", ...)     <- a plain string
    #       location = <folder>/<name>.png
    #       sprite   = <name>                     (no dyn_location)
    #
    # Both carry the same six grid numbers and both are position CUSTOM. The
    # only differences are the path shape and which name becomes the slot, so
    # this is a mode on one block rather than a separate block type.
    is_box = d.get("mode") == "box"

    sprite = d.get("sprite") or "character"
    expression = d.get("expression") or "normal"
    outfit = d.get("outfit") or "default"

    if is_box:
        # sprite holds the folder ("asset"), expression holds the file name.
        folder = d.get("folder") or "asset"
        name = d.get("image") or expression
        sprite = name  # the image name IS the slot

    # Placement is six numbers describing a rectangle on a wRatio-by-hRatio
    # grid. The original renderer turns them into pixels like this:
    #
    #   cell_w = width / wRatio
    #   cell_h = height / hRatio
    #   x      = cell_w * (column - 1)      <- 1-based, not an array index
    #   y      = cell_h * (row - 1)
    #   size   = (cell_w * wFrameRatio, cell_h * hFrameRatio)
    #
    # The named positions are only presets for those numbers; every show ships
    # all six so the engine never has to guess.
    layout = d.get("layout") if isinstance(d.get("layout"), dict) else {}
    grid = dict(SPRITE_DEFAULTS)
    for key in SPRITE_DEFAULTS:
        value = layout.get(key)
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            grid[key] = int(value)

    # The engine reads `position` only to decide whether to apply the numbers at
    # all; a preset name is cosmetic, and a hand-tuned grid is CUSTOM.
    preset = layout.get("preset") or d.get("position") or "CENTER"
    position = preset if preset in ("CENTER", "LEFT", "RIGHT") else "CUSTOM"

    location = f"{folder}/{name}.png" if is_box else sprite_path(sprite, outfit, expression)

    action = {
        "type": "show_sprite",
        "action": "show",
        "sprite": sprite,
        "location": location,
        "position": position,
        **grid,
    }

    # dyn_location lets the outfit be chosen at runtime from a variable, so a
    # character can change clothes mid-story without the script knowing which
    # folder it will be. Only a real character gets one, matching the SDK: a
    # plain image box has no outfit to swap.
    outfit_var = d.get("outfit_var")
    if outfit_var and not is_box:
        action["dyn_location"] = f"characters/{sprite}/<{outfit_var}>/{expression}.png"

    return action


def _to_action_hide(d: dict) -> dict:
    return {"type": "remove_sprite", "action": "remove", "sprite": d.get("sprite") or "character"}


def _to_action_background(d: dict) -> dict:
    return {"type": "modify_background", "action": "set", "background": d.get("background") or ""}


def _to_action_clear_background(_: dict) -> dict:
    return {"type": "clear_background", "action": "clear"}


def _to_action_label(d: dict) -> dict:
    return {"type": "label", "action": "label", "label": d.get("name") or "label"}


def _to_action_jump(d: dict) -> dict:
    """A jump is just a label.

    Tabs are an authoring convenience: every .story file is concatenated into
    one flat array before compilation, so there is a single global label
    namespace and a label in any tab is reachable from any other. A "file"
    field would imply a boundary that does not exist, and it disabled label
    validation in the compiler, so it is not emitted.
    """
    return {"type": "transition", "action": "jump", "label": d.get("target") or ""}


def _to_action_next(d: dict) -> dict:
    return {"type": "next", "action": "next", "label": d.get("target") or ""}


def _to_action_end(_: dict) -> dict:
    return {"type": "finish_dialogue", "action": "finish_dialogue"}


def _to_action_if(d: dict) -> dict:
    condition = d.get("condition") or "equal"
    spec = CONDITIONS.get(condition, {})
    needs_var = spec.get("needs_var", True)

    action: dict[str, Any] = {
        "type": "conditional",
        "action": "conditional",
        "condition": condition,
        # Day and night read no variable. The SDK writes a literal placeholder
        # ("Nyaaa~") in that slot; it is ignored by the engine, so writing the
        # same thing keeps our output byte-comparable with the source material.
        "var": (d.get("var") or "") if needs_var else PLACEHOLDER_VAR,
        # `end` is resolved to an action id in the second pass.
        "end": 0,
    }
    if d.get("scope") and needs_var:
        action["scope"] = d["scope"]
    if spec.get("needs_value"):
        action["value"] = parse_literal(d.get("value"))
    return action


def _to_action_set_var(d: dict) -> dict:
    action = {
        "type": "modify_variable",
        "action": d.get("operation") or "set",
        "var": d.get("var") or "",
        "value": parse_literal(d.get("value")),
    }
    if d.get("scope"):
        action["scope"] = d["scope"]
    return action


def _to_action_unlock(d: dict) -> dict:
    return {
        "type": "unlock_dialogues",
        "action": "unlock_dialogues",
        "events": list(d.get("labels") or []),
    }


def _to_action_give_item(d: dict) -> dict:
    return {
        "type": "give_item",
        "action": "give",
        "item": d.get("item") or "",
        "amount": int(d.get("amount") or 1),
    }


def _to_action_take_item(d: dict) -> dict:
    return {
        "type": "take_item",
        "action": "take",
        "item": d.get("item") or "",
        "amount": int(d.get("amount") or 1),
    }


def _to_action_music(d: dict) -> dict:
    return {"type": "play_music", "action": "play_music", "music": d.get("music") or None}


def _to_action_sound(d: dict) -> dict:
    return {"type": "play_sound", "action": "play_sound", "sound": d.get("sound") or ""}


def _to_action_command(d: dict) -> dict:
    return {"type": "command", "action": d.get("command") or ""}


BUILDERS = {
    "say": _to_action_say,
    "choice": _to_action_choice,
    "nightChoice": _to_action_night_choice,
    "idle": _to_action_idle,
    "show": _to_action_show,
    "hide": _to_action_hide,
    "background": _to_action_background,
    "clearBackground": _to_action_clear_background,
    "label": _to_action_label,
    "jump": _to_action_jump,
    "if": _to_action_if,
    "next": _to_action_next,
    "end": _to_action_end,
    "setVar": _to_action_set_var,
    "unlock": _to_action_unlock,
    "giveItem": _to_action_give_item,
    "takeItem": _to_action_take_item,
    "music": _to_action_music,
    "sound": _to_action_sound,
    "command": _to_action_command,
}

# ── action -> block (for loading a shipped JSON back into the editor) ────────

FROM_ACTION = {
    "dialogue": "say",
    "choice": "choice",
    "night_choice": "nightChoice",
    "idle_chat": "idle",
    "show_sprite": "show",
    "remove_sprite": "hide",
    "modify_background": "background",
    "clear_background": "clearBackground",
    "label": "label",
    "transition": "jump",
    "conditional": "if",
    "conditional_global": "if",
    "next": "next",
    "finish_dialogue": "end",
    "modify_variable": "setVar",
    "modify_global": "setVar",
    "unlock_dialogues": "unlock",
    "give_item": "giveItem",
    "take_item": "takeItem",
    "play_music": "music",
    "play_sound": "sound",
}


def block_from_action(action: dict) -> dict | None:
    """Turn a shipped action back into an editor block, or None if unsupported.

    Round-tripping matters: opening a compiled JSON in the studio should not
    lose the story. Studio-only hints (a conditional's target label) cannot be
    recovered from an id, so they come back empty and the writer re-points them.
    """
    kind = FROM_ACTION.get(action.get("type", ""))
    if kind is None:
        return None

    t = action.get("type")
    if kind == "say":
        return {"kind": kind, "data": {"label": action.get("label", ""), "content": action.get("content", ""),
                                       "voice": action.get("voice")}}
    if kind in ("choice", "nightChoice"):
        return {"kind": kind, "data": {"choices": action.get("choice") or []}}
    if kind == "show":
        location = action.get("location") or ""
        parts = location.split("/")
        layout = {
            "preset": action.get("position", "CENTER"),
            **{k: action[k] for k in SPRITE_DEFAULTS if k in action},
        }

        is_character = parts and parts[0] == "characters"

        if not is_character:
            # A plain image box: <folder>/<file>.png, slot name is the file.
            folder = parts[0] if len(parts) >= 2 else "asset"
            filename = parts[-1] if parts else location
            return {
                "kind": kind,
                "data": {
                    "mode": "box",
                    "folder": folder,
                    "image": filename.removesuffix(".png"),
                    "layout": layout,
                },
            }

        # characters/<id>/<outfit>/<emotion>.png
        if len(parts) >= 4:
            character, outfit, filename = parts[1], parts[2], parts[-1]
        else:
            character, outfit, filename = (parts[1] if len(parts) > 1 else "character"), "default", parts[-1]

        data = {
            "mode": "character",
            "sprite": action.get("sprite") or character,
            "outfit": outfit,
            "expression": filename.removesuffix(".png") or "normal",
            "layout": layout,
        }

        # Recover the variable name from "characters/<id>/<var>/<emotion>.png".
        dyn = action.get("dyn_location") or ""
        if "<" in dyn:
            data["outfit_var"] = dyn.split("<", 1)[1].split(">", 1)[0]

        return {"kind": kind, "data": data}
    if kind == "hide":
        return {"kind": kind, "data": {"sprite": action.get("sprite", "character")}}
    if kind == "background":
        return {"kind": kind, "data": {"background": action.get("background", "")}}
    if kind == "label":
        return {"kind": kind, "data": {"name": action.get("label", "")}}
    if kind == "jump":
        return {"kind": kind, "data": {"target": action.get("label", "")}}
    if kind == "if":
        data = {
            "scope": action.get("scope"),
            "var": action.get("var", ""),
            "condition": action.get("condition", "equal"),
            "value": action.get("value"),
            # Cannot recover a label from an id; the editor flags this.
            "_target": "",
            "_unresolved_target_id": action.get("end"),
        }
        return {"kind": kind, "data": data}
    if kind == "next":
        return {"kind": kind, "data": {"target": action.get("label", "")}}
    if kind == "setVar":
        return {"kind": kind, "data": {
            "scope": action.get("scope"),
            "var": action.get("var", ""),
            "operation": action.get("action", "set"),
            "value": action.get("value"),
        }}
    if kind == "unlock":
        return {"kind": kind, "data": {"labels": action.get("events") or []}}
    if kind in ("giveItem", "takeItem"):
        return {"kind": kind, "data": {"item": action.get("item", ""), "amount": action.get("amount", 1)}}
    if kind == "music":
        return {"kind": kind, "data": {"music": action.get("music")}}
    if kind == "sound":
        return {"kind": kind, "data": {"sound": action.get("sound", "")}}
    if kind == "idle" or kind == "end" or kind == "clearBackground":
        return {"kind": kind, "data": {}}
    return None
