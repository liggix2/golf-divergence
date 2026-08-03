#!/usr/bin/env python3
"""
Merge Kalshi and DraftKings odds into a single file for the site.

Normalizes player names for matching and outputs a merged record per player.

Usage:
    python merge_odds.py [--event-slug SLUG] [--kalshi-ticker TICKER]
"""

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

from name_utils import normalize_name, normalize_name_base

SCRIPT_DIR = Path(__file__).parent.parent
DATA_DIR = SCRIPT_DIR / "data"
OUTPUT_DIR = DATA_DIR / "merged"

# Default event parameters
DEFAULT_EVENT_SLUG = "wyndham-championship-2026"
DEFAULT_KALSHI_TICKER = "KXPGATOUR-WYC26"

# Kalshi taker fee: 7% * price * (1 - price)
KALSHI_FEE_RATE = 0.07


def kalshi_effective_price(raw_price: float) -> float:
    """Calculate Kalshi effective price including taker fee."""
    if raw_price <= 0 or raw_price >= 1:
        return raw_price
    fee = KALSHI_FEE_RATE * raw_price * (1 - raw_price)
    return raw_price + fee


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


def load_kalshi(kalshi_file: Path) -> tuple[dict, dict, str, list]:
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

    return load_source(kalshi_file, "Kalshi", get_markets)


def load_draftkings(dk_file: Path) -> tuple[dict, dict, str, list]:
    """Load DraftKings data with collision detection."""
    def get_markets(data):
        for player in data.get("players", []):
            name = player.get("player_name", "")
            yield name, {
                "display_name": name,
                "dk_american_odds": player.get("american_odds"),
                "dk_implied_prob": player.get("implied_prob"),
            }

    return load_source(dk_file, "DraftKings", get_markets)


def load_datagolf(dg_file: Path) -> tuple[dict, dict, str, list]:
    """Load Data Golf data with collision detection."""
    def get_markets(data):
        for player in data.get("players", []):
            display_name = player.get("player_name", "")
            win_baseline = player.get("win_baseline")
            if win_baseline is None:
                continue
            yield display_name, {
                "display_name": display_name,
                "dg_win_prob": win_baseline,
                "dg_id": player.get("dg_id"),
            }

    return load_source(dg_file, "DataGolf", get_markets)


def load_model(model_file: Path) -> tuple[dict, dict, str]:
    """
    Load model output indexed by dg_id and normalized name.

    Returns:
        (by_dg_id dict, by_normalized_name dict, fetched_at)
    """
    with open(model_file) as f:
        data = json.load(f)

    fetched_at = data.get("fetched_at", "")
    by_dg_id = {}
    by_name = {}

    for player in data.get("players", []):
        dg_id = player.get("dg_id")
        name = player.get("player_name", "")
        win_prob = player.get("win_prob")
        placeholder = player.get("placeholder_rating", False)

        record = {
            "my_fair_prob": win_prob,
            "my_fair_placeholder": placeholder,
        }

        if dg_id is not None:
            by_dg_id[dg_id] = record

        if name:
            normalized = normalize_name(name)
            by_name[normalized] = record

    return by_dg_id, by_name, fetched_at


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


def merge_data(kalshi: dict, dk: dict, dg: dict, model_by_id: dict, model_by_name: dict) -> tuple[list, set, set, set]:
    """
    Merge Kalshi, DraftKings, Data Golf, and model data.

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

        # Look up model data by dg_id first, then by normalized name
        dg_id = g.get("dg_id")
        model = None
        if dg_id and dg_id in model_by_id:
            model = model_by_id[dg_id]
        elif norm_name in model_by_name:
            model = model_by_name[norm_name]

        my_fair_prob = model.get("my_fair_prob") if model else None
        my_fair_placeholder = model.get("my_fair_placeholder", False) if model else False

        # Compute edge: my_fair_prob - market implied prob (in percentage points)
        edge_dk = None
        edge_kalshi = None

        if my_fair_prob is not None:
            dk_prob = d.get("dk_implied_prob")
            if dk_prob is not None:
                edge_dk = (my_fair_prob - dk_prob) * 100

            kalshi_prob = k.get("kalshi_implied_prob")
            if kalshi_prob is not None:
                # Use fee-adjusted effective price for Kalshi
                effective_prob = kalshi_effective_price(kalshi_prob)
                edge_kalshi = (my_fair_prob - effective_prob) * 100

        record = {
            "player_name": display_name,
            "normalized_name": norm_name,
            "dg_id": dg_id,
            "dk_american_odds": d.get("dk_american_odds"),
            "dk_implied_prob": d.get("dk_implied_prob"),
            "dk_devigged_prob": dk_devigged_map.get(norm_name),
            "kalshi_ask": k.get("kalshi_ask"),
            "kalshi_implied_prob": k.get("kalshi_implied_prob"),
            "dg_win_prob": g.get("dg_win_prob"),
            "my_fair_prob": my_fair_prob,
            "my_fair_placeholder": my_fair_placeholder,
            "edge_dk": edge_dk,
            "edge_kalshi": edge_kalshi,
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
    parser = argparse.ArgumentParser(description="Merge golf odds from multiple sources")
    parser.add_argument(
        "--event-slug",
        type=str,
        default=DEFAULT_EVENT_SLUG,
        help=f"Event slug for input/output files (default: {DEFAULT_EVENT_SLUG})"
    )
    parser.add_argument(
        "--kalshi-ticker",
        type=str,
        default=DEFAULT_KALSHI_TICKER,
        help=f"Kalshi ticker for input file (default: {DEFAULT_KALSHI_TICKER})"
    )
    args = parser.parse_args()

    event_slug = args.event_slug
    kalshi_ticker = args.kalshi_ticker

    kalshi_file = DATA_DIR / "kalshi" / f"{kalshi_ticker}.json"
    dk_file = DATA_DIR / "draftkings" / f"{event_slug}.json"
    dg_file = DATA_DIR / "datagolf" / f"predictions-{event_slug}.json"
    model_file = DATA_DIR / "model" / f"{event_slug}.json"
    output_file = OUTPUT_DIR / f"{event_slug}.json"

    print(f"Event: {event_slug}")
    print(f"Kalshi ticker: {kalshi_ticker}")
    print()

    print("Loading Kalshi data...")
    try:
        kalshi, kalshi_base, kalshi_fetched, kalshi_collisions = load_kalshi(kalshi_file)
        print(f"  Loaded {len(kalshi)} players from Kalshi")
    except FileNotFoundError:
        print(f"Error: Kalshi file not found: {kalshi_file}")
        sys.exit(1)

    print("Loading DraftKings data...")
    try:
        dk, dk_base, dk_fetched, dk_collisions = load_draftkings(dk_file)
        print(f"  Loaded {len(dk)} players from DraftKings")
    except FileNotFoundError:
        print(f"  Warning: DraftKings file not found, proceeding without DK data")
        dk, dk_base, dk_fetched, dk_collisions = {}, {}, "", []

    print("Loading Data Golf predictions...")
    try:
        dg, dg_base, dg_fetched, dg_collisions = load_datagolf(dg_file)
        print(f"  Loaded {len(dg)} players from Data Golf predictions")
    except FileNotFoundError:
        print(f"  Warning: DG predictions not found, proceeding without DG odds")
        dg, dg_base, dg_fetched, dg_collisions = {}, {}, "", []

    print("Loading model data...")
    try:
        model_by_id, model_by_name, model_fetched = load_model(model_file)
        print(f"  Loaded {len(model_by_id)} players from model")
    except FileNotFoundError:
        print(f"Error: Model file not found: {model_file}")
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
    merged, unmatched_kalshi, unmatched_dk, unmatched_dg = merge_data(kalshi, dk, dg, model_by_id, model_by_name)

    matched_dk_kalshi = len(set(kalshi.keys()) & set(dk.keys()))
    matched_dg = len(set(dg.keys()) & (set(kalshi.keys()) | set(dk.keys())))

    print(f"  Total merged records: {len(merged)}")
    print(f"  DK-Kalshi matched: {matched_dk_kalshi}")
    print(f"  Data Golf matched: {matched_dg}")
    print(f"  Unmatched from Kalshi: {len(unmatched_kalshi)}")
    print(f"  Unmatched from DraftKings: {len(unmatched_dk)}")
    print(f"  Unmatched from Data Golf: {len(unmatched_dg)}")

    # Calculate Kalshi ask sum
    kalshi_ask_sum = sum(p.get("kalshi_ask", 0) or 0 for p in merged)
    print(f"  Kalshi ask sum: {kalshi_ask_sum * 100:.1f}%")

    # Build output
    output = {
        "event_slug": event_slug,
        "kalshi_ticker": kalshi_ticker,
        "merged_at": datetime.now(timezone.utc).isoformat(),
        "kalshi_ask_sum": kalshi_ask_sum,
        "sources": {
            "kalshi": {
                "file": str(kalshi_file.name),
                "fetched_at": kalshi_fetched,
                "player_count": len(kalshi),
            },
            "draftkings": {
                "file": str(dk_file.name),
                "fetched_at": dk_fetched,
                "player_count": len(dk),
            },
            "datagolf": {
                "file": str(dg_file.name),
                "fetched_at": dg_fetched,
                "player_count": len(dg),
            },
            "model": {
                "file": str(model_file.name),
                "fetched_at": model_fetched,
                "player_count": len(model_by_id),
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
    with open(output_file, "w") as f:
        json.dump(output, f, indent=2)
    print(f"\nSaved to: {output_file}")

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
