#!/usr/bin/env python3
"""
Golf Win Probability Model v1

Monte Carlo simulation using strokes gained to estimate win probabilities.
Tiered skill sources: skill_ratings -> rankings -> inferred from DG win prob.

Usage:
    python model.py
"""

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

SCRIPT_DIR = Path(__file__).parent.parent
DATA_DIR = SCRIPT_DIR / "data"

SKILL_RATINGS_FILE = DATA_DIR / "datagolf" / "skill-ratings.json"
RANKINGS_FILE = DATA_DIR / "datagolf" / "rankings.json"
FIELD_FILE = DATA_DIR / "datagolf" / "rocket-classic-2026.json"
OUTPUT_DIR = DATA_DIR / "model"
OUTPUT_FILE = OUTPUT_DIR / "rocket-classic-2026.json"

# Model parameters
MODEL_VERSION = "v1-tiered"
NUM_SIMULATIONS = 20000
NUM_ROUNDS = 4
ROUND_STDDEV = 2.75


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


def load_field() -> list:
    """Load current tournament field with DG baseline win probs."""
    with open(FIELD_FILE) as f:
        data = json.load(f)

    return data.get("players", [])


def fit_skill_to_winprob_curve(field: list, skill_ratings: dict) -> tuple:
    """
    Fit a monotonic curve mapping sg_total -> DG baseline win probability.
    Uses log-linear regression: log(win_prob) = a * sg_total + b

    Returns (a, b) coefficients for the curve.
    """
    # Collect players with both sg_total and DG win prob
    x_vals = []  # sg_total
    y_vals = []  # log(win_prob)

    for p in field:
        dg_id = p.get("dg_id")
        win_baseline = p.get("win_baseline")

        if dg_id is None or win_baseline is None or win_baseline <= 0:
            continue

        sg_total = skill_ratings.get(dg_id)
        if sg_total is None:
            continue

        x_vals.append(sg_total)
        y_vals.append(np.log(win_baseline))

    if len(x_vals) < 10:
        raise ValueError("Not enough data points to fit curve")

    x = np.array(x_vals)
    y = np.array(y_vals)

    # Simple linear regression: y = a*x + b
    n = len(x)
    sum_x = x.sum()
    sum_y = y.sum()
    sum_xy = (x * y).sum()
    sum_x2 = (x * x).sum()

    a = (n * sum_xy - sum_x * sum_y) / (n * sum_x2 - sum_x * sum_x)
    b = (sum_y - a * sum_x) / n

    return a, b


def invert_winprob_to_skill(win_prob: float, a: float, b: float) -> float:
    """
    Invert the curve to get implied skill from win probability.
    log(win_prob) = a * skill + b  =>  skill = (log(win_prob) - b) / a
    """
    if win_prob <= 0:
        return None
    return (np.log(win_prob) - b) / a


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
    noise = np.random.normal(0, ROUND_STDDEV, (NUM_SIMULATIONS, n_players, NUM_ROUNDS))
    round_scores = expected_scores[np.newaxis, :, np.newaxis] + noise

    # Total score over 4 rounds
    totals = round_scores.sum(axis=2)

    # Find winner(s) in each simulation
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
        field = load_field()
        print(f"  Field: {len(field)} players")
    except FileNotFoundError:
        print(f"Error: Field not found: {FIELD_FILE}")
        sys.exit(1)

    # Fit curve for inferring skill from DG win prob
    print("\nFitting skill -> win_prob curve...")
    a, b = fit_skill_to_winprob_curve(field, skill_ratings)
    print(f"  log(win_prob) = {a:.4f} * sg_total + {b:.4f}")

    # Build player list with tiered skill sources
    players = []
    source_counts = {"skill_ratings": 0, "rankings": 0, "inferred_from_dg": 0}
    jackson_before = None
    jackson_after = None

    for p in field:
        dg_id = p.get("dg_id")
        player_name = p.get("player_name", "Unknown")
        win_baseline = p.get("win_baseline")

        if dg_id is None:
            continue

        # Tier 1: skill_ratings
        if dg_id in skill_ratings:
            sg_total = skill_ratings[dg_id]
            skill_source = "skill_ratings"
        # Tier 2: rankings
        elif dg_id in rankings:
            sg_total = rankings[dg_id]
            skill_source = "rankings"
        # Tier 3: infer from DG win prob
        elif win_baseline is not None and win_baseline > 0:
            sg_total = invert_winprob_to_skill(win_baseline, a, b)
            skill_source = "inferred_from_dg"
        else:
            # Last resort: can't infer
            sg_total = None
            skill_source = "missing"

        # Track Jackson Koivun before/after
        if "koivun" in player_name.lower():
            jackson_before = {
                "name": player_name,
                "dg_id": dg_id,
                "win_baseline": win_baseline,
                "old_sg": None,  # Was placeholder before
                "old_source": "placeholder",
            }

        source_counts[skill_source] = source_counts.get(skill_source, 0) + 1

        players.append({
            "dg_id": dg_id,
            "player_name": player_name,
            "sg_total": sg_total,
            "skill_source": skill_source,
            "placeholder_rating": skill_source == "inferred_from_dg",
        })

    # Report skill source distribution
    print(f"\nSkill sources:")
    for source, count in sorted(source_counts.items()):
        print(f"  {source}: {count}")

    # Check for any missing
    missing = [p for p in players if p["sg_total"] is None]
    if missing:
        print(f"\nCould not assign skill to {len(missing)} players:")
        for p in missing:
            print(f"  - {p['player_name']}")
        # Remove them from simulation
        players = [p for p in players if p["sg_total"] is not None]

    # Show skill range
    sg_values = [p["sg_total"] for p in players]
    print(f"\nField sg_total range: {min(sg_values):.3f} to {max(sg_values):.3f}")

    # Run simulation
    print(f"\nRunning Monte Carlo ({NUM_SIMULATIONS:,} simulations, {NUM_ROUNDS} rounds)...")
    np.random.seed(42)
    win_probs = run_simulation(players)

    # Add win_prob to player records
    for p in players:
        p["win_prob"] = win_probs[p["dg_id"]]

    # Sort by win probability descending
    players.sort(key=lambda p: p["win_prob"], reverse=True)

    # Track Jackson Koivun after
    for p in players:
        if "koivun" in p["player_name"].lower():
            jackson_after = {
                "name": p["player_name"],
                "sg_total": p["sg_total"],
                "skill_source": p["skill_source"],
                "win_prob": p["win_prob"],
            }
            break

    # Build output
    output = {
        "source": "model",
        "fetched_at": datetime.now(timezone.utc).isoformat(),
        "model_version": MODEL_VERSION,
        "parameters": {
            "num_simulations": NUM_SIMULATIONS,
            "num_rounds": NUM_ROUNDS,
            "round_stddev": ROUND_STDDEV,
            "curve_a": a,
            "curve_b": b,
        },
        "skill_sources": source_counts,
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

    # Load DG baseline for comparison
    dg_baseline = {p.get("dg_id"): p.get("win_baseline") for p in field}

    print("\n" + "=" * 100)
    print(f"{'Player':<22} {'Source':<15} {'SG Total':>9} {'Model':>9} {'DG Base':>9} {'Diff':>9}")
    print("=" * 100)

    for p in players[:25]:
        name = p["player_name"][:21]
        source = p["skill_source"][:14]
        sg = p["sg_total"]
        model_prob = p["win_prob"]
        dg_prob = dg_baseline.get(p["dg_id"])

        model_str = f"{model_prob * 100:.2f}%"
        if dg_prob is not None:
            dg_str = f"{dg_prob * 100:.2f}%"
            diff = (model_prob - dg_prob) * 100
            diff_str = f"{diff:+.2f}pp"
        else:
            dg_str = "—"
            diff_str = "—"

        print(f"{name:<22} {source:<15} {sg:>9.3f} {model_str:>9} {dg_str:>9} {diff_str:>9}")

    print("=" * 100)

    # Jackson Koivun before/after
    if jackson_before and jackson_after:
        print("\n" + "=" * 60)
        print("JACKSON KOIVUN BEFORE/AFTER")
        print("=" * 60)
        print(f"DG baseline win prob: {jackson_before['win_baseline'] * 100:.2f}%")
        print()
        print("BEFORE (v1-baseline):")
        print(f"  skill_source: placeholder (field min - 0.25)")
        print(f"  sg_total: ~-1.80 (estimated)")
        print(f"  win_prob: ~0.005%")
        print()
        print("AFTER (v1-tiered):")
        print(f"  skill_source: {jackson_after['skill_source']}")
        print(f"  sg_total: {jackson_after['sg_total']:.3f}")
        print(f"  win_prob: {jackson_after['win_prob'] * 100:.2f}%")
        print("=" * 60)


if __name__ == "__main__":
    main()
