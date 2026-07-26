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

# Common nickname mappings (normalized form -> canonical form)
NICKNAME_MAP = {
    'johnny': 'john',
    'matt': 'matthew',
    'matthias': 'matthew',
    'matti': 'matthew',
    'zach': 'zachary',
    'zack': 'zachary',
    'mike': 'michael',
    'chris': 'christopher',
    'rob': 'robert',
    'bob': 'robert',
    'will': 'william',
    'bill': 'william',
    'tom': 'thomas',
    'tommy': 'thomas',
    'jim': 'james',
    'jimmy': 'james',
    'dan': 'daniel',
    'danny': 'daniel',
    'tony': 'anthony',
    'nick': 'nicholas',
    'cam': 'cameron',
    'ben': 'benjamin',
    'alex': 'alexander',
    'sam': 'samuel',
    'ed': 'edward',
    'ted': 'theodore',
    'joe': 'joseph',
    'joey': 'joseph',
    'rick': 'richard',
    'rickie': 'richard',
    'dick': 'richard',
    'pat': 'patrick',
    'steve': 'steven',
    'dave': 'david',
    'andy': 'andrew',
    'drew': 'andrew',
    'charlie': 'charles',
    'chuck': 'charles',
    'larry': 'lawrence',
    'max': 'maxwell',
}

# Input files
KALSHI_FILE = DATA_DIR / "kalshi" / "KXPGATOUR-ROC26.json"
DK_FILE = DATA_DIR / "draftkings" / "rocket-classic-2026.json"

# Output file
OUTPUT_DIR = DATA_DIR / "merged"
OUTPUT_FILE = OUTPUT_DIR / "rocket-classic-2026.json"


def normalize_name(name: str) -> str:
    """
    Normalize player name for matching.

    - Convert to lowercase
    - Strip periods, apostrophes, hyphens
    - Collapse whitespace
    - Strip suffixes like Jr, Jr., II, III, IV
    - Convert accented characters to ASCII
    - Handle special characters like ø -> o
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

    Args:
        probs: List of implied probabilities

    Returns:
        List of devigged probabilities summing to 1.0
    """
    total = sum(probs)
    if total == 0:
        return probs
    return [p / total for p in probs]


def load_kalshi() -> tuple[dict, str]:
    """
    Load Kalshi data and return dict keyed by normalized name.

    Returns:
        (dict of normalized_name -> player data, fetched_at timestamp)
    """
    with open(KALSHI_FILE) as f:
        data = json.load(f)

    fetched_at = data.get("fetched_at", "")
    players = {}

    for market in data.get("markets", []):
        name = market.get("player_name") or market.get("player_code", "")
        if not name:
            continue

        # Get ask price (yes_ask_dollars)
        ask_dollars = market.get("yes_ask_dollars")
        if not ask_dollars:
            continue

        ask = float(ask_dollars)
        # Filter out inactive markets
        if ask <= 0 or ask >= 1.0:
            continue

        normalized = normalize_name(name)
        players[normalized] = {
            "display_name": name,
            "kalshi_ask": ask,
            "kalshi_implied_prob": ask,  # Ask price IS the implied prob
        }

    return players, fetched_at


def load_draftkings() -> tuple[dict, str]:
    """
    Load DraftKings data and return dict keyed by normalized name.

    Returns:
        (dict of normalized_name -> player data, fetched_at timestamp)
    """
    with open(DK_FILE) as f:
        data = json.load(f)

    fetched_at = data.get("fetched_at", "")
    players = {}

    for player in data.get("players", []):
        name = player.get("player_name", "")
        if not name:
            continue

        normalized = normalize_name(name)
        players[normalized] = {
            "display_name": name,
            "dk_american_odds": player.get("american_odds"),
            "dk_implied_prob": player.get("implied_prob"),
        }

    return players, fetched_at


def merge_data(kalshi: dict, dk: dict) -> tuple[list, set, set]:
    """
    Merge Kalshi and DraftKings data.

    Returns:
        (merged list, unmatched kalshi names, unmatched dk names)
    """
    all_normalized = set(kalshi.keys()) | set(dk.keys())
    matched_names = set(kalshi.keys()) & set(dk.keys())
    unmatched_kalshi = set(kalshi.keys()) - set(dk.keys())
    unmatched_dk = set(dk.keys()) - set(kalshi.keys())

    # Calculate devigged DK probabilities
    dk_probs = [dk[n]["dk_implied_prob"] for n in dk.keys()]
    dk_devigged = devig_probabilities(dk_probs)
    dk_devigged_map = dict(zip(dk.keys(), dk_devigged))

    merged = []
    for norm_name in all_normalized:
        k = kalshi.get(norm_name, {})
        d = dk.get(norm_name, {})

        # Use DK display name if available, else Kalshi
        display_name = d.get("display_name") or k.get("display_name", norm_name)

        record = {
            "player_name": display_name,
            "normalized_name": norm_name,
            "dk_american_odds": d.get("dk_american_odds"),
            "dk_implied_prob": d.get("dk_implied_prob"),
            "dk_devigged_prob": dk_devigged_map.get(norm_name),
            "kalshi_ask": k.get("kalshi_ask"),
            "kalshi_implied_prob": k.get("kalshi_implied_prob"),
        }
        merged.append(record)

    # Sort by DK implied prob descending (favorites first), then Kalshi
    def sort_key(r):
        dk = r.get("dk_implied_prob") or 0
        ka = r.get("kalshi_implied_prob") or 0
        return (dk, ka)

    merged.sort(key=sort_key, reverse=True)

    return merged, unmatched_kalshi, unmatched_dk


def main():
    print("Loading Kalshi data...")
    try:
        kalshi, kalshi_fetched = load_kalshi()
        print(f"  Loaded {len(kalshi)} players from Kalshi")
    except FileNotFoundError:
        print(f"Error: Kalshi file not found: {KALSHI_FILE}")
        sys.exit(1)

    print("Loading DraftKings data...")
    try:
        dk, dk_fetched = load_draftkings()
        print(f"  Loaded {len(dk)} players from DraftKings")
    except FileNotFoundError:
        print(f"Error: DraftKings file not found: {DK_FILE}")
        sys.exit(1)

    print("\nMerging data...")
    merged, unmatched_kalshi, unmatched_dk = merge_data(kalshi, dk)

    matched = len(kalshi) + len(dk) - len(merged)
    matched_count = len(set(kalshi.keys()) & set(dk.keys()))

    print(f"  Total merged records: {len(merged)}")
    print(f"  Matched players: {matched_count}")
    print(f"  Unmatched from Kalshi: {len(unmatched_kalshi)}")
    print(f"  Unmatched from DraftKings: {len(unmatched_dk)}")

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
        },
        "match_stats": {
            "matched": matched_count,
            "unmatched_kalshi": len(unmatched_kalshi),
            "unmatched_dk": len(unmatched_dk),
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
    print("\n" + "=" * 60)
    print("MATCH REPORT")
    print("=" * 60)
    print(f"Matched: {matched_count} players")

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

    if not unmatched_kalshi and not unmatched_dk:
        print("\nAll players matched!")


if __name__ == "__main__":
    main()
