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
        data = fetch_pretournament(api_key)
        parse_and_save(data)


if __name__ == "__main__":
    main()
