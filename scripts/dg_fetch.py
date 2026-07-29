#!/usr/bin/env python3
"""
Data Golf API Fetcher

Fetches pre-tournament predictions from Data Golf API.
Parses player win probabilities from all available model variants.

Usage:
    python dg_fetch.py           # Fetch and parse pre-tournament predictions
    python dg_fetch.py --raw     # Dump raw responses for discovery
"""

import argparse
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

try:
    import requests
except ImportError:
    print("Error: requests library required. Install with: pip install requests")
    sys.exit(1)

SCRIPT_DIR = Path(__file__).parent.parent
DATA_DIR = SCRIPT_DIR / "data" / "datagolf"
ENV_FILE = SCRIPT_DIR / ".env"

BASE_URL = "https://feeds.datagolf.com"


def load_api_key() -> str:
    """Load API key from .env file."""
    if not ENV_FILE.exists():
        print(f"Error: .env file not found at {ENV_FILE}")
        print("Create it with: DATAGOLF_API_KEY=your_key_here")
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
    print("Add it with: DATAGOLF_API_KEY=your_key_here")
    sys.exit(1)


def last_first_to_first_last(name: str) -> str:
    """Convert 'Last, First' format to 'First Last'."""
    if ',' in name:
        parts = name.split(',', 1)
        if len(parts) == 2:
            return f"{parts[1].strip()} {parts[0].strip()}"
    return name


def slugify(text: str) -> str:
    """Convert text to URL-friendly slug."""
    text = text.lower()
    text = re.sub(r'[^a-z0-9]+', '-', text)
    return text.strip('-')


def fetch_pretournament(api_key: str) -> dict:
    """Fetch pre-tournament predictions."""
    url = f"{BASE_URL}/preds/pre-tournament"
    params = {"key": api_key, "tour": "pga", "file_format": "json"}

    print("Fetching pre-tournament predictions...")
    response = requests.get(url, params=params, timeout=30)
    response.raise_for_status()
    return response.json()


def fetch_skill_ratings(api_key: str) -> dict:
    """Fetch skill ratings."""
    url = f"{BASE_URL}/preds/skill-ratings"
    params = {"key": api_key, "file_format": "json"}

    print("Fetching skill ratings...")
    response = requests.get(url, params=params, timeout=30)
    response.raise_for_status()
    return response.json()


def fetch_rankings(api_key: str) -> dict:
    """Fetch Data Golf rankings."""
    url = f"{BASE_URL}/preds/get-dg-rankings"
    params = {"key": api_key, "file_format": "json"}

    print("Fetching rankings...")
    response = requests.get(url, params=params, timeout=30)
    response.raise_for_status()
    return response.json()


def parse_and_save(data: dict) -> None:
    """Parse pre-tournament data and save structured output."""
    event_name = data.get("event_name", "Unknown Event")
    last_updated = data.get("last_updated", "")
    models = data.get("models_available", [])

    if not models:
        print("Error: No models found in response")
        sys.exit(1)

    print(f"Event: {event_name}")
    print(f"Models: {', '.join(models)}")

    # Build player records by dg_id
    players_by_id = {}

    for model in models:
        model_data = data.get(model, [])
        for player in model_data:
            dg_id = player.get("dg_id")
            if dg_id is None:
                continue

            if dg_id not in players_by_id:
                raw_name = player.get("player_name", "")
                players_by_id[dg_id] = {
                    "dg_id": dg_id,
                    "player_name": last_first_to_first_last(raw_name),
                }

            win_prob = player.get("win")
            if win_prob is not None:
                players_by_id[dg_id][f"win_{model}"] = win_prob

    players = list(players_by_id.values())
    players.sort(key=lambda p: p.get("win_baseline", 0), reverse=True)

    # Build output
    output = {
        "source": "datagolf",
        "fetched_at": datetime.now(timezone.utc).isoformat(),
        "event_name": event_name,
        "last_updated": last_updated,
        "models": models,
        "player_count": len(players),
        "players": players,
    }

    # Save to file
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    filename = f"{slugify(event_name)}-2026.json"
    output_path = DATA_DIR / filename
    with open(output_path, "w") as f:
        json.dump(output, f, indent=2)

    print(f"Saved to: {output_path}")
    print(f"Players: {len(players)}")

    # Print win probability sums per model
    print()
    for model in models:
        key = f"win_{model}"
        total = sum(p.get(key, 0) for p in players)
        print(f"  {model} win prob sum: {total * 100:.1f}%")

    return players


def parse_skill_ratings(data: dict, field_players: list) -> None:
    """Parse skill ratings and save structured output."""
    last_updated = data.get("last_updated", "")
    raw_players = data.get("players", [])

    players = []
    for player in raw_players:
        dg_id = player.get("dg_id")
        if dg_id is None:
            continue

        raw_name = player.get("player_name", "")
        players.append({
            "dg_id": dg_id,
            "player_name": last_first_to_first_last(raw_name),
            "sg_total": player.get("sg_total"),
            "sg_ott": player.get("sg_ott"),
            "sg_app": player.get("sg_app"),
            "sg_arg": player.get("sg_arg"),
            "sg_putt": player.get("sg_putt"),
        })

    players.sort(key=lambda p: p.get("sg_total") or 0, reverse=True)

    # Build output
    output = {
        "source": "datagolf",
        "fetched_at": datetime.now(timezone.utc).isoformat(),
        "last_updated": last_updated,
        "player_count": len(players),
        "players": players,
    }

    # Save to file
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    output_path = DATA_DIR / "skill-ratings.json"
    with open(output_path, "w") as f:
        json.dump(output, f, indent=2)

    print(f"Saved to: {output_path}")
    print(f"Players: {len(players)}")

    # Cross-reference with tournament field
    skill_ids = {p["dg_id"] for p in players}
    field_ids = {p["dg_id"] for p in field_players}

    have_ratings = field_ids & skill_ids
    missing_ratings = field_ids - skill_ids

    print(f"\nField coverage: {len(have_ratings)}/{len(field_ids)} players have skill ratings")

    if missing_ratings:
        missing_names = [p["player_name"] for p in field_players if p["dg_id"] in missing_ratings]
        print(f"Missing ratings ({len(missing_ratings)}):")
        for name in sorted(missing_names):
            print(f"  - {name}")

    return skill_ids, missing_ratings


def parse_rankings(data: dict, field_players: list, skill_ids: set, missing_from_skills: set) -> None:
    """Parse rankings and save structured output. Validate scale against skill ratings."""
    last_updated = data.get("last_updated", "")
    raw_rankings = data.get("rankings", [])

    print(f"\nRankings endpoint fields (sample):")
    if raw_rankings:
        sample = raw_rankings[0]
        for key in sorted(sample.keys()):
            print(f"  {key}: {type(sample[key]).__name__} = {repr(sample[key])[:40]}")

    players = []
    for player in raw_rankings:
        dg_id = player.get("dg_id")
        if dg_id is None:
            continue

        raw_name = player.get("player_name", "")
        players.append({
            "dg_id": dg_id,
            "player_name": last_first_to_first_last(raw_name),
            "dg_rank": player.get("datagolf_rank"),
            "dg_skill_estimate": player.get("dg_skill_estimate"),
        })

    players.sort(key=lambda p: p.get("dg_rank") or 999)

    # Build output
    output = {
        "source": "datagolf",
        "fetched_at": datetime.now(timezone.utc).isoformat(),
        "last_updated": last_updated,
        "player_count": len(players),
        "players": players,
    }

    # Save to file
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    output_path = DATA_DIR / "rankings.json"
    with open(output_path, "w") as f:
        json.dump(output, f, indent=2)

    print(f"\nSaved to: {output_path}")
    print(f"Players: {len(players)}")

    # Load skill ratings for comparison
    skill_ratings_file = DATA_DIR / "skill-ratings.json"
    if skill_ratings_file.exists():
        with open(skill_ratings_file) as f:
            skill_data = json.load(f)
        skill_by_id = {p["dg_id"]: p["sg_total"] for p in skill_data["players"] if p.get("sg_total") is not None}

        # Find players in both
        rankings_by_id = {p["dg_id"]: p["dg_skill_estimate"] for p in players if p.get("dg_skill_estimate") is not None}
        common_ids = set(skill_by_id.keys()) & set(rankings_by_id.keys())

        if common_ids:
            sg_totals = [skill_by_id[i] for i in common_ids]
            skill_estimates = [rankings_by_id[i] for i in common_ids]

            # Compute correlation and mean difference
            n = len(common_ids)
            mean_sg = sum(sg_totals) / n
            mean_est = sum(skill_estimates) / n

            # Pearson correlation
            num = sum((sg_totals[i] - mean_sg) * (skill_estimates[i] - mean_est) for i in range(n))
            denom_sg = sum((x - mean_sg) ** 2 for x in sg_totals) ** 0.5
            denom_est = sum((x - mean_est) ** 2 for x in skill_estimates) ** 0.5
            corr = num / (denom_sg * denom_est) if denom_sg * denom_est > 0 else 0

            # Mean difference
            diffs = [skill_estimates[i] - sg_totals[i] for i in range(n)]
            mean_diff = sum(diffs) / n

            print(f"\nScale validation ({n} players in both):")
            print(f"  Correlation (dg_skill_estimate vs sg_total): {corr:.4f}")
            print(f"  Mean difference (estimate - sg_total): {mean_diff:+.4f}")
            print(f"  sg_total range: {min(sg_totals):.3f} to {max(sg_totals):.3f}")
            print(f"  dg_skill_estimate range: {min(skill_estimates):.3f} to {max(skill_estimates):.3f}")

    # Check coverage of missing field players
    ranking_ids = {p["dg_id"] for p in players}
    field_ids = {p["dg_id"] for p in field_players}
    covered_by_rankings = missing_from_skills & ranking_ids

    print(f"\nMissing from skills but covered by rankings: {len(covered_by_rankings)}/{len(missing_from_skills)}")
    if covered_by_rankings:
        covered_names = [p["player_name"] for p in field_players if p["dg_id"] in covered_by_rankings]
        for name in sorted(covered_names):
            print(f"  + {name}")

    still_missing = missing_from_skills - ranking_ids
    if still_missing:
        print(f"\nStill missing ({len(still_missing)}):")
        still_missing_names = [p["player_name"] for p in field_players if p["dg_id"] in still_missing]
        for name in sorted(still_missing_names):
            print(f"  - {name}")


def dump_raw(api_key: str) -> None:
    """Dump raw responses for discovery."""
    print("Data Golf API Discovery")
    print("=" * 60)

    # Pre-tournament predictions
    print("Fetching /preds/pre-tournament...")
    url = f"{BASE_URL}/preds/pre-tournament"
    params = {"key": api_key, "tour": "pga", "file_format": "json"}
    response = requests.get(url, params=params, timeout=30)
    response.raise_for_status()
    data = response.json()

    DATA_DIR.mkdir(parents=True, exist_ok=True)
    output_path = DATA_DIR / "raw_pretournament.json"
    with open(output_path, "w") as f:
        json.dump(data, f, indent=2)
    print(f"  Saved to: {output_path}")

    print("\nTop-level keys:")
    for key, value in data.items():
        if isinstance(value, list):
            print(f"  {key}: list ({len(value)} items)")
        else:
            print(f"  {key}: {repr(value)[:50]}")

    # Skill ratings
    print("\nFetching /preds/skill-ratings...")
    url = f"{BASE_URL}/preds/skill-ratings"
    params = {"key": api_key, "file_format": "json"}
    response = requests.get(url, params=params, timeout=30)
    response.raise_for_status()
    data = response.json()

    output_path = DATA_DIR / "raw_skillratings.json"
    with open(output_path, "w") as f:
        json.dump(data, f, indent=2)
    print(f"  Saved to: {output_path}")

    print("\n" + "=" * 60)
    print("Discovery complete.")


def main():
    parser = argparse.ArgumentParser(description="Fetch Data Golf predictions")
    parser.add_argument(
        "--raw",
        action="store_true",
        help="Dump raw responses for discovery instead of parsing"
    )
    args = parser.parse_args()

    api_key = load_api_key()

    if args.raw:
        dump_raw(api_key)
    else:
        # Fetch and parse pre-tournament predictions
        pretournament_data = fetch_pretournament(api_key)
        field_players = parse_and_save(pretournament_data)

        print()

        # Fetch and parse skill ratings
        skills_data = fetch_skill_ratings(api_key)
        skill_ids, missing_from_skills = parse_skill_ratings(skills_data, field_players)

        # Fetch and parse rankings (fallback skill source)
        rankings_data = fetch_rankings(api_key)
        parse_rankings(rankings_data, field_players, skill_ids, missing_from_skills)


if __name__ == "__main__":
    main()
