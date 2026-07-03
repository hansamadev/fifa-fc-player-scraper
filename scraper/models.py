"""
models.py — PlayerData dataclass for FIFAIndex FC 26 scraper.

All fields follow the requirements exactly.
`stats` and `extra_fields` are generic dicts so new attributes
added to the site are captured automatically without code changes.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class PlayerData:
    # ── Identity ─────────────────────────────────────────────
    fifaindex_id: int = 0
    name: str = ""
    full_name: Optional[str] = None
    shirt_name: Optional[str] = None
    profile_url: str = ""
    photo_url: Optional[str] = None

    # ── Ratings ──────────────────────────────────────────────
    overall: Optional[int] = None
    potential: Optional[int] = None

    # ── Personal Info ─────────────────────────────────────────
    age: Optional[int] = None
    birth_date: Optional[str] = None
    height_cm: Optional[int] = None
    weight_kg: Optional[int] = None
    preferred_foot: Optional[str] = None
    weak_foot: Optional[int] = None
    skill_moves: Optional[int] = None
    body_type: Optional[str] = None
    acceleration_type: Optional[str] = None
    international_reputation: Optional[int] = None

    # ── Positions ─────────────────────────────────────────────
    preferred_position: Optional[str] = None
    alternative_positions: List[str] = field(default_factory=list)

    # ── Club ──────────────────────────────────────────────────
    club: Optional[str] = None
    league: Optional[str] = None
    kit_number: Optional[int] = None
    club_rating: Optional[int] = None        # club card star rating (1-5)
    joined_date: Optional[str] = None
    contract_until: Optional[int] = None

    # ── National Team ─────────────────────────────────────────
    national_team: Optional[str] = None
    nationality: Optional[str] = None
    national_kit_number: Optional[int] = None
    national_rating: Optional[int] = None    # national team star rating (1-5)
    national_position: Optional[str] = None

    # ── Financial ─────────────────────────────────────────────
    market_value: Optional[str] = None       # raw string e.g. "€157.0M"
    wage: Optional[str] = None               # raw string e.g. "€610K/wk"
    release_clause: Optional[str] = None

    # ── Playstyles & Traits ──────────────────────────────────
    playstyles_plus: List[str] = field(default_factory=list)
    playstyles: List[str] = field(default_factory=list)
    personality_traits: List[str] = field(default_factory=list)

    # ── Stats (generic dict — future-proof) ───────────────────
    # Category totals AND sub-stats stored flat.
    # Keys are the exact label from the site (e.g. "Pace", "Acceleration", …)
    # New stats added to the site appear here automatically.
    stats: Dict[str, int] = field(default_factory=dict)

    # ── Extra / Unknown fields (future-proof) ─────────────────
    # Any profile field not mapped to a known attribute lands here.
    extra_fields: Dict[str, Any] = field(default_factory=dict)

    # ──────────────────────────────────────────────────────────

    def to_dict(self) -> dict:
        """Convert to a plain dict suitable for JSON serialisation."""
        return {
            "fifaindex_id": self.fifaindex_id,
            "name": self.name,
            "full_name": self.full_name,
            "shirt_name": self.shirt_name,
            "profile_url": self.profile_url,
            "photo_url": self.photo_url,
            "overall": self.overall,
            "potential": self.potential,
            "age": self.age,
            "birth_date": self.birth_date,
            "height_cm": self.height_cm,
            "weight_kg": self.weight_kg,
            "preferred_foot": self.preferred_foot,
            "weak_foot": self.weak_foot,
            "skill_moves": self.skill_moves,
            "body_type": self.body_type,
            "acceleration_type": self.acceleration_type,
            "international_reputation": self.international_reputation,
            "preferred_position": self.preferred_position,
            "alternative_positions": self.alternative_positions,
            "club": self.club,
            "league": self.league,
            "kit_number": self.kit_number,
            "club_rating": self.club_rating,
            "joined_date": self.joined_date,
            "contract_until": self.contract_until,
            "national_team": self.national_team,
            "nationality": self.nationality,
            "national_kit_number": self.national_kit_number,
            "national_rating": self.national_rating,
            "national_position": self.national_position,
            "market_value": self.market_value,
            "wage": self.wage,
            "release_clause": self.release_clause,
            "playstyles_plus": self.playstyles_plus,
            "playstyles": self.playstyles,
            "personality_traits": self.personality_traits,
            "stats": self.stats,
            "extra_fields": self.extra_fields,
        }

    def to_flat_dict(self) -> dict:
        """
        Flat representation for CSV output.
        Lists and dicts are serialised as JSON strings.
        Stats are expanded as individual columns.
        """
        d = self.to_dict()
        flat: dict = {}
        for key, val in d.items():
            if key == "stats":
                # Expand each stat as its own column
                for stat_name, stat_val in val.items():
                    flat[f"stat_{stat_name.lower().replace(' ', '_')}"] = stat_val
            elif key == "extra_fields":
                for ef_key, ef_val in val.items():
                    flat[f"extra_{ef_key.lower().replace(' ', '_')}"] = ef_val
            elif isinstance(val, (list, dict)):
                flat[key] = json.dumps(val, ensure_ascii=False)
            else:
                flat[key] = val
        return flat

