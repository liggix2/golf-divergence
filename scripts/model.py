#!/usr/bin/env python3
"""
Golf Win Probability Model v1

Monte Carlo simulation using strokes gained to estimate win probabilities.

Usage:
    python model.py
"""

import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import numpy as np

SCRIPT_DIR = Path(__file__).parent.parent
DATA_DIR = SCRIPT_DIR / "data"

SKILL_RATINGS_FILE = DATA_DIR / "datagolf" / "skill-ratings.json"
FIELD_FILE = DATA_DIR / "datagolf" / "rocket-classic-2026.json"
OUTPUT_DIR = DATA_DIR / "model"
OUTPUT_FILE = OUTPUT_DIR / "rocket-classic-2026.json"

# Model parameters
MODEL_VERSION = "v1-baseline"
NUM_SIMULATIONS = 20000
NUM_ROUNDS = 4
ROUND_STDDEV = 2.75
PLACEHOLDER_PENALTY = 0.25


def load_skill_ratings() -> dict:
    """Load skill ratings indexed by dg_id."""
    with open(SKILL_RATINGS_FILE) as f:
        data = json.load(f)

    ratings = {}
    for player in data.get("players", []):
        dg_id = player.get("dg_id")
        if dg_id is not None:
            ratings[dg_id] = player

    return ratings


def load_field() -> list:
    """Load current tournament field."""
    with open(FIELD_FILE) as f:
        data = json.load(f)

    return data.get("players", [])


def load_datagolf_baseline() -> dict:
    """Load Data Golf baseline win probabilities for comparison."""
    with open(FIELD_FILE) as f:
        data = json.load(f)

    probs = {}
    for player in data.get("players", []):
        dg_id = player.get("dg_id")
        win_baseline = player.get("win_baseline")
        if dg_id is not None and win_baseline is not None:
            probs[dg_id] = win_baseline

    return probs


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

    # Expected score per round (lower is better, so negate sg_total)
    expected_scores = -sg_totals

    # Simulate all rounds for all players
    # Shape: (NUM_SIMULATIONS, n_players, NUM_ROUNDS)
    noise = np.random.normal(0, ROUND_STDDEV, (NUM_SIMULATIONS, n_players, NUM_ROUNDS))
    round_scores = expected_scores[np.newaxis, :, np.newaxis] + noise

    # Total score over 4 rounds
    totals = round_scores.sum(axis=2)  # Shape: (NUM_SIMULATIONS, n_players)

    # Find winner(s) in each simulation
    win_counts = np.zeros(n_players)

    for sim in range(NUM_SIMULATIONS):
        sim_totals = totals[sim]
        min_score = sim_totals.min()
        winners = np.where(sim_totals == min_score)[0]
        # Split win evenly among ties
        win_share = 1.0 / len(winners)
        for w in winners:
            win_counts[w] += win_share

    # Convert to probabilities
    win_probs = win_counts / NUM_SIMULATIONS

    return {dg_id: prob for dg_id, prob in zip(dg_ids, win_probs)}


def main():
    print("Loading data...")
    try:
        skill_ratings = load_skill_ratings()
        print(f"  Skill ratings: {len(skill_ratings)} players")
    except FileNotFoundError:
        print(f"Error: Skill ratings not found: {SKILL_RATINGS_FILE}")
        sys.exit(1)

    try:
        field = load_field()
        print(f"  Field: {len(field)} players")
    except FileNotFoundError:
        print(f"Error: Field not found: {FIELD_FILE}")
        sys.exit(1)

    dg_baseline = load_datagolf_baseline()

    # Build player list with sg_total
    players = []
    missing_rating = []

    for p in field:
        dg_id = p.get("dg_id")
        player_name = p.get("player_name", "Unknown")

        if dg_id is None:
            continue

        rating = skill_ratings.get(dg_id)
        if rating and rating.get("sg_total") is not None:
            sg_total = rating["sg_total"]
            is_placeholder = False
        else:
            sg_total = None
            is_placeholder = True
            missing_rating.append(player_name)

        players.append({
            "dg_id": dg_id,
            "player_name": player_name,
            "sg_total": sg_total,
            "placeholder_rating": is_placeholder,
        })

    # Calculate field minimum and assign placeholder rating
    rated_sg = [p["sg_total"] for p in players if p["sg_total"] is not None]
    if not rated_sg:
        print("Error: No players with skill ratings")
        sys.exit(1)

    field_min_sg = min(rated_sg)
    placeholder_sg = field_min_sg - PLACEHOLDER_PENALTY

    print(f"\nField sg_total range: {min(rated_sg):.3f} to {max(rated_sg):.3f}")
    print(f"Placeholder sg_total: {placeholder_sg:.3f} (min - {PLACEHOLDER_PENALTY})")
    print(f"Players with placeholder rating: {len(missing_rating)}")

    for p in players:
        if p["sg_total"] is None:
            p["sg_total"] = placeholder_sg

    # Run simulation
    print(f"\nRunning Monte Carlo ({NUM_SIMULATIONS:,} simulations, {NUM_ROUNDS} rounds)...")
    np.random.seed(42)  # Reproducibility
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
        "model_version": MODEL_VERSION,
        "parameters": {
            "num_simulations": NUM_SIMULATIONS,
            "num_rounds": NUM_ROUNDS,
            "round_stddev": ROUND_STDDEV,
            "placeholder_penalty": PLACEHOLDER_PENALTY,
        },
        "player_count": len(players),
        "players": players,
    }

    # Save
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    with open(OUTPUT_FILE, "w") as f:
        json.dump(output, f, indent=2)
    print(f"\nSaved to: {OUTPUT_FILE}")

    # Print results
    total_prob = sum(p["win_prob"] for p in players)
    print(f"\nTotal win probability sum: {total_prob * 100:.2f}%")

    print("\n" + "=" * 85)
    print(f"{'Player':<25} {'SG Total':>10} {'Model':>10} {'DG Base':>10} {'Diff':>10} {'Flag':>6}")
    print("=" * 85)

    for p in players[:20]:
        name = p["player_name"][:24]
        sg = p["sg_total"]
        model_prob = p["win_prob"]
        dg_prob = dg_baseline.get(p["dg_id"])
        flag = "*" if p["placeholder_rating"] else ""

        model_str = f"{model_prob * 100:.2f}%"
        if dg_prob is not None:
            dg_str = f"{dg_prob * 100:.2f}%"
            diff = (model_prob - dg_prob) * 100
            diff_str = f"{diff:+.2f}pp"
        else:
            dg_str = "—"
            diff_str = "—"

        print(f"{name:<25} {sg:>10.3f} {model_str:>10} {dg_str:>10} {diff_str:>10} {flag:>6}")

    print("=" * 85)
    print("* = placeholder rating (field min - 0.25)")

    if missing_rating:
        print(f"\nPlayers with placeholder ratings ({len(missing_rating)}):")
        for name in sorted(missing_rating):
            print(f"  - {name}")


if __name__ == "__main__":
    main()
