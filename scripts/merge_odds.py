#!/usr/bin/env python3
"""
Merge Kalshi and DraftKings odds into a single file for the site.

Normalizes player names for matching and outputs a merged record per player.
"""

import json
import re
import sys
import unicodedata
from datetime import datetime, timezone
from pathlib import Path

SCRIPT_DIR = Path(__file__).parent.parent
DATA_DIR = SCRIPT_DIR / "data"

# Active nickname mappings - only entries needed for current fields
NICKNAME_MAP = {
    'johnny': 'john',
    'matt': 'matthew',
    'matthias': 'matthew',
    'matti': 'matthew',
    'zach': 'zachary',
}

# Reserve mappings - add back if future fields need them
# NICKNAME_MAP_RESERVE = {
#     'zack': 'zachary',
#     'mike': 'michael',
#     'chris': 'christopher',
#     'rob': 'robert',
#     'bob': 'robert',
#     'will': 'william',
#     'bill': 'william',
#     'tom': 'thomas',
#     'tommy': 'thomas',
#     'jim': 'james',
#     'jimmy': 'james',
#     'dan': 'daniel',
#     'danny': 'daniel',
#     'tony': 'anthony',
#     'nick': 'nicholas',
#     'cam': 'cameron',
#     'ben': 'benjamin',
#     'alex': 'alexander',
#     'sam': 'samuel',
#     'ed': 'edward',
#     'ted': 'theodore',
#     'joe': 'joseph',
#     'joey': 'joseph',
#     'rick': 'richard',
#     'rickie': 'richard',
#     'dick': 'richard',
#     'pat': 'patrick',
#     'steve': 'steven',
#     'dave': 'david',
#     'andy': 'andrew',
#     'drew': 'andrew',
#     'charlie': 'charles',
#     'chuck': 'charles',
#     'larry': 'lawrence',
#     'max': 'maxwell',
# }

# Input files
KALSHI_FILE = DATA_DIR / "kalshi" / "KXPGATOUR-ROC26.json"
DK_FILE = DATA_DIR / "draftkings" / "rocket-classic-2026.json"
DG_FILE = DATA_DIR / "datagolf" / "raw_pretournament.json"

# Output file
OUTPUT_DIR = DATA_DIR / "merged"
OUTPUT_FILE = OUTPUT_DIR / "rocket-classic-2026.json"


def last_first_to_first_last(name: str) -> str:
    """Convert 'Last, First' format to 'First Last'."""
    if ',' in name:
        parts = name.split(',', 1)
        if len(parts) == 2:
            return f"{parts[1].strip()} {parts[0].strip()}"
    return name


def normalize_name_base(name: str) -> str:
    """
    Normalize player name WITHOUT nickname mapping.
    Used to detect if nickname mapping was needed for a match.
    """
    # Handle special Nordic characters before normalization
    replacements = {
        'ø': 'o', 'Ø': 'O',
        'æ': 'ae', 'Æ': 'AE',
        'å': 'a', 'Å': 'A',
        'ö': 'o', 'Ö': 'O',
        'ü': 'u', 'Ü': 'U',
        'ñ': 'n', 'Ñ': 'N',
    }
    for old, new in replacements.items():
        name = name.replace(old, new)

    # Convert accented characters to ASCII
    name = unicodedata.normalize('NFKD', name)
    name = ''.join(c for c in name if not unicodedata.combining(c))

    # Lowercase
    name = name.lower()

    # Strip periods, apostrophes, hyphens
    name = name.replace('.', '').replace("'", '').replace("'", '').replace('-', '')

    # Collapse whitespace
    name = ' '.join(name.split())

    # Strip common suffixes
    suffixes = [' jr', ' sr', ' ii', ' iii', ' iv', ' v']
    for suffix in suffixes:
        if name.endswith(suffix):
            name = name[:-len(suffix)]

    # Strip single middle initials (e.g., "jordan l smith" -> "jordan smith")
    name = re.sub(r'\b[a-z]\b', '', name)
    name = ' '.join(name.split())

    return name.strip()


def normalize_name(name: str) -> str:
    """
    Normalize player name WITH nickname mapping.
    """
    name = normalize_name_base(name)

    # Apply nickname mappings to first name
    parts = name.split()
    if parts:
        first = parts[0]
        if first in NICKNAME_MAP:
            parts[0] = NICKNAME_MAP[first]
        name = ' '.join(parts)

    return name.strip()


def devig_probabilities(probs: list[float]) -> list[float]:
    """
    Devig probabilities by proportional scaling.
    """
    total = sum(probs)
    if total == 0:
        return probs
    return [p / total for p in probs]


def load_source(file_path: Path, source_name: str, get_markets: callable) -> tuple[dict, dict, str, list]:
    """
    Load a data source with collision detection.

    Returns:
        (players dict, base_names dict, fetched_at, collisions list)
    """
    with open(file_path) as f:
        data = json.load(f)

    fetched_at = data.get("fetched_at", "")
    players = {}
    base_names = {}  # normalized_base -> display_name (for nickname match detection)
    collisions = []

    # Track names before normalization to detect collisions
    seen_normalized = {}  # normalized -> original display name

    for item in get_markets(data):
        name, player_data = item
        if not name:
            continue

        normalized = normalize_name(name)
        normalized_base = normalize_name_base(name)

        # Check for collision
        if normalized in seen_normalized:
            collisions.append({
                "normalized": normalized,
                "name1": seen_normalized[normalized],
                "name2": name,
            })
            continue

        seen_normalized[normalized] = name
        players[normalized] = player_data
        base_names[normalized_base] = name

    return players, base_names, fetched_at, collisions


def load_kalshi() -> tuple[dict, dict, str, list]:
    """Load Kalshi data with collision detection."""
    def get_markets(data):
        for market in data.get("markets", []):
            name = market.get("player_name") or market.get("player_code", "")
            ask_dollars = market.get("yes_ask_dollars")
            if not ask_dollars:
                continue
            ask = float(ask_dollars)
            if ask <= 0 or ask >= 1.0:
                continue
            yield name, {
                "display_name": name,
                "kalshi_ask": ask,
                "kalshi_implied_prob": ask,
            }

    return load_source(KALSHI_FILE, "Kalshi", get_markets)


def load_draftkings() -> tuple[dict, dict, str, list]:
    """Load DraftKings data with collision detection."""
    def get_markets(data):
        for player in data.get("players", []):
            name = player.get("player_name", "")
            yield name, {
                "display_name": name,
                "dk_american_odds": player.get("american_odds"),
                "dk_implied_prob": player.get("implied_prob"),
            }

    return load_source(DK_FILE, "DraftKings", get_markets)


def load_datagolf() -> tuple[dict, dict, str, list]:
    """Load Data Golf data with collision detection."""
    def get_markets(data):
        for player in data.get("baseline", []):
            raw_name = player.get("player_name", "")
            display_name = last_first_to_first_last(raw_name)
            win_prob = player.get("win")
            if win_prob is None:
                continue
            yield display_name, {
                "display_name": display_name,
                "dg_win_prob": win_prob,
                "dg_id": player.get("dg_id"),
            }

    return load_source(DG_FILE, "DataGolf", get_markets)


def find_nickname_matches(kalshi_base: dict, dk_base: dict, kalshi: dict, dk: dict) -> list:
    """
    Find matches that only succeeded because of NICKNAME_MAP.

    Returns list of (kalshi_name, dk_name, normalized_key) tuples.
    """
    nickname_matches = []

    matched_normalized = set(kalshi.keys()) & set(dk.keys())

    for norm_key in matched_normalized:
        kalshi_display = kalshi[norm_key]["display_name"]
        dk_display = dk[norm_key]["display_name"]

        kalshi_base_norm = normalize_name_base(kalshi_display)
        dk_base_norm = normalize_name_base(dk_display)

        # If base normalizations differ, nickname mapping was needed
        if kalshi_base_norm != dk_base_norm:
            nickname_matches.append((kalshi_display, dk_display, norm_key))

    return nickname_matches


def merge_data(kalshi: dict, dk: dict, dg: dict) -> tuple[list, set, set, set]:
    """
    Merge Kalshi, DraftKings, and Data Golf data.

    Returns:
        (merged list, unmatched kalshi names, unmatched dk names, unmatched dg names)
    """
    all_normalized = set(kalshi.keys()) | set(dk.keys()) | set(dg.keys())
    matched_any = set(kalshi.keys()) | set(dk.keys())
    unmatched_kalshi = set(kalshi.keys()) - set(dk.keys())
    unmatched_dk = set(dk.keys()) - set(kalshi.keys())
    unmatched_dg = set(dg.keys()) - matched_any

    # Calculate devigged DK probabilities
    dk_probs = [dk[n]["dk_implied_prob"] for n in dk.keys()]
    dk_devigged = devig_probabilities(dk_probs)
    dk_devigged_map = dict(zip(dk.keys(), dk_devigged))

    merged = []
    for norm_name in all_normalized:
        k = kalshi.get(norm_name, {})
        d = dk.get(norm_name, {})
        g = dg.get(norm_name, {})

        # Use DK display name if available, else Kalshi, else Data Golf
        display_name = d.get("display_name") or k.get("display_name") or g.get("display_name", norm_name)

        record = {
            "player_name": display_name,
            "normalized_name": norm_name,
            "dg_id": g.get("dg_id"),
            "dk_american_odds": d.get("dk_american_odds"),
            "dk_implied_prob": d.get("dk_implied_prob"),
            "dk_devigged_prob": dk_devigged_map.get(norm_name),
            "kalshi_ask": k.get("kalshi_ask"),
            "kalshi_implied_prob": k.get("kalshi_implied_prob"),
            "dg_win_prob": g.get("dg_win_prob"),
        }
        merged.append(record)

    # Sort by DK implied prob descending (favorites first), then Kalshi
    def sort_key(r):
        dk_prob = r.get("dk_implied_prob") or 0
        ka_prob = r.get("kalshi_implied_prob") or 0
        return (dk_prob, ka_prob)

    merged.sort(key=sort_key, reverse=True)

    return merged, unmatched_kalshi, unmatched_dk, unmatched_dg


def main():
    print("Loading Kalshi data...")
    try:
        kalshi, kalshi_base, kalshi_fetched, kalshi_collisions = load_kalshi()
        print(f"  Loaded {len(kalshi)} players from Kalshi")
    except FileNotFoundError:
        print(f"Error: Kalshi file not found: {KALSHI_FILE}")
        sys.exit(1)

    print("Loading DraftKings data...")
    try:
        dk, dk_base, dk_fetched, dk_collisions = load_draftkings()
        print(f"  Loaded {len(dk)} players from DraftKings")
    except FileNotFoundError:
        print(f"Error: DraftKings file not found: {DK_FILE}")
        sys.exit(1)

    print("Loading Data Golf data...")
    try:
        dg, dg_base, dg_fetched, dg_collisions = load_datagolf()
        print(f"  Loaded {len(dg)} players from Data Golf")
    except FileNotFoundError:
        print(f"Error: Data Golf file not found: {DG_FILE}")
        sys.exit(1)

    # Report collisions
    if kalshi_collisions:
        print(f"\n⚠️  KALSHI COLLISIONS ({len(kalshi_collisions)}):")
        for c in kalshi_collisions:
            print(f"  '{c['name1']}' and '{c['name2']}' both normalize to '{c['normalized']}'")
            print(f"    -> Skipping '{c['name2']}'")

    if dk_collisions:
        print(f"\n⚠️  DRAFTKINGS COLLISIONS ({len(dk_collisions)}):")
        for c in dk_collisions:
            print(f"  '{c['name1']}' and '{c['name2']}' both normalize to '{c['normalized']}'")
            print(f"    -> Skipping '{c['name2']}'")

    if dg_collisions:
        print(f"\n⚠️  DATA GOLF COLLISIONS ({len(dg_collisions)}):")
        for c in dg_collisions:
            print(f"  '{c['name1']}' and '{c['name2']}' both normalize to '{c['normalized']}'")
            print(f"    -> Skipping '{c['name2']}'")

    # Find nickname-assisted matches
    nickname_matches = find_nickname_matches(kalshi_base, dk_base, kalshi, dk)

    print("\nMerging data...")
    merged, unmatched_kalshi, unmatched_dk, unmatched_dg = merge_data(kalshi, dk, dg)

    matched_dk_kalshi = len(set(kalshi.keys()) & set(dk.keys()))
    matched_dg = len(set(dg.keys()) & (set(kalshi.keys()) | set(dk.keys())))

    print(f"  Total merged records: {len(merged)}")
    print(f"  DK-Kalshi matched: {matched_dk_kalshi}")
    print(f"  Data Golf matched: {matched_dg}")
    print(f"  Unmatched from Kalshi: {len(unmatched_kalshi)}")
    print(f"  Unmatched from DraftKings: {len(unmatched_dk)}")
    print(f"  Unmatched from Data Golf: {len(unmatched_dg)}")

    # Build output
    output = {
        "event_name": "Rocket Classic 2026",
        "merged_at": datetime.now(timezone.utc).isoformat(),
        "sources": {
            "kalshi": {
                "file": str(KALSHI_FILE.name),
                "fetched_at": kalshi_fetched,
                "player_count": len(kalshi),
            },
            "draftkings": {
                "file": str(DK_FILE.name),
                "fetched_at": dk_fetched,
                "player_count": len(dk),
            },
            "datagolf": {
                "file": str(DG_FILE.name),
                "fetched_at": dg_fetched,
                "player_count": len(dg),
            },
        },
        "match_stats": {
            "dk_kalshi_matched": matched_dk_kalshi,
            "dg_matched": matched_dg,
            "unmatched_kalshi": len(unmatched_kalshi),
            "unmatched_dk": len(unmatched_dk),
            "unmatched_dg": len(unmatched_dg),
            "total_merged": len(merged),
        },
        "players": merged,
    }

    # Save
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    with open(OUTPUT_FILE, "w") as f:
        json.dump(output, f, indent=2)
    print(f"\nSaved to: {OUTPUT_FILE}")

    # Print match report
    print("\n" + "=" * 70)
    print("MATCH REPORT")
    print("=" * 70)
    print(f"DK-Kalshi matched: {matched_dk_kalshi} players")
    print(f"Data Golf matched: {matched_dg} players")

    # Print nickname-assisted matches
    if nickname_matches:
        print(f"\nNickname-assisted matches ({len(nickname_matches)}):")
        for kalshi_name, dk_name, norm_key in sorted(nickname_matches):
            print(f"  Kalshi: '{kalshi_name}' <-> DK: '{dk_name}'")

    if unmatched_kalshi:
        print(f"\nUnmatched from Kalshi ({len(unmatched_kalshi)}):")
        for name in sorted(unmatched_kalshi):
            display = kalshi[name]["display_name"]
            print(f"  - {display}")

    if unmatched_dk:
        print(f"\nUnmatched from DraftKings ({len(unmatched_dk)}):")
        for name in sorted(unmatched_dk):
            display = dk[name]["display_name"]
            print(f"  - {display}")

    if unmatched_dg:
        print(f"\nUnmatched from Data Golf ({len(unmatched_dg)}):")
        for name in sorted(unmatched_dg):
            display = dg[name]["display_name"]
            print(f"  - {display}")

    if not unmatched_kalshi and not unmatched_dk and not unmatched_dg:
        print("\nAll players matched!")


if __name__ == "__main__":
    main()
