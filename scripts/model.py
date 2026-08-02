#!/usr/bin/env python3
"""
Golf Win Probability Model v2

Monte Carlo simulation using strokes gained to estimate win probabilities.
Tiered skill sources: skill_ratings -> rankings -> field-minimum fallback.

Usage:
    python model.py [--event-slug EVENT_SLUG]
"""

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

SCRIPT_DIR = Path(__file__).parent.parent
DATA_DIR = SCRIPT_DIR / "data"

DEFAULT_EVENT_SLUG = "wyndham-championship-2026"

SKILL_RATINGS_FILE = DATA_DIR / "datagolf" / "skill-ratings.json"
RANKINGS_FILE = DATA_DIR / "datagolf" / "rankings.json"

MODEL_VERSION = "v2-field-based"
NUM_SIMULATIONS = 20000
NUM_ROUNDS = 4
ROUND_STDDEV = 2.75

FALLBACK_OFFSET = 0.5


def load_skill_ratings() -> dict:
    """Load skill ratings indexed by dg_id."""
    with open(SKILL_RATINGS_FILE) as f:
        data = json.load(f)

    ratings = {}
    for player in data.get("players", []):
        dg_id = player.get("dg_id")
        sg_total = player.get("sg_total")
        if dg_id is not None and sg_total is not None:
            ratings[dg_id] = sg_total

    return ratings


def load_rankings() -> dict:
    """Load rankings skill estimates indexed by dg_id."""
    with open(RANKINGS_FILE) as f:
        data = json.load(f)

    rankings = {}
    for player in data.get("players", []):
        dg_id = player.get("dg_id")
        skill_est = player.get("dg_skill_estimate")
        if dg_id is not None and skill_est is not None:
            rankings[dg_id] = skill_est

    return rankings


def load_field(field_file: Path) -> tuple:
    """Load current tournament field from field-updates file."""
    with open(field_file) as f:
        data = json.load(f)

    event_name = data.get("event_name", "Unknown Event")
    return data.get("players", []), event_name


def run_simulation(players: list) -> dict:
    """
    Run Monte Carlo simulation to estimate win probabilities.

    Each player's round score is: -sg_total + Normal(0, ROUND_STDDEV)
    Lower total after 4 rounds wins. Ties split evenly.

    Returns dict of dg_id -> win probability
    """
    n_players = len(players)
    dg_ids = [p["dg_id"] for p in players]
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
    return {dg_id: prob for dg_id, prob in zip(dg_ids, win_probs)}


def main():
    parser = argparse.ArgumentParser(description="Run golf win probability model")
    parser.add_argument(
        "--event-slug",
        type=str,
        default=DEFAULT_EVENT_SLUG,
        help=f"Event slug for input/output files (default: {DEFAULT_EVENT_SLUG})"
    )
    args = parser.parse_args()

    event_slug = args.event_slug
    field_file = DATA_DIR / "datagolf" / f"field-{event_slug}.json"
    output_dir = DATA_DIR / "model"
    output_file = output_dir / f"{event_slug}.json"

    print(f"Event: {event_slug}")
    print("Loading data...")

    try:
        skill_ratings = load_skill_ratings()
        print(f"  Skill ratings: {len(skill_ratings)} players")
    except FileNotFoundError:
        print(f"Error: Skill ratings not found: {SKILL_RATINGS_FILE}")
        sys.exit(1)

    try:
        rankings = load_rankings()
        print(f"  Rankings: {len(rankings)} players")
    except FileNotFoundError:
        print(f"Warning: Rankings not found, skipping fallback tier")
        rankings = {}

    try:
        field, event_name = load_field(field_file)
        print(f"  Field: {len(field)} players ({event_name})")
    except FileNotFoundError:
        print(f"Error: Field not found: {field_file}")
        sys.exit(1)

    # Build player list with tiered skill sources
    players = []
    source_counts = {"skill_ratings": 0, "rankings": 0, "field_fallback": 0}

    for p in field:
        dg_id = p.get("dg_id")
        player_name = p.get("player_name", "Unknown")

        if dg_id is None:
            continue

        # Tier 1: skill_ratings (sg_total)
        if dg_id in skill_ratings:
            sg_total = skill_ratings[dg_id]
            skill_source = "skill_ratings"
        # Tier 2: rankings (dg_skill_estimate)
        elif dg_id in rankings:
            sg_total = rankings[dg_id]
            skill_source = "rankings"
        # Tier 3: placeholder - will be assigned field minimum later
        else:
            sg_total = None
            skill_source = "field_fallback"

        source_counts[skill_source] = source_counts.get(skill_source, 0) + 1

        players.append({
            "dg_id": dg_id,
            "player_name": player_name,
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

    # Assign fallback skill to players missing ratings
    for p in players:
        if p["sg_total"] is None:
            p["sg_total"] = fallback_skill

    # Report skill source distribution
    print(f"\nSkill sources:")
    for source, count in sorted(source_counts.items()):
        if count > 0:
            print(f"  {source}: {count}")

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
    for p in players:
        p["win_prob"] = win_probs[p["dg_id"]]

    # Sort by win probability descending
    players.sort(key=lambda p: p["win_prob"], reverse=True)

    # Build output
    output = {
        "source": "model",
        "fetched_at": datetime.now(timezone.utc).isoformat(),
        "event_name": event_name,
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
