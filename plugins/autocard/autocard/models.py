from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


Number = int | float


@dataclass(slots=True)
class Weapon:
    name: str
    skill: str = ""
    value: Number | None = None
    damage: str = ""
    notes: str = ""


@dataclass(slots=True)
class PokemonMove:
    name: str
    category: str = ""
    element: str = ""
    accuracy: str = ""
    damage: str = ""
    range: str = ""
    ep_cost: Number | None = None
    priority: Number | None = None
    effect: str = ""


@dataclass(slots=True)
class PokemonCompanion:
    name: str
    species: str = ""
    gender: str = ""
    types: list[str] = field(default_factory=list)
    ability: str = ""
    held_item: str = ""
    status: str = ""
    bond: Number | None = None
    hp: Number | None = None
    hpmax: Number | None = None
    ep: Number | None = None
    stats: dict[str, Number] = field(default_factory=dict)
    moves: list[PokemonMove] = field(default_factory=list)
    features: list[str] = field(default_factory=list)
    backstory: str = ""
    portrait: bytes | None = field(default=None, repr=False)
    portrait_mime: str = ""
    # Kept after the original fields so positional callers remain compatible.
    accuracy: Number | None = None
    evasion: Number | None = None
    stat_modifiers: dict[str, Number] = field(default_factory=dict)


@dataclass(slots=True)
class Character:
    source_filename: str
    source_format: str
    rule: str
    seal_system: str
    template_id: str
    template_name: str
    layout: str
    name: str = "未命名角色"
    player: str = ""
    identity: dict[str, str] = field(default_factory=dict)
    attributes: dict[str, Number] = field(default_factory=dict)
    skills: dict[str, Number] = field(default_factory=dict)
    skill_formulas: dict[str, str] = field(default_factory=dict)
    saving_throw_factors: dict[str, Number] = field(default_factory=dict)
    weapons: list[Weapon] = field(default_factory=list)
    armor: list[str] = field(default_factory=list)
    items: list[str] = field(default_factory=list)
    spells: list[str] = field(default_factory=list)
    feats: list[str] = field(default_factory=list)
    features: list[str] = field(default_factory=list)
    pokemon: list[PokemonCompanion] = field(default_factory=list)
    backstory: str = ""
    portrait: bytes | None = field(default=None, repr=False)
    portrait_mime: str = ""
    warnings: list[str] = field(default_factory=list)
    # Pokémon trainer cards keep SealDice's writable modifiers in
    # ``attributes`` and retain the sheet's raw ability scores separately.
    attribute_scores: dict[str, Number] = field(default_factory=dict)

    @property
    def write_count(self) -> int:
        return len(self.attributes) + len(self.skills) + len(self.saving_throw_factors)

    def to_dict(self, *, include_portrait: bool = False) -> dict[str, Any]:
        value = asdict(self)
        if not include_portrait:
            value.pop("portrait", None)
            value.pop("portrait_mime", None)
            for companion in value.get("pokemon", []):
                companion.pop("portrait", None)
                companion.pop("portrait_mime", None)
        return value

    def preview(self) -> dict[str, Any]:
        if self.rule == "COC7":
            core_order = ["外貌", "体质", "敏捷", "教育", "智力", "幸运", "意志", "体型", "力量"]
        elif self.rule == "POKEMON-TRPG":
            core_order = ["力量", "体魄", "智识", "意念", "机敏", "魅力", "幸运"]
        elif self.seal_system == "story":
            core_order = []
        else:
            core_order = ["力量", "敏捷", "体质", "智力", "感知", "魅力"]
        return {
            "name": self.name,
            "rule": self.rule,
            "layout": self.layout,
            "core_attributes": {key: self.attributes.get(key, 0) for key in core_order},
            "skill_count": len(self.skills),
            "pokemon_count": len(self.pokemon),
            "write_count": self.write_count,
        }
