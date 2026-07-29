#!/usr/bin/env python3
"""
Calibrate Model Variance

Analyzes historical round-level data to calibrate the Monte Carlo model's
variance parameters.

Usage:
    python calibrate_variance.py
"""

import json
import sys
import time
from collections import defaultdict
from pathlib import Path

try:
    import requests
except ImportError:
    print("Error: requests library required. Install with: pip install requests")
    sys.exit(1)

import numpy as np

SCRIPT_DIR = Path(__file__).parent.parent
DATA_DIR = SCRIPT_DIR / "data" / "datagolf" / "historical"
ENV_FILE = SCRIPT_DIR / ".env"

BASE_URL = "https://feeds.datagolf.com"
RATE_LIMIT_SLEEP = 1.5

YEARS = [2023, 2024, 2025]
MIN_ROUNDS = 20


def load_api_key() -> str:
    """Load API key from .env file."""
    if not ENV_FILE.exists():
        print(f"Error: .env file not found at {ENV_FILE}")
        sys.exit(1)

    with open(ENV_FILE) as f:
        for line in f:
            line = line.strip()
            if line.startswith("#") or not line:
                continue
            if line.startswith("DATAGOLF_API_KEY="):
                key = line.split("=", 1)[1].strip()
                key = key.strip('"').strip("'")
                if key:
                    return key

    print("Error: DATAGOLF_API_KEY not found in .env file")
    sys.exit(1)


def fetch_with_cache(api_key: str, year: int) -> dict:
    """Fetch year data with caching."""
    cache_path = DATA_DIR / f"rounds_pga_{year}.json"

    if cache_path.exists():
        print(f"  Loading {year} from cache...")
        with open(cache_path) as f:
            return json.load(f)

    url = f"{BASE_URL}/historical-raw-data/rounds"
    params = {
        "key": api_key,
        "tour": "pga",
        "event_id": "all",
        "year": str(year),
        "file_format": "json"
    }

    print(f"  Fetching {year}...")
    response = requests.get(url, params=params, timeout=120)
    response.raise_for_status()

    data = response.json()

    DATA_DIR.mkdir(parents=True, exist_ok=True)
    with open(cache_path, "w") as f:
        json.dump(data, f)
    print(f"  Saved to cache ({cache_path.name})")

    return data


def build_round_table(all_data: dict) -> list:
    """
    Build flat table of player-round records.
    Returns list of dicts: dg_id, event_id, year, round_num, sg_total
    """
    records = []

    for year, year_data in all_data.items():
        for event_id, event_data in year_data.items():
            scores = event_data.get("scores", [])

            for player in scores:
                dg_id = player.get("dg_id")
                if dg_id is None:
                    continue

                for round_num in range(1, 7):  # Up to 6 rounds for some events
                    round_key = f"round_{round_num}"
                    round_data = player.get(round_key)

                    if round_data is None:
                        continue

                    sg_total = round_data.get("sg_total")
                    if sg_total is None:
                        continue

                    records.append({
                        "dg_id": dg_id,
                        "event_id": event_id,
                        "year": year,
                        "round_num": round_num,
                        "sg_total": sg_total,
                    })

    return records


def compute_residuals(records: list, player_rounds: dict) -> list:
    """
    Compute leave-one-out residuals for each round.
    residual = sg_total - (player mean excluding this round)
    """
    # Pre-compute player totals and counts
    player_sums = defaultdict(float)
    player_counts = defaultdict(int)

    for r in records:
        dg_id = r["dg_id"]
        player_sums[dg_id] += r["sg_total"]
        player_counts[dg_id] += 1

    residuals = []
    for r in records:
        dg_id = r["dg_id"]
        sg = r["sg_total"]
        n = player_counts[dg_id]

        if n <= 1:
            continue

        # Leave-one-out mean
        loo_mean = (player_sums[dg_id] - sg) / (n - 1)
        residual = sg - loo_mean

        residuals.append({
            **r,
            "residual": residual,
            "loo_mean": loo_mean,
        })

    return residuals


def compute_skewness(values: list) -> float:
    """Compute skewness of a distribution."""
    n = len(values)
    if n < 3:
        return 0

    arr = np.array(values)
    mean = arr.mean()
    std = arr.std()

    if std == 0:
        return 0

    return ((arr - mean) ** 3).mean() / (std ** 3)


def analyze_by_round_number(records: list) -> None:
    """Analyze sg_total distribution by round number."""
    by_round = defaultdict(list)

    for r in records:
        rn = r["round_num"]
        if rn <= 4:  # Focus on standard 4-round events
            by_round[rn].append(r["sg_total"])

    print("\n" + "=" * 70)
    print("SG_TOTAL BY ROUND NUMBER")
    print("=" * 70)
    print(f"{'Round':<8} {'N':>10} {'Mean':>10} {'Std':>10}")
    print("-" * 70)

    for rn in sorted(by_round.keys()):
        values = by_round[rn]
        arr = np.array(values)
        print(f"{rn:<8} {len(values):>10,} {arr.mean():>10.3f} {arr.std():>10.3f}")


def analyze_within_tournament_correlation(residuals: list) -> None:
    """
    For each player-event with 2+ rounds, correlate residuals across round pairs.
    """
    # Group by player-event
    player_events = defaultdict(list)
    for r in residuals:
        key = (r["dg_id"], r["event_id"], r["year"])
        player_events[key].append(r["residual"])

    # Compute pairwise correlations
    correlations = []

    for key, resids in player_events.items():
        if len(resids) < 2:
            continue

        # All pairwise correlations within this player-event
        for i in range(len(resids)):
            for j in range(i + 1, len(resids)):
                correlations.append(resids[i] * resids[j])

    if correlations:
        # Average pairwise product (proxy for correlation)
        arr = np.array(correlations)

        # Also compute actual correlation using all pairs
        # Group residuals by position in event
        r1_list = []
        r2_list = []
        for key, resids in player_events.items():
            if len(resids) >= 2:
                r1_list.append(resids[0])
                r2_list.append(resids[1])

        if len(r1_list) > 10:
            corr = np.corrcoef(r1_list, r2_list)[0, 1]
        else:
            corr = 0

        print("\n" + "=" * 70)
        print("WITHIN-TOURNAMENT CORRELATION")
        print("=" * 70)
        print(f"Player-events with 2+ rounds: {len([k for k, v in player_events.items() if len(v) >= 2]):,}")
        print(f"Total pairwise products: {len(correlations):,}")
        print(f"Mean pairwise product: {arr.mean():.4f}")
        print(f"Round 1 vs Round 2 correlation: {corr:.4f}")


def analyze_by_skill_tier(residuals: list, records: list) -> None:
    """Split residual std by player skill tier."""
    # Compute player mean sg_total
    player_sums = defaultdict(float)
    player_counts = defaultdict(int)

    for r in records:
        dg_id = r["dg_id"]
        player_sums[dg_id] += r["sg_total"]
        player_counts[dg_id] += 1

    player_means = {
        dg_id: player_sums[dg_id] / player_counts[dg_id]
        for dg_id in player_sums
    }

    # Sort players by mean sg_total
    sorted_players = sorted(player_means.items(), key=lambda x: x[1], reverse=True)

    # Assign tiers
    player_tiers = {}
    for i, (dg_id, _) in enumerate(sorted_players):
        if i < 25:
            player_tiers[dg_id] = "Top 25"
        elif i < 75:
            player_tiers[dg_id] = "26-75"
        elif i < 150:
            player_tiers[dg_id] = "76-150"
        else:
            player_tiers[dg_id] = "151+"

    # Group residuals by tier
    tier_residuals = defaultdict(list)
    for r in residuals:
        tier = player_tiers.get(r["dg_id"], "Unknown")
        tier_residuals[tier].append(r["residual"])

    print("\n" + "=" * 70)
    print("RESIDUAL STD BY SKILL TIER")
    print("=" * 70)
    print(f"{'Tier':<12} {'Players':>10} {'Rounds':>10} {'Resid Std':>12}")
    print("-" * 70)

    tier_order = ["Top 25", "26-75", "76-150", "151+"]
    for tier in tier_order:
        resids = tier_residuals.get(tier, [])
        if resids:
            arr = np.array(resids)
            n_players = len([p for p, t in player_tiers.items() if t == tier])
            print(f"{tier:<12} {n_players:>10} {len(resids):>10,} {arr.std():>12.3f}")


def main():
    api_key = load_api_key()
    print("Variance Calibration Analysis")
    print("=" * 70)

    # Step 1: Fetch data for all years
    print("\nStep 1: Loading historical data...")
    all_data = {}
    for i, year in enumerate(YEARS):
        if i > 0:
            time.sleep(RATE_LIMIT_SLEEP)
        all_data[year] = fetch_with_cache(api_key, year)
        print(f"  {year}: {len(all_data[year])} events")

    # Step 2: Build round table
    print("\nStep 2: Building round table...")
    records = build_round_table(all_data)
    print(f"  Total rounds (with sg_total): {len(records):,}")

    # Count unique players
    all_players = set(r["dg_id"] for r in records)
    print(f"  Unique players: {len(all_players):,}")

    # Step 3: Filter to players with 20+ rounds
    print(f"\nStep 3: Filtering to players with {MIN_ROUNDS}+ rounds...")
    player_counts = defaultdict(int)
    for r in records:
        player_counts[r["dg_id"]] += 1

    qualified_players = {p for p, c in player_counts.items() if c >= MIN_ROUNDS}
    print(f"  Qualified players: {len(qualified_players):,}")

    records = [r for r in records if r["dg_id"] in qualified_players]
    print(f"  Rounds after filter: {len(records):,}")

    # Step 4: Compute residuals
    print("\nStep 4: Computing leave-one-out residuals...")
    residuals = compute_residuals(records, player_counts)
    print(f"  Residuals computed: {len(residuals):,}")

    # Step 5: Residual statistics
    resid_values = [r["residual"] for r in residuals]
    arr = np.array(resid_values)

    print("\n" + "=" * 70)
    print("RESIDUAL STATISTICS")
    print("=" * 70)
    print(f"N:                {len(arr):,}")
    print(f"Mean:             {arr.mean():.4f}")
    print(f"Standard Dev:     {arr.std():.4f}")
    print(f"Skewness:         {compute_skewness(resid_values):.4f}")
    print()
    print("Percentiles:")
    for p in [1, 5, 25, 50, 75, 95, 99]:
        print(f"  {p:>3}th: {np.percentile(arr, p):>8.3f}")

    # Step 6: By round number
    analyze_by_round_number(records)

    # Step 7: Within-tournament correlation
    analyze_within_tournament_correlation(residuals)

    # Step 8: By skill tier
    analyze_by_skill_tier(residuals, records)

    print("\n" + "=" * 70)
    print("Analysis complete.")


if __name__ == "__main__":
    main()
