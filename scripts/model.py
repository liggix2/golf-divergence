#!/usr/bin/env python3
"""
Golf Win Probability Model v2

Monte Carlo simulation using strokes gained to estimate win probabilities.
Tiered skill sources: skill_ratings -> rankings -> field-minimum fallback.

Supports two field sources:
  - datagolf: Field from Data Golf /field-updates endpoint
  - kalshi: Field from Kalshi markets (active markets only)

Usage:
    python model.py [--event-slug EVENT_SLUG] [--field-source {datagolf,kalshi}]
"""

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

from name_utils import normalize_name, last_first_to_first_last

SCRIPT_DIR = Path(__file__).parent.parent
DATA_DIR = SCRIPT_DIR / "data"

DEFAULT_EVENT_SLUG = "wyndham-championship-2026"
DEFAULT_KALSHI_TICKER = "KXPGATOUR-WYC26"

SKILL_RATINGS_FILE = DATA_DIR / "datagolf" / "skill-ratings.json"
RANKINGS_FILE = DATA_DIR / "datagolf" / "rankings.json"

MODEL_VERSION = "v2-field-based"
NUM_SIMULATIONS = 20000
NUM_ROUNDS = 4
ROUND_STDDEV = 2.75

FALLBACK_OFFSET = 0.5


def load_skill_ratings() -> tuple[dict, dict]:
    """
    Load skill ratings indexed by dg_id and normalized name.

    Returns:
        (by_dg_id dict, by_normalized_name dict)
    """
    with open(SKILL_RATINGS_FILE) as f:
        data = json.load(f)

    by_id = {}
    by_name = {}

    for player in data.get("players", []):
        dg_id = player.get("dg_id")
        sg_total = player.get("sg_total")
        raw_name = player.get("player_name", "")

        if sg_total is None:
            continue

        if dg_id is not None:
            by_id[dg_id] = {"sg_total": sg_total, "player_name": last_first_to_first_last(raw_name)}

        if raw_name:
            normalized = normalize_name(last_first_to_first_last(raw_name))
            by_name[normalized] = {"sg_total": sg_total, "dg_id": dg_id, "player_name": last_first_to_first_last(raw_name)}

    return by_id, by_name


def load_rankings() -> tuple[dict, dict]:
    """
    Load rankings skill estimates indexed by dg_id and normalized name.

    Returns:
        (by_dg_id dict, by_normalized_name dict)
    """
    with open(RANKINGS_FILE) as f:
        data = json.load(f)

    by_id = {}
    by_name = {}

    for player in data.get("players", []):
        dg_id = player.get("dg_id")
        skill_est = player.get("dg_skill_estimate")
        raw_name = player.get("player_name", "")

        if skill_est is None:
            continue

        if dg_id is not None:
            by_id[dg_id] = {"sg_total": skill_est, "player_name": last_first_to_first_last(raw_name)}

        if raw_name:
            normalized = normalize_name(last_first_to_first_last(raw_name))
            by_name[normalized] = {"sg_total": skill_est, "dg_id": dg_id, "player_name": last_first_to_first_last(raw_name)}

    return by_id, by_name


def load_field_datagolf(field_file: Path) -> tuple[list, str]:
    """Load current tournament field from Data Golf field-updates file."""
    with open(field_file) as f:
        data = json.load(f)

    event_name = data.get("event_name", "Unknown Event")
    players = []

    for p in data.get("players", []):
        dg_id = p.get("dg_id")
        player_name = p.get("player_name", "")
        if dg_id is not None:
            players.append({
                "dg_id": dg_id,
                "player_name": player_name,
                "normalized_name": normalize_name(player_name),
            })

    return players, event_name


def load_field_kalshi(kalshi_file: Path) -> tuple[list, str]:
    """
    Load tournament field from Kalshi markets file.

    Filters to active markets only (status != "finalized", valid ask price).
    """
    with open(kalshi_file) as f:
        data = json.load(f)

    event_ticker = data.get("event_ticker", "Unknown")
    players = []

    for market in data.get("markets", []):
        status = market.get("status", "")

        # Skip finalized/inactive markets
        if status == "finalized":
            continue

        # Check for valid ask price
        ask_dollars = market.get("yes_ask_dollars")
        if not ask_dollars:
            continue
        try:
            ask = float(ask_dollars)
            if ask <= 0 or ask >= 1.0:
                continue
        except (ValueError, TypeError):
            continue

        player_name = market.get("player_name") or market.get("player_code", "")
        if not player_name:
            continue

        players.append({
            "dg_id": None,  # Will be matched via name normalization
            "player_name": player_name,
            "normalized_name": normalize_name(player_name),
            "kalshi_ask": ask,
        })

    return players, f"Kalshi {event_ticker}"


def run_simulation(players: list) -> dict:
    """
    Run Monte Carlo simulation to estimate win probabilities.

    Each player's round score is: -sg_total + Normal(0, ROUND_STDDEV)
    Lower total after 4 rounds wins. Ties split evenly.

    Returns dict of player_id -> win probability (using index as ID for Kalshi)
    """
    n_players = len(players)
    sg_totals = np.array([p["sg_total"] for p in players])

    expected_scores = -sg_totals

    noise = np.random.normal(0, ROUND_STDDEV, (NUM_SIMULATIONS, n_players, NUM_ROUNDS))
    round_scores = expected_scores[np.newaxis, :, np.newaxis] + noise

    totals = round_scores.sum(axis=2)

    win_counts = np.zeros(n_players)

    for sim in range(NUM_SIMULATIONS):
        sim_totals = totals[sim]
        min_score = sim_totals.min()
        winners = np.where(sim_totals == min_score)[0]
        win_share = 1.0 / len(winners)
        for w in winners:
            win_counts[w] += win_share

    win_probs = win_counts / NUM_SIMULATIONS
    return {i: prob for i, prob in enumerate(win_probs)}


def main():
    parser = argparse.ArgumentParser(description="Run golf win probability model")
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
        help=f"Kalshi ticker for field source (default: {DEFAULT_KALSHI_TICKER})"
    )
    parser.add_argument(
        "--field-source",
        type=str,
        choices=["datagolf", "kalshi"],
        default="datagolf",
        help="Field source: datagolf (default) or kalshi"
    )
    args = parser.parse_args()

    event_slug = args.event_slug
    field_source = args.field_source
    output_dir = DATA_DIR / "model"
    output_file = output_dir / f"{event_slug}.json"

    print(f"Event: {event_slug}")
    print(f"Field source: {field_source}")
    print("Loading data...")

    # Load skill sources
    try:
        skill_by_id, skill_by_name = load_skill_ratings()
        print(f"  Skill ratings: {len(skill_by_id)} by ID, {len(skill_by_name)} by name")
    except FileNotFoundError:
        print(f"Error: Skill ratings not found: {SKILL_RATINGS_FILE}")
        sys.exit(1)

    try:
        rankings_by_id, rankings_by_name = load_rankings()
        print(f"  Rankings: {len(rankings_by_id)} by ID, {len(rankings_by_name)} by name")
    except FileNotFoundError:
        print(f"Warning: Rankings not found, skipping fallback tier")
        rankings_by_id, rankings_by_name = {}, {}

    # Load field based on source
    if field_source == "datagolf":
        field_file = DATA_DIR / "datagolf" / f"field-{event_slug}.json"
        try:
            field, event_name = load_field_datagolf(field_file)
            print(f"  Field: {len(field)} players ({event_name})")
        except FileNotFoundError:
            print(f"Error: Field not found: {field_file}")
            sys.exit(1)
    else:  # kalshi
        kalshi_file = DATA_DIR / "kalshi" / f"{args.kalshi_ticker}.json"
        try:
            field, event_name = load_field_kalshi(kalshi_file)
            print(f"  Field: {len(field)} players ({event_name})")
        except FileNotFoundError:
            print(f"Error: Kalshi file not found: {kalshi_file}")
            sys.exit(1)

    # Build player list with tiered skill sources
    players = []
    source_counts = {"skill_ratings": 0, "rankings": 0, "field_fallback": 0}
    unmatched = []

    for i, p in enumerate(field):
        dg_id = p.get("dg_id")
        player_name = p.get("player_name", "Unknown")
        normalized = p.get("normalized_name", normalize_name(player_name))

        sg_total = None
        skill_source = None
        matched_name = None

        # For Data Golf field, we have dg_id - use it directly
        if dg_id is not None:
            if dg_id in skill_by_id:
                sg_total = skill_by_id[dg_id]["sg_total"]
                skill_source = "skill_ratings"
            elif dg_id in rankings_by_id:
                sg_total = rankings_by_id[dg_id]["sg_total"]
                skill_source = "rankings"

        # For Kalshi field (or DG field fallback), match by normalized name
        if sg_total is None and normalized:
            if normalized in skill_by_name:
                match = skill_by_name[normalized]
                sg_total = match["sg_total"]
                skill_source = "skill_ratings"
                matched_name = match.get("player_name")
                if dg_id is None:
                    dg_id = match.get("dg_id")
            elif normalized in rankings_by_name:
                match = rankings_by_name[normalized]
                sg_total = match["sg_total"]
                skill_source = "rankings"
                matched_name = match.get("player_name")
                if dg_id is None:
                    dg_id = match.get("dg_id")

        # Fallback
        if sg_total is None:
            skill_source = "field_fallback"
            unmatched.append(player_name)

        source_counts[skill_source] = source_counts.get(skill_source, 0) + 1

        players.append({
            "player_idx": i,
            "dg_id": dg_id,
            "player_name": player_name,
            "matched_name": matched_name,
            "sg_total": sg_total,
            "skill_source": skill_source,
            "placeholder_rating": skill_source == "field_fallback",
        })

    # Compute field minimum for fallback players
    known_skills = [p["sg_total"] for p in players if p["sg_total"] is not None]
    if known_skills:
        field_min = min(known_skills)
        fallback_skill = field_min - FALLBACK_OFFSET
    else:
        fallback_skill = -2.0
        field_min = -1.5

    # Assign fallback skill to players missing ratings
    for p in players:
        if p["sg_total"] is None:
            p["sg_total"] = fallback_skill

    # Report skill source distribution
    print(f"\nSkill sources:")
    for source in ["skill_ratings", "rankings", "field_fallback"]:
        count = source_counts.get(source, 0)
        if count > 0:
            print(f"  {source}: {count}")

    matched_count = source_counts.get("skill_ratings", 0) + source_counts.get("rankings", 0)
    print(f"\nMatched: {matched_count}/{len(field)} players")

    if unmatched:
        print(f"\nUnmatched ({len(unmatched)}):")
        for name in sorted(unmatched):
            print(f"  - {name}")

    if source_counts.get("field_fallback", 0) > 0:
        print(f"\nFallback skill: {fallback_skill:.3f} (field min {field_min:.3f} - {FALLBACK_OFFSET})")

    # Show skill range
    sg_values = [p["sg_total"] for p in players]
    print(f"Field sg_total range: {min(sg_values):.3f} to {max(sg_values):.3f}")

    # Run simulation
    print(f"\nRunning Monte Carlo ({NUM_SIMULATIONS:,} simulations, {NUM_ROUNDS} rounds)...")
    np.random.seed(42)
    win_probs = run_simulation(players)

    # Add win_prob to player records
    for i, p in enumerate(players):
        p["win_prob"] = win_probs[i]

    # Sort by win probability descending
    players.sort(key=lambda p: p["win_prob"], reverse=True)

    # Clean up output - remove internal fields
    for p in players:
        del p["player_idx"]
        if p.get("matched_name") is None:
            del p["matched_name"]

    # Build output
    output = {
        "source": "model",
        "fetched_at": datetime.now(timezone.utc).isoformat(),
        "event_name": event_name,
        "field_source": field_source,
        "model_version": MODEL_VERSION,
        "parameters": {
            "num_simulations": NUM_SIMULATIONS,
            "num_rounds": NUM_ROUNDS,
            "round_stddev": ROUND_STDDEV,
            "fallback_offset": FALLBACK_OFFSET,
            "fallback_skill": fallback_skill if source_counts.get("field_fallback", 0) > 0 else None,
        },
        "skill_sources": source_counts,
        "player_count": len(players),
        "players": players,
    }

    # Save
    output_dir.mkdir(parents=True, exist_ok=True)
    with open(output_file, "w") as f:
        json.dump(output, f, indent=2)
    print(f"\nSaved to: {output_file}")

    # Print results
    total_prob = sum(p["win_prob"] for p in players)
    print(f"\nTotal win probability sum: {total_prob * 100:.2f}%")

    print("\n" + "=" * 80)
    print(f"{'Player':<25} {'Source':<15} {'SG Total':>10} {'Win Prob':>10}")
    print("=" * 80)

    for p in players[:20]:
        name = p["player_name"][:24]
        source = p["skill_source"][:14]
        sg = p["sg_total"]
        prob = p["win_prob"]

        print(f"{name:<25} {source:<15} {sg:>10.3f} {prob * 100:>9.2f}%")

    print("=" * 80)


if __name__ == "__main__":
    main()
