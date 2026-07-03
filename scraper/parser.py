"""
parser.py — FIFAIndex FC 26 player page parser.

Exact DOM patterns from diagnostic.py (live site, June 2026):

bg-card cards with h3 headers (ALL UPPERCASE):
  "PROFILE"        → profile fields (Preferred Foot, Skill Moves, etc.)
  "SPECIALITIES"   → specialty tags (#Poacher, etc.)
  "CLUB"           → club info (Real Madrid, league link, kit, joined, contract)
  "NATIONAL TEAM"  → national team info
  "ROLES"          → role links /roles/*/fc26
  "TRAITS & PLAYSTYLES" → h4 sub-sections: PLAYSTYLES+, PLAYSTYLES, PERSONALITY TRAITS
  "CAREER HISTORY" → skip

bg-card cards with h4 headers (stat cards, also uppercase):
  "PACE", "SHOOTING", "PASSING", "DRIBBLING", "DEFENDING", "PHYSICAL", "GOALKEEPING", etc.
  Sub-rows in div.space-y-1 > div.flex.items-center.gap-2

Club card extra structure:
  - Team logo img
  - Club name: a[href="/teams/..."] .text-foreground
  - League: a[href="/leagues/..."] .text-muted-foreground
  - Field rows: div.mt-3.space-y-1.5 > div.flex.justify-between:
      span.text-muted-foreground (label) + value

Stars: SVG with class "lucide-star" (count filled stars)
PlayStyles: a[href="/traits/*/fc26"] — innerText is the badge name
"""
from __future__ import annotations

import logging
import re
from typing import Any, Dict, List, Optional

from bs4 import BeautifulSoup, NavigableString, Tag

from .models import PlayerData
from .utils import ensure_absolute, extract_player_id, parse_height, parse_int, parse_weight

logger = logging.getLogger(__name__)
BASE_URL = "https://www.fifaindex.com"

# ── Helpers ───────────────────────────────────────────────────────────────────

def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "").strip().lower())

def _text(el) -> str:
    if el is None: return ""
    if isinstance(el, str): return re.sub(r"\s+", " ", el.strip())
    return re.sub(r"\s+", " ", el.get_text(" ", strip=True))

def _count_filled_stars(tag: Tag) -> int:
    """Count filled star SVG elements by checking for 'fill-' inside class names."""
    count = 0
    for svg in tag.find_all("svg"):
        cls = " ".join(svg.get("class") or [])
        if "lucide-star" in cls:
            if "fill-" in cls:
                count += 1
    return count

POS_RE = re.compile(
    r"^(GK|SW|RWB|RB|RCB|CB|LCB|LB|LWB|CDM|RCM|CM|LCM|CAM|"
    r"RAM|LAM|RM|RW|RF|CF|LF|LW|LM|RS|ST|LS|RES|SUB)$"
)

# ── Known profile labels → PlayerData field ───────────────────────────────────
PROFILE_LABELS: Dict[str, str] = {
    "preferred foot": "preferred_foot",
    "weak foot": "weak_foot",
    "skill moves": "skill_moves",
    "body type": "body_type",
    "acceleration type": "acceleration_type",
    "accelerate type": "acceleration_type",
    "international rep.": "international_reputation",
    "international rep": "international_reputation",
    "international reputation": "international_reputation",
    "full name": "full_name",
    "shirt name": "shirt_name",
    "birth date": "birth_date",
    "date of birth": "birth_date",
    "nationality": "nationality",
    "release clause": "release_clause",
    "positions": "positions_raw",
}

# Real Face is not a stat. Work Rate and Body Type are not requested.
IGNORED_LABELS: set[str] = {
    "real face",
    "work rate",
    "attack work rate",
    "defense work rate",
    "defensive work rate",
}


# ── Main entry ────────────────────────────────────────────────────────────────

def parse_player(html: str, page_url: str) -> PlayerData:
    """Parse a fully-rendered FIFAIndex player page and return PlayerData."""
    soup = BeautifulSoup(html, "html.parser")
    player = PlayerData()
    player.profile_url = page_url

    pid = extract_player_id(page_url)
    if pid: player.fifaindex_id = pid

    try: _parse_hero(soup, player)
    except Exception: logger.exception("hero: %s", page_url)

    try: _parse_profile(soup, player)
    except Exception: logger.exception("profile: %s", page_url)

    try: _parse_club(soup, player)
    except Exception: logger.exception("club: %s", page_url)

    try: _parse_national(soup, player)
    except Exception: logger.exception("national: %s", page_url)

    try: _parse_playstyles(soup, player)
    except Exception: logger.exception("playstyles: %s", page_url)

    try: _parse_stats(soup, player)
    except Exception: logger.exception("stats: %s", page_url)

    return player


# ── Hero card ─────────────────────────────────────────────────────────────────

def _parse_hero(soup: BeautifulSoup, player: PlayerData) -> None:
    # Name
    h1 = soup.find("h1")
    if h1: player.name = _text(h1)

    # Photo: CDN pattern /fc26/players/{id}.png
    for img in soup.find_all("img"):
        src = img.get("src", "") or img.get("data-src", "")
        if src and re.search(r"/players/\d+\.(png|jpg|webp)", src):
            player.photo_url = ensure_absolute(BASE_URL, src)
            break

    # Positions: POS_RE text nodes anywhere on page
    positions: List[str] = []
    for el in soup.find_all(string=POS_RE):
        t = el.strip() if isinstance(el, NavigableString) else ""
        if t and t not in positions:
            positions.append(t)
    if positions:
        player.preferred_position = positions[0]
        player.alternative_positions = positions[1:]

    # Nationality via /nations/ link
    for a in soup.find_all("a", href=re.compile(r"/nations/\d+")):
        t = _text(a)
        if t and not t.isdigit():
            player.nationality = t
            break

    # Age / height / weight from span text
    for sp in soup.find_all("span"):
        t = _text(sp)
        if re.match(r"^\d{1,2}\s*y\.?o?\.?$", t) and player.age is None:
            player.age = int(re.match(r"^(\d+)", t).group(1))
        elif re.match(r"^\d{2,3}\s*cm$", t) and player.height_cm is None:
            player.height_cm = int(re.match(r"^(\d+)", t).group(1))
        elif re.match(r"^\d{2,3}\s*kg$", t) and player.weight_kg is None:
            player.weight_kg = int(re.match(r"^(\d+)", t).group(1))

    # OVR / POT: find text nodes matching exactly "OVR"/"POT"
    for lbl_text in soup.find_all(string="OVR"):
        num = _nearby_int(lbl_text, 50, 99)
        if num is not None and player.overall is None: player.overall = num

    for lbl_text in soup.find_all(string="POT"):
        num = _nearby_int(lbl_text, 50, 99)
        if num is not None and player.potential is None: player.potential = num

    # Value / Wage
    for lbl_text in soup.find_all(string=re.compile(r"^Value$", re.I)):
        t = _next_sibling_text(lbl_text)
        if t and ("€" in t or "$" in t) and player.market_value is None:
            player.market_value = t

    for lbl_text in soup.find_all(string=re.compile(r"^Wage$", re.I)):
        t = _next_sibling_text(lbl_text)
        if t and ("€" in t or "$" in t) and player.wage is None:
            player.wage = t


def _nearby_int(text_node, lo: int, hi: int) -> Optional[int]:
    """Find a nearby integer in [lo, hi] in the same grandparent container."""
    parent = getattr(text_node, 'parent', None)
    if not parent: return None
    gp = parent.parent
    if not gp: return None
    for el in gp.find_all(string=re.compile(r"^\d{2,3}$")):
        v = int(el.strip())
        if lo <= v <= hi:
            return v
    return None


def _next_sibling_text(text_node) -> Optional[str]:
    """Return text of the next sibling Tag after text_node's parent."""
    parent = getattr(text_node, 'parent', None)
    if not parent: return None
    for sib in parent.next_siblings:
        if isinstance(sib, Tag):
            t = _text(sib)
            if t: return t
    return None


# ── Profile card (h3 = "PROFILE") ────────────────────────────────────────────

def _parse_profile(soup: BeautifulSoup, player: PlayerData) -> None:
    card = _card_by_h3(soup, "Profile")
    if not card: return

    for row in card.find_all("div"):
        cls = row.get("class", [])
        if "justify-between" not in cls: continue
        if "items-center" not in cls: continue
        children = [c for c in row.children if isinstance(c, Tag)]
        if len(children) < 2: continue

        label_el, value_el = children[0], children[1]
        label = _norm(_text(label_el))
        if not label or label.isdigit(): continue

        if label in IGNORED_LABELS:
            continue

        mapped = PROFILE_LABELS.get(label)
        if mapped in ("weak_foot", "skill_moves", "international_reputation"):
            value = _count_filled_stars(value_el)
        else:
            value = _text(value_el)

        _route_profile(player, mapped, label, value)


def _route_profile(player: PlayerData, mapped: Optional[str], label: str, value: Any) -> None:
    if mapped == "preferred_foot":    player.preferred_foot = value
    elif mapped == "weak_foot":       player.weak_foot = value
    elif mapped == "skill_moves":     player.skill_moves = value
    elif mapped == "body_type":       player.body_type = value
    elif mapped == "acceleration_type": player.acceleration_type = value
    elif mapped == "international_reputation": player.international_reputation = value
    elif mapped == "full_name":       player.full_name = value
    elif mapped == "shirt_name":      player.shirt_name = value
    elif mapped == "birth_date":      player.birth_date = value
    elif mapped == "nationality":
        if not player.nationality: player.nationality = value
    elif mapped == "release_clause":  player.release_clause = value
    elif mapped == "positions_raw":
        for p in re.split(r"[,\s]+", value):
            p = p.strip()
            if POS_RE.match(p):
                if not player.preferred_position: player.preferred_position = p
                elif p not in player.alternative_positions: player.alternative_positions.append(p)
    elif mapped is None and label and len(label) < 80:
        # Unknown → extra_fields (future-proof)
        player.extra_fields[label] = value


# ── Club card (h3 = "CLUB") ───────────────────────────────────────────────────

def _parse_club(soup: BeautifulSoup, player: PlayerData) -> None:
    card = _card_by_h3(soup, "CLUB")
    if not card: return

    # Club name: a[href="/teams/..."] with font-medium class
    for a in card.find_all("a", href=re.compile(r"/teams/")):
        t = _text(a)
        if t and "http" not in t:
            player.club = t
            break

    # League: a[href="/leagues/..."]
    for a in card.find_all("a", href=re.compile(r"/leagues/")):
        t = _text(a)
        if t: player.league = t; break

    # Field rows: div.mt-3 > div.flex.justify-between
    for row in card.find_all("div"):
        cls = row.get("class", [])
        if "justify-between" not in cls: continue
        if "items-center" not in cls: continue
        children = [c for c in row.children if isinstance(c, Tag)]
        if len(children) < 2: continue
        lbl = _norm(_text(children[0]))
        val = _text(children[1])

        if lbl == "rating":
            player.club_rating = _count_filled_stars(children[1]) or parse_int(val)
        elif lbl == "kit number":
            m = re.search(r"(\d+)", val)
            if m: player.kit_number = int(m.group(1))
        elif lbl == "joined":
            player.joined_date = val
        elif lbl == "contract":
            m = re.search(r"(\d{4})", val)
            if m: player.contract_until = int(m.group(1))
        elif lbl == "position":
            pass  # club card position = preferred position (already set)


# ── National team card (h3 = "National team") ───────────────────────────────
# NOTE: h3 text on live site is mixed-case "National team" not all-caps
# NOTE: national team link is /teams/NNNN-france (not /nations/) — same pattern as club

def _parse_national(soup: BeautifulSoup, player: PlayerData) -> None:
    card = _card_by_h3(soup, r"National\s+team")
    if not card: return

    # National team name: first <a href="/teams/..."> inside this card
    for a in card.find_all("a", href=re.compile(r"/teams/")):
        t = _text(a)
        if t and "http" not in t and not t.isdigit():
            player.national_team = t
            break

    # Field rows
    for row in card.find_all("div"):
        cls = row.get("class", [])
        if "justify-between" not in cls: continue
        if "items-center" not in cls: continue
        children = [c for c in row.children if isinstance(c, Tag)]
        if len(children) < 2: continue
        lbl = _norm(_text(children[0]))
        val = _text(children[1])

        if lbl == "rating":
            player.national_rating = _count_filled_stars(children[1]) or parse_int(val)
        elif lbl == "kit number":
            m = re.search(r"(\d+)", val)
            if m: player.national_kit_number = int(m.group(1))
        elif lbl == "position":
            player.national_position = val


def _parse_playstyles(soup: BeautifulSoup, player: PlayerData) -> None:
    card = _card_by_h3(soup, r"Traits\s+&\s+PlayStyles")
    if not card:
        return

    current_section = None
    for child in card.descendants:
        if isinstance(child, Tag):
            if child.name == "h4":
                header_text = _norm(_text(child))
                if "playstyles+" in header_text:
                    current_section = "playstyles_plus"
                elif "playstyles" in header_text:
                    current_section = "playstyles"
                elif "personality traits" in header_text:
                    current_section = "personality_traits"
                else:
                    current_section = None
            elif child.name == "a":
                href = child.get("href", "")
                if "/traits/" in href:
                    trait_name = _text(child)
                    if trait_name:
                        if current_section == "playstyles_plus":
                            player.playstyles_plus.append(trait_name)
                        elif current_section == "playstyles":
                            player.playstyles.append(trait_name)
                        elif current_section == "personality_traits":
                            player.personality_traits.append(trait_name)


# ── Stat cards (h4 headers: PACE, SHOOTING, etc.) ────────────────────────────

def _parse_stats(soup: BeautifulSoup, player: PlayerData) -> None:
    """
    Stat card: <div class="rounded-lg border bg-card p-3">
      <div class="mb-2 flex items-center justify-between">
        <h4 class="... uppercase">Pace</h4>
        <span class="... text-stat-high">96</span>   ← category total
      </div>
      <div class="space-y-1">
        <div class="flex items-center gap-2">
          <span class="w-24 shrink-0 text-xs text-muted-foreground">Acceleration</span>
          <div ...progress bar.../>
          <span class="w-7 shrink-0 text-end text-xs font-bold text-stat-high">97</span>
        </div>
    """
    stat_card_classes = {"rounded-lg", "border", "bg-card", "p-3"}

    for div in soup.find_all("div"):
        div_cls = set(div.get("class", []))
        if not stat_card_classes.issubset(div_cls): continue

        h4 = div.find("h4")
        if not h4: continue
        category = _text(h4)
        if not category or len(category) > 40: continue

        # Category total: span sibling to h4 in the header row
        header_row = h4.find_parent("div")
        if header_row:
            for sp in header_row.find_all("span"):
                t = sp.get_text(strip=True)
                if t.isdigit() and 0 <= int(t) <= 99:
                    if category not in player.stats:
                        player.stats[category] = int(t)
                    break

        # Sub-stats: div.space-y-1 > div.flex.items-center.gap-2
        # Row structure: span.w-24 (name) | div (progress bar) | span.w-7 (value)
        # Use direct class name matching (lambda has issues with html.parser)
        sub = None
        for child in div.children:
            if not isinstance(child, Tag): continue
            if "space-y-1" in child.get("class", []):
                sub = child
                break
        if not sub: continue

        for row in sub.find_all("div", recursive=False):
            row_cls = row.get("class", [])
            if "flex" not in row_cls or "gap-2" not in row_cls: continue

            # Find name span (w-24) and value span (w-7) by class membership
            name_sp = None
            val_sp = None
            for sp in row.find_all("span"):
                sp_cls = sp.get("class", [])
                if "w-24" in sp_cls:
                    name_sp = sp
                elif "w-7" in sp_cls:
                    val_sp = sp

            if not name_sp or not val_sp: continue

            stat_name = _text(name_sp)
            stat_val_txt = val_sp.get_text(strip=True)

            if (
                stat_name
                and stat_val_txt.isdigit()
                and 0 <= int(stat_val_txt) <= 99
                and len(stat_name) < 50
                and stat_name not in player.stats
            ):
                player.stats[stat_name] = int(stat_val_txt)

    # Fallback if no stat cards found (layout change)
    if not player.stats:
        _stats_text_fallback(soup, player)


def _stats_text_fallback(soup: BeautifulSoup, player: PlayerData) -> None:
    KNOWN = [
        "Pace","Acceleration","Sprint Speed","Shooting","Finishing","Shot Power",
        "Long Shots","Attacking Position","Positioning","Volleys","Penalties",
        "Passing","Vision","Crossing","Short Passing","Long Passing","Curve",
        "Free Kick Accuracy","Dribbling","Agility","Balance","Ball Control",
        "Reactions","Composure","Defending","Interceptions","Heading Accuracy",
        "Defensive Awareness","Tactical Awareness","Standing Tackle","Sliding Tackle",
        "Physical","Jumping","Stamina","Strength","Aggression",
        "Goalkeeping","GK Diving","GK Handling","GK Kicking","GK Positioning","GK Reflexes",
    ]
    full = soup.get_text(" ")
    for s in KNOWN:
        if s in player.stats: continue
        m = re.search(rf"\b{re.escape(s)}\s+(\d{{1,3}})\b", full)
        if m:
            v = int(m.group(1))
            if 0 <= v <= 99: player.stats[s] = v


# ── Card finder ───────────────────────────────────────────────────────────────

def _card_by_h3(soup: BeautifulSoup, h3_pattern: str) -> Optional[Tag]:
    """Find a bg-card div whose h3 text matches the pattern (case-insensitive)."""
    for h3 in soup.find_all("h3"):
        h3_text = _text(h3)  # keep original case for pattern matching
        if re.search(h3_pattern, h3_text, re.I):
            # Walk up to the bg-card div
            el = h3.parent
            for _ in range(5):
                if el is None: break
                if "bg-card" in " ".join(el.get("class", [])):
                    return el
                el = el.parent
    return None
