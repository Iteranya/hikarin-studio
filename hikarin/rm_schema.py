"""Resource Management schema: the primitives every system is made of.

The studio's promise for visual novels is "no hand-written JSON, no ids, labels
all the way through". The resource management layer makes the same promise for
the systems around the story: currencies, generators, recipes, expeditions,
tech trees, assignments. Everything is one of these primitives::

    Resource    a named value with a cap            gold, mana, affection
    Generator   produces resources over time         mine, factory, aura node
    Converter   transforms resources into resources  smelter, workshop
    Assignable  puts a thing into a slot and        worker, hero, module
                modifies a generator/converter
    Node        a point on a map or tree            expedition, tech node
    Event       a random outcome for a node         combat skirmish, cache
    Requirement a gate: "you need X to do Y"        tech, resources, tags
    Effect      a mutation: "when X, change Y"      add, unlock, set flag

A project's RM data lives in ``resource_management.json`` next to
``variables.json``. The two are deliberately not the same file: variables are
the VN's scratch state, the RM schema is the game's economy, and coupling them
is how one ends up rewritten by accident. They meet at one seam — a Resource
flagged ``visible_to_vn`` is *also* exported into the variables registry, so the
story editor sees it as an ordinary global and the engine cannot tell the
difference. That sync lives in :mod:`hikarin.resource_management`, not here.

This module is models and validation only. It does not read or write files.
"""

from __future__ import annotations

import re
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator, model_validator

RESOURCE_ID_RE = re.compile(r"^[a-z][a-z0-9_-]{0,63}$")
HEX_COLOR_RE = re.compile(r"^#(?:[0-9a-fA-F]{3}|[0-9a-fA-F]{6})$")
VN_NAME_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_.]{0,63}$")

NAME_RE = VN_NAME_RE  # re-exported for symmetry with variables.py

REQUIREMENT_TYPES = (
    "resource",        # {"resource": id, "amount": n, "op"?: ">="|"=="|"<="}
    "tag",             # {"tag": name, "count"?: n}
    "tech",            # {"tech": tech_node_id}
    "generator_level", # {"generator": id, "level": n}
    "flag",            # {"flag": name, "scope"?: "global"|"local", "value"?: any}
    "assignable",      # {"assignable": id} or {"assignable": id, "min_level"?: n}
    "time",            # {"hour": n} or {"from": n, "to": n} — 0..23
    "custom",          # {"key": name, "data"?: {...}}
)

EFFECT_TYPES = (
    "add_resource",    # {"resource": id, "amount": n}
    "multiply_output", # {"target": id, "mult": float} — generator or converter
    "unlock",          # {"target_type": "generator"|"converter"|"node"|"tech"|"event", "target": id}
    "set_flag",        # {"flag": name, "scope"?: "global"|"local", "value": any}
    "add_tag",         # {"assignable": id, "tag": name}
    "trigger_event",   # {"event": event_id, "data"?: {...}}
    "custom",          # {"key": name, "data"?: {...}}
)

NODE_TYPES = ("expedition", "encounter", "location", "story", "trade")


# ── leaves ──────────────────────────────────────────────────────────────────


class Requirement(BaseModel):
    """A gate. ``type`` picks the vocabulary, ``data`` carries the operands."""

    type: Literal[
        "resource", "tag", "tech", "generator_level", "flag", "assignable", "time", "custom"
    ]
    data: dict[str, Any] = Field(default_factory=dict)


class Effect(BaseModel):
    """A mutation, optionally conditioned on requirements."""

    type: Literal[
        "add_resource", "multiply_output", "unlock", "set_flag", "add_tag",
        "trigger_event", "custom",
    ]
    data: dict[str, Any] = Field(default_factory=dict)
    conditions: list[Requirement] = Field(default_factory=list)


class AssignmentBonus(BaseModel):
    """What a tag does to a generator or converter it is assigned to.

    All multipliers are multiplicative against the level's base values.
    ``stat_mods`` is an open dict so the game can define its own vocabulary
    (atk, def, aura_affinity, ...) without the schema knowing it.
    """

    output_mult: float = 1.0
    efficiency_mult: float = 1.0  # >1 means the same effect at lower upkeep
    speed_mult: float = 1.0      # for converters: craft time divides by this
    quality_bonus: float = 0.0   # additive chance of a bonus-output roll
    stat_mods: dict[str, float] = Field(default_factory=dict)
    special_key: str | None = None  # custom callback the game implements
    conditions: list[Requirement] = Field(default_factory=list)


class ChanceReward(BaseModel):
    resource: str
    probability: float = Field(ge=0.0, le=1.0)
    amount: float = Field(default=1.0, gt=0.0)


# ── resources ───────────────────────────────────────────────────────────────


class ResourceDef(BaseModel):
    id: str
    name: str
    base_cap: float = Field(default=999999, ge=0.0)
    resource_type: Literal["integer", "decimal", "boolean"] = "integer"
    color: str = "#FFFFFF"
    icon: str = "circle"
    description: str = ""
    show_in_hud: bool = False
    format_string: str = "{value} {icon}"
    # VN integration. A VN-visible resource is the *same value* everywhere: the
    # VN sees it as a declared global (scope WORLD when vn_scope is GLOBAL), and
    # the RM runtime owns the number. They are one variable with two editors.
    visible_to_vn: bool = False
    vn_scope: Literal["GLOBAL", "LOCAL"] = "GLOBAL"
    vn_name: str = ""  # defaults to the resource id when empty

    @field_validator("id")
    @classmethod
    def _id_slug(cls, v: str) -> str:
        v = v.strip().lower()
        if not RESOURCE_ID_RE.match(v):
            raise ValueError(
                f"{v!r} is not a usable resource id. Start with a letter; "
                "lowercase letters, digits, - and _ only."
            )
        return v

    @field_validator("color")
    @classmethod
    def _hex(cls, v: str) -> str:
        if not HEX_COLOR_RE.match(v or ""):
            raise ValueError(f"{v!r} is not a #rgb or #rrggbb colour.")
        return v.upper() if len(v) == 7 else v

    @field_validator("vn_name")
    @classmethod
    def _vn_name_ok(cls, v: str) -> str:
        v = v.strip()
        if v and not VN_NAME_RE.match(v):
            raise ValueError(
                f"{v!r} is not a usable VN variable name. Letters, numbers, _ "
                "and . only, and it cannot start with a digit."
            )
        return v

    @model_validator(mode="after")
    def _default_vn_name(self) -> "ResourceDef":
        if self.visible_to_vn and not self.vn_name:
            candidate = self.id.replace("-", "_")
            if not VN_NAME_RE.match(candidate):
                raise ValueError(
                    f"Resource id {self.id!r} cannot become a VN variable name; "
                    "set vn_name explicitly."
                )
            self.vn_name = candidate
        return self


# ── generators / converters ─────────────────────────────────────────────────


def _slug(v: str, what: str) -> str:
    v = v.strip().lower()
    if not RESOURCE_ID_RE.match(v):
        raise ValueError(
            f"{v!r} is not a usable {what} id. Start with a letter; lowercase "
            "letters, digits, - and _ only."
        )
    return v


class GeneratorLevel(BaseModel):
    level: int = Field(ge=1)
    cost: dict[str, float] = Field(default_factory=dict)
    output: dict[str, float] = Field(default_factory=dict)
    upkeep: dict[str, float] = Field(default_factory=dict)
    unlocks: list[str] = Field(default_factory=list)
    requirements: list[Requirement] = Field(default_factory=list)

    @field_validator("cost", "output", "upkeep", mode="before")
    @classmethod
    def _non_negative(cls, v: Any) -> Any:
        if isinstance(v, dict):
            return {str(k): float(x) for k, x in v.items() if float(x) >= 0}
        return v


class GeneratorDef(BaseModel):
    id: str
    name: str
    description: str = ""
    category: str = "general"
    slots: int = Field(default=1, ge=0, le=100)
    levels: list[GeneratorLevel] = Field(default_factory=list, min_length=1)
    assignment_bonuses: dict[str, AssignmentBonus] = Field(default_factory=dict)
    requirements: list[Requirement] = Field(default_factory=list)
    grid_x: int | None = None
    grid_y: int | None = None

    @field_validator("id")
    @classmethod
    def _id_slug(cls, v: str) -> str:
        return _slug(v, "generator")

    @model_validator(mode="after")
    def _levels_sane(self) -> "GeneratorDef":
        seen = [lv.level for lv in self.levels]
        if len(seen) != len(set(seen)):
            raise ValueError(f"Generator {self.id!r} has duplicate level numbers.")
        self.levels.sort(key=lambda lv: lv.level)
        return self


class Recipe(BaseModel):
    id: str
    name: str
    inputs: dict[str, float] = Field(default_factory=dict)
    outputs: dict[str, float] = Field(default_factory=dict)
    duration: float = Field(default=1.0, gt=0.0)  # in ticks
    chance_bonus: dict[str, float] = Field(default_factory=dict)  # resource → chance
    requirements: list[Requirement] = Field(default_factory=list)

    @field_validator("id")
    @classmethod
    def _id_slug(cls, v: str) -> str:
        return _slug(v, "recipe")


class ConverterDef(BaseModel):
    id: str
    name: str
    description: str = ""
    category: str = "general"
    slots: int = Field(default=1, ge=0, le=100)
    recipes: list[Recipe] = Field(default_factory=list)
    assignment_bonuses: dict[str, AssignmentBonus] = Field(default_factory=dict)
    requirements: list[Requirement] = Field(default_factory=list)
    grid_x: int | None = None
    grid_y: int | None = None

    @field_validator("id")
    @classmethod
    def _id_slug(cls, v: str) -> str:
        return _slug(v, "converter")


# ── assignables ─────────────────────────────────────────────────────────────


class AssignableDef(BaseModel):
    id: str
    name: str
    description: str = ""
    tags: list[str] = Field(default_factory=list)
    base_stats: dict[str, float] = Field(default_factory=dict)
    source: Literal["vn_character", "manual", "procedural"] = "manual"
    vn_character_slug: str | None = None

    @field_validator("id")
    @classmethod
    def _id_slug(cls, v: str) -> str:
        return _slug(v, "assignable")


# ── nodes / events / tech tree ──────────────────────────────────────────────


class NodeDef(BaseModel):
    id: str
    name: str
    description: str = ""
    node_type: Literal["expedition", "encounter", "location", "story", "trade"] = "expedition"
    x: float = 0.0
    y: float = 0.0
    requirements: list[Requirement] = Field(default_factory=list)
    duration: float = Field(default=0.0, ge=0.0)  # seconds; 0 = instant
    rewards: dict[str, float] = Field(default_factory=dict)
    chance_rewards: list[ChanceReward] = Field(default_factory=list)
    event_pool: list[str] = Field(default_factory=list)
    vn_label: str | None = None  # story nodes: label to jump to on completion
    connects_to: list[str] = Field(default_factory=list)

    @field_validator("id")
    @classmethod
    def _id_slug(cls, v: str) -> str:
        return _slug(v, "node")


class EventDef(BaseModel):
    id: str
    name: str
    description: str = ""
    weight: float = Field(default=1.0, gt=0.0)
    requirements: list[Requirement] = Field(default_factory=list)
    effects: list[Effect] = Field(default_factory=list)

    @field_validator("id")
    @classmethod
    def _id_slug(cls, v: str) -> str:
        return _slug(v, "event")


class TechNodeDef(BaseModel):
    id: str
    name: str
    description: str = ""
    cost: dict[str, float] = Field(default_factory=dict)
    requirements: list[Requirement] = Field(default_factory=list)
    unlocks: list[str] = Field(default_factory=list)
    effects: list[Effect] = Field(default_factory=list)
    x: float = 0.0
    y: float = 0.0

    @field_validator("id")
    @classmethod
    def _id_slug(cls, v: str) -> str:
        return _slug(v, "tech")


# ── the schema itself ───────────────────────────────────────────────────────


class ResourceManagementSchema(BaseModel):
    version: int = 1
    tick_rate_hz: float = Field(default=1.0, gt=0.0, le=60.0)
    max_offline_hours: float = Field(default=24.0, ge=0.0)

    resources: list[ResourceDef] = Field(default_factory=list)
    generators: list[GeneratorDef] = Field(default_factory=list)
    converters: list[ConverterDef] = Field(default_factory=list)
    assignables: list[AssignableDef] = Field(default_factory=list)
    nodes: list[NodeDef] = Field(default_factory=list)
    events: list[EventDef] = Field(default_factory=list)
    tech_nodes: list[TechNodeDef] = Field(default_factory=list)


def _dupes(items: list[Any], what: str) -> list[str]:
    seen: set[str] = set()
    problems: list[str] = []
    for item in items:
        if item.id in seen:
            problems.append(f"{what} {item.id!r} is defined twice")
        seen.add(item.id)
    return problems


def validate_schema(schema: ResourceManagementSchema) -> list[str]:
    """Every cross-reference check the model types cannot do.

    Returns a list of human-readable problems; empty means the schema is
    coherent. Pydantic catches shape; this catches meaning.
    """
    problems: list[str] = []

    problems += _dupes(schema.resources, "Resource")
    problems += _dupes(schema.generators, "Generator")
    problems += _dupes(schema.converters, "Converter")
    problems += _dupes(schema.assignables, "Assignable")
    problems += _dupes(schema.nodes, "Node")
    problems += _dupes(schema.events, "Event")
    problems += _dupes(schema.tech_nodes, "Tech node")

    resource_ids = {r.id for r in schema.resources}
    generator_ids = {g.id for g in schema.generators}
    converter_ids = {c.id for c in schema.converters}
    node_ids = {n.id for n in schema.nodes}
    event_ids = {e.id for e in schema.events}
    tech_ids = {t.id for t in schema.tech_nodes}
    assignable_ids = {a.id for a in schema.assignables}
    # Anything a level or a tech node is allowed to unlock.
    unlock_targets = generator_ids | converter_ids | node_ids | tech_ids | event_ids

    def check_cost(cost: dict[str, float], where: str) -> None:
        for rid in cost:
            if rid not in resource_ids:
                problems.append(f"{where} costs unknown resource {rid!r}")

    def check_output(out: dict[str, float], where: str) -> None:
        for rid in out:
            if rid not in resource_ids:
                problems.append(f"{where} produces/consumes unknown resource {rid!r}")

    def check_requirements(reqs: list[Requirement], where: str) -> None:
        for i, req in enumerate(reqs, 1):
            d = req.data
            if req.type == "resource":
                rid = str(d.get("resource") or "")
                if rid not in resource_ids:
                    problems.append(f"{where} requirement #{i}: unknown resource {rid!r}")
            elif req.type == "tech":
                tid = str(d.get("tech") or "")
                if tid not in tech_ids:
                    problems.append(f"{where} requirement #{i}: unknown tech {tid!r}")
            elif req.type == "generator_level":
                gid = str(d.get("generator") or "")
                if gid not in generator_ids:
                    problems.append(f"{where} requirement #{i}: unknown generator {gid!r}")
            elif req.type == "assignable":
                aid = str(d.get("assignable") or "")
                if aid and aid not in assignable_ids:
                    problems.append(f"{where} requirement #{i}: unknown assignable {aid!r}")
            # tag/flag/time/custom are intentionally open: games define their own.

    def check_effects(effects: list[Effect], where: str) -> None:
        for i, eff in enumerate(effects, 1):
            d = eff.data
            if eff.type == "add_resource":
                rid = str(d.get("resource") or "")
                if rid not in resource_ids:
                    problems.append(f"{where} effect #{i}: unknown resource {rid!r}")
            elif eff.type == "unlock":
                target = str(d.get("target") or "")
                if target and target not in unlock_targets:
                    problems.append(f"{where} effect #{i}: unknown unlock target {target!r}")
            elif eff.type == "multiply_output":
                target = str(d.get("target") or "")
                if target and target not in generator_ids | converter_ids:
                    problems.append(f"{where} effect #{i}: unknown target {target!r}")
            elif eff.type == "trigger_event":
                eid = str(d.get("event") or "")
                if eid and eid not in event_ids:
                    problems.append(f"{where} effect #{i}: unknown event {eid!r}")
            check_requirements(eff.conditions, f"{where} effect #{i}")

    def check_bonuses(bonuses: dict[str, AssignmentBonus], where: str) -> None:
        for tag, bonus in bonuses.items():
            check_requirements(bonus.conditions, f"{where} bonus for tag {tag!r}")

    for gen in schema.generators:
        where = f"Generator {gen.id!r}"
        check_requirements(gen.requirements, where)
        check_bonuses(gen.assignment_bonuses, where)
        for lv in gen.levels:
            check_cost(lv.cost, f"{where} level {lv.level}")
            check_output(lv.output, f"{where} level {lv.level}")
            check_output(lv.upkeep, f"{where} level {lv.level}")
            check_requirements(lv.requirements, f"{where} level {lv.level}")
            for target in lv.unlocks:
                if target not in unlock_targets:
                    problems.append(f"{where} level {lv.level} unlocks unknown id {target!r}")

    for conv in schema.converters:
        where = f"Converter {conv.id!r}"
        check_requirements(conv.requirements, where)
        check_bonuses(conv.assignment_bonuses, where)
        for recipe in conv.recipes:
            check_output(recipe.inputs, f"{where} recipe {recipe.id!r}")
            check_output(recipe.outputs, f"{where} recipe {recipe.id!r}")
            check_output(recipe.chance_bonus, f"{where} recipe {recipe.id!r}")
            check_requirements(recipe.requirements, f"{where} recipe {recipe.id!r}")

    for node in schema.nodes:
        where = f"Node {node.id!r}"
        check_requirements(node.requirements, where)
        check_output(node.rewards, where)
        for cr in node.chance_rewards:
            if cr.resource not in resource_ids:
                problems.append(f"{where} chance reward: unknown resource {cr.resource!r}")
        for eid in node.event_pool:
            if eid not in event_ids:
                problems.append(f"{where} event pool: unknown event {eid!r}")
        for target in node.connects_to:
            if target not in node_ids:
                problems.append(f"{where} connects to unknown node {target!r}")

    for ev in schema.events:
        check_requirements(ev.requirements, f"Event {ev.id!r}")
        check_effects(ev.effects, f"Event {ev.id!r}")

    for tech in schema.tech_nodes:
        where = f"Tech {tech.id!r}"
        check_cost(tech.cost, where)
        check_requirements(tech.requirements, where)
        check_effects(tech.effects, where)
        for target in tech.unlocks:
            if target not in unlock_targets:
                problems.append(f"{where} unlocks unknown id {target!r}")

    # A VN-visible resource leaks its vn_name into the variables registry; two
    # resources claiming the same name would silently shadow each other there.
    vn_names: dict[str, str] = {}
    for res in schema.resources:
        if not res.visible_to_vn:
            continue
        name = res.vn_name or res.id
        if name in vn_names:
            problems.append(
                f"Resources {vn_names[name]!r} and {res.id!r} both export to VN "
                f"variable {name!r}"
            )
        vn_names[name] = res.id

    # Reachability from roots: a tech node or node that nothing unlocks and
    # nothing connects to can never be reached. Info-level, still a problem
    # worth reporting — the author meant to wire it up.
    reachable: set[str] = set()

    seeds = (
        {g.id for g in schema.generators if not g.requirements}
        | {c.id for c in schema.converters if not c.requirements}
        | {t.id for t in schema.tech_nodes if not t.requirements}
        | {n.id for n in schema.nodes if not n.requirements}
    )
    pending = list(seeds)
    while pending:
        current = pending.pop()
        if current in reachable:
            continue
        reachable.add(current)
        outgoing: list[str] = []
        for tech in schema.tech_nodes:
            if tech.id == current:
                outgoing += tech.unlocks
                outgoing += [
                    str(eff.data["target"])
                    for eff in tech.effects
                    if eff.type == "unlock" and eff.data.get("target")
                ]
        for gen in schema.generators:
            if gen.id == current:
                for lv in gen.levels:
                    outgoing += lv.unlocks
        for node in schema.nodes:
            if node.id == current:
                outgoing += node.connects_to
        pending += outgoing

    locked = (
        (tech_ids | generator_ids | converter_ids | node_ids) - reachable
    )
    for item in sorted(locked):
        problems.append(
            f"{item!r} is unreachable: nothing you can build unlocks it (warning)"
        )

    return problems


def is_clean(problems: list[str]) -> bool:
    """Errors block export; entries tagged (warning) do not."""
    return not any("(warning)" not in p for p in problems)
