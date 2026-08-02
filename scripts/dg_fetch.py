#!/usr/bin/env python3
"""
Data Golf API Fetcher

Fetches field and predictions from Data Golf API.
Field from /field-updates is authoritative; predictions are optional.

Usage:
    python dg_fetch.py --event-slug EVENT_SLUG
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

DEFAULT_EVENT_SLUG = "wyndham-championship-2026"


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


def fetch_field_updates(api_key: str) -> dict:
    """Fetch current field from /field-updates endpoint."""
    url = f"{BASE_URL}/field-updates"
    params = {"key": api_key, "tour": "pga", "file_format": "json"}

    print("Fetching field updates...")
    response = requests.get(url, params=params, timeout=30)
    response.raise_for_status()
    return response.json()


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


def parse_field(data: dict, event_slug: str) -> list:
    """
    Parse field data and save structured output.

    Returns list of field players with dg_id and player_name.
    """
    event_name = data.get("event_name", "Unknown Event")
    last_updated = data.get("last_updated", "")

    # Guard: verify event name matches expected slug
    api_slug = slugify(event_name)
    expected_base = event_slug.rsplit("-", 1)[0]  # Remove year suffix

    if not api_slug.startswith(expected_base) and expected_base not in api_slug:
        print(f"\nERROR: Event mismatch!")
        print(f"  Expected: {event_slug}")
        print(f"  API returned: {event_name} (slug: {api_slug})")
        print(f"\nThe field-updates endpoint is returning a different tournament.")
        print("Check if the tournament has started or if the slug is correct.")
        sys.exit(1)

    print(f"Event: {event_name}")

    # Parse field from the response
    raw_field = data.get("field", [])

    players = []
    for player in raw_field:
        dg_id = player.get("dg_id")
        if dg_id is None:
            continue

        raw_name = player.get("player_name", "")
        players.append({
            "dg_id": dg_id,
            "player_name": last_first_to_first_last(raw_name),
        })

    players.sort(key=lambda p: p["player_name"])

    # Build output
    output = {
        "source": "datagolf",
        "endpoint": "field-updates",
        "fetched_at": datetime.now(timezone.utc).isoformat(),
        "event_name": event_name,
        "last_updated": last_updated,
        "player_count": len(players),
        "players": players,
    }

    # Save to file
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    filename = f"field-{event_slug}.json"
    output_path = DATA_DIR / filename
    with open(output_path, "w") as f:
        json.dump(output, f, indent=2)

    print(f"Saved to: {output_path}")
    print(f"Players: {len(players)}")

    return players, event_name


def parse_predictions(data: dict, event_slug: str, field_event_name: str) -> bool:
    """
    Parse pre-tournament predictions and save structured output.

    Returns True if predictions were saved, False if skipped due to event mismatch.
    """
    pred_event_name = data.get("event_name", "Unknown Event")
    last_updated = data.get("last_updated", "")
    models = data.get("models_available", [])

    # Check if predictions are for the same event as the field
    if pred_event_name != field_event_name:
        print(f"\n  Predictions event: {pred_event_name}")
        print(f"  Field event: {field_event_name}")
        print(f"  -> Skipping predictions (not yet available for {field_event_name})")
        return False

    if not models:
        print("  Warning: No models found in response")
        return False

    print(f"  Event: {pred_event_name}")
    print(f"  Models: {', '.join(models)}")

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
        "endpoint": "pre-tournament",
        "fetched_at": datetime.now(timezone.utc).isoformat(),
        "event_name": pred_event_name,
        "last_updated": last_updated,
        "models": models,
        "player_count": len(players),
        "players": players,
    }

    # Save to file
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    filename = f"predictions-{event_slug}.json"
    output_path = DATA_DIR / filename
    with open(output_path, "w") as f:
        json.dump(output, f, indent=2)

    print(f"  Saved to: {output_path}")
    print(f"  Players: {len(players)}")

    # Print win probability sums per model
    for model in models:
        key = f"win_{model}"
        total = sum(p.get(key, 0) for p in players)
        print(f"    {model} win prob sum: {total * 100:.1f}%")

    return True


def parse_skill_ratings(data: dict, field_players: list) -> tuple:
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
    """Parse rankings and save structured output."""
    last_updated = data.get("last_updated", "")
    raw_rankings = data.get("rankings", [])

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

    # Check coverage of missing field players
    ranking_ids = {p["dg_id"] for p in players}
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

    DATA_DIR.mkdir(parents=True, exist_ok=True)

    # Field updates
    print("Fetching /field-updates...")
    url = f"{BASE_URL}/field-updates"
    params = {"key": api_key, "tour": "pga", "file_format": "json"}
    response = requests.get(url, params=params, timeout=30)
    response.raise_for_status()
    data = response.json()

    output_path = DATA_DIR / "raw_field_updates.json"
    with open(output_path, "w") as f:
        json.dump(data, f, indent=2)
    print(f"  Saved to: {output_path}")

    print("\nTop-level keys:")
    for key, value in data.items():
        if isinstance(value, list):
            print(f"  {key}: list ({len(value)} items)")
        else:
            print(f"  {key}: {repr(value)[:50]}")

    if data.get("field"):
        print("\nSample field entry:")
        sample = data["field"][0]
        for key in sorted(sample.keys()):
            print(f"  {key}: {repr(sample[key])[:50]}")

    # Pre-tournament predictions
    print("\nFetching /preds/pre-tournament...")
    url = f"{BASE_URL}/preds/pre-tournament"
    params = {"key": api_key, "tour": "pga", "file_format": "json"}
    response = requests.get(url, params=params, timeout=30)
    response.raise_for_status()
    data = response.json()

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

    print("\n" + "=" * 60)
    print("Discovery complete.")


def main():
    parser = argparse.ArgumentParser(description="Fetch Data Golf field and predictions")
    parser.add_argument(
        "--raw",
        action="store_true",
        help="Dump raw responses for discovery instead of parsing"
    )
    parser.add_argument(
        "--event-slug",
        type=str,
        default=DEFAULT_EVENT_SLUG,
        help=f"Event slug for output filename (default: {DEFAULT_EVENT_SLUG})"
    )
    args = parser.parse_args()

    api_key = load_api_key()

    if args.raw:
        dump_raw(api_key)
    else:
        event_slug = args.event_slug
        print(f"Event slug: {event_slug}")
        print()

        # Step 1: Fetch field (authoritative source)
        field_data = fetch_field_updates(api_key)
        field_players, field_event_name = parse_field(field_data, event_slug)

        print()

        # Step 2: Fetch predictions (optional - may be for different event)
        pretournament_data = fetch_pretournament(api_key)
        predictions_available = parse_predictions(pretournament_data, event_slug, field_event_name)

        print()

        # Step 3: Fetch skill ratings (always needed for model)
        skills_data = fetch_skill_ratings(api_key)
        skill_ids, missing_from_skills = parse_skill_ratings(skills_data, field_players)

        # Step 4: Fetch rankings (fallback skill source)
        rankings_data = fetch_rankings(api_key)
        parse_rankings(rankings_data, field_players, skill_ids, missing_from_skills)

        # Summary
        print("\n" + "=" * 60)
        print("SUMMARY")
        print("=" * 60)
        print(f"Field: {field_event_name} ({len(field_players)} players)")
        print(f"Predictions: {'available' if predictions_available else 'not yet available'}")
        print(f"Skill ratings coverage: {len(skill_ids & {p['dg_id'] for p in field_players})}/{len(field_players)}")


if __name__ == "__main__":
    main()
