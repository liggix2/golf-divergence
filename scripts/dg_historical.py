#!/usr/bin/env python3
"""
Data Golf Historical Data Fetcher

Fetches historical event data from Data Golf API for analysis.
Caches responses locally to avoid redundant requests.

Usage:
    python dg_historical.py
"""

import json
import sys
import time
from datetime import datetime
from pathlib import Path

try:
    import requests
except ImportError:
    print("Error: requests library required. Install with: pip install requests")
    sys.exit(1)

SCRIPT_DIR = Path(__file__).parent.parent
DATA_DIR = SCRIPT_DIR / "data" / "datagolf" / "historical"
ENV_FILE = SCRIPT_DIR / ".env"

BASE_URL = "https://feeds.datagolf.com"

# Rate limit: 45 requests per minute = 1.33 seconds between requests
RATE_LIMIT_SLEEP = 1.5


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
    sys.exit(1)


def fetch_with_cache(api_key: str, endpoint: str, params: dict, cache_path: Path) -> dict:
    """
    Fetch from API with local caching.
    Returns cached data if file exists, otherwise fetches and saves.
    """
    if cache_path.exists():
        print(f"  Loading from cache: {cache_path.name}")
        with open(cache_path) as f:
            return json.load(f)

    url = f"{BASE_URL}{endpoint}"
    params["key"] = api_key

    print(f"  Fetching {endpoint}...")
    response = requests.get(url, params=params, timeout=120)
    response.raise_for_status()

    data = response.json()

    # Save to cache
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    with open(cache_path, "w") as f:
        json.dump(data, f, indent=2)
    print(f"  Saved to: {cache_path.name}")

    return data


def fetch_year_events(api_key: str, year: int) -> dict:
    """Fetch all PGA events for a given year."""
    cache_path = DATA_DIR / f"rounds_pga_{year}.json"

    data = fetch_with_cache(
        api_key,
        "/historical-raw-data/rounds",
        {"tour": "pga", "event_id": "all", "year": str(year), "file_format": "json"},
        cache_path
    )

    return data


def fetch_single_event(api_key: str, event_id: str, year: int) -> dict:
    """Fetch rounds data for a specific event."""
    cache_path = DATA_DIR / f"rounds_{event_id}_{year}.json"

    data = fetch_with_cache(
        api_key,
        "/historical-raw-data/rounds",
        {"tour": "pga", "event_id": event_id, "year": str(year), "file_format": "json"},
        cache_path
    )

    return data


def main():
    api_key = load_api_key()
    print("Data Golf Historical Data Fetcher")
    print("=" * 70)

    # Step 1: Fetch all 2025 PGA events to get the event list
    print("\nStep 1: Fetching PGA event IDs (via 2025 all-events request)...")
    year_data = fetch_year_events(api_key, 2025)

    # The response is a dict with event_id as keys
    event_ids = list(year_data.keys())
    print(f"\nFound {len(event_ids)} events in 2025")

    # Build event list with metadata
    events = []
    for event_id in event_ids:
        event_data = year_data[event_id]
        events.append({
            "event_id": event_id,
            "event_name": event_data.get("event_name"),
            "event_completed": event_data.get("event_completed"),
            "year": event_data.get("year"),
        })

    # Sort by completion date
    events.sort(key=lambda e: e.get("event_completed", ""), reverse=True)

    # Save event list for reference
    event_list_path = DATA_DIR / "event-ids.json"
    with open(event_list_path, "w") as f:
        json.dump({"events": events, "year": 2025, "tour": "pga"}, f, indent=2)
    print(f"  Saved event list to: {event_list_path.name}")

    print(f"\nMost recent 10 events:")
    print("-" * 70)
    for event in events[:10]:
        date = event.get("event_completed", "?")
        eid = event.get("event_id", "?")
        name = event.get("event_name", "Unknown")
        print(f"  {date} | {eid:>5} | {name}")

    # Step 2: Pick one completed event and show its structure
    print("\n" + "=" * 70)
    print("Step 2: Examining sample event structure...")

    # Pick the most recent completed event
    sample_event = events[0] if events else None

    if sample_event:
        event_id = sample_event["event_id"]
        event_name = sample_event["event_name"]
        print(f"\nSelected: {event_name}")
        print(f"Event ID: {event_id}")

        event_data = year_data[event_id]

        # Save as sample_event.json
        sample_path = DATA_DIR / "sample_event.json"
        with open(sample_path, "w") as f:
            json.dump(event_data, f, indent=2)
        print(f"Saved to: {sample_path.name}")

        # Print structure
        print(f"\n{'=' * 70}")
        print("EVENT DATA STRUCTURE")
        print("=" * 70)
        print("Top-level keys:")
        for key, value in event_data.items():
            if isinstance(value, list):
                print(f"  {key}: list ({len(value)} items)")
            elif isinstance(value, dict):
                print(f"  {key}: dict ({len(value)} keys)")
            else:
                print(f"  {key}: {type(value).__name__} = {str(value)[:50]}")

        # Show full sample player-round record
        scores = event_data.get("scores", [])
        if scores:
            print(f"\n{'=' * 70}")
            print("FULL SAMPLE PLAYER-ROUND RECORD")
            print("=" * 70)
            sample_player = scores[0]
            print(json.dumps(sample_player, indent=2))

            # Show round keys
            for key in sample_player.keys():
                if key.startswith("round_"):
                    round_data = sample_player[key]
                    print(f"\n{key} keys: {list(round_data.keys())}")
                    break
    else:
        print("No events found")

    print("\n" + "=" * 70)
    print("Historical data fetch complete.")
    print(f"Data cached in: {DATA_DIR}")


if __name__ == "__main__":
    main()
