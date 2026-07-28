#!/usr/bin/env python3
"""
DraftKings Golf Odds Fetcher

Fetches golf tournament winner odds from DraftKings sportsbook API.
Parses selections into player odds and saves to JSON.

Usage:
    python dk_fetch.py           # Fetch and parse
    python dk_fetch.py --raw     # Dump raw JSON response for debugging
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


# DraftKings API endpoint for golf tournament winner markets
URL = (
    "https://sportsbook-nash.draftkings.com/sites/US-NJ-SB/api/sportscontent/"
    "controldata/league/leagueSubcategory/v1/markets"
    "?isBatchable=false"
    "&templateVars=189706%2C4508"
    "&eventsQuery=%24filter%3DleagueId%20eq%20%27189706%27%20AND%20"
    "clientMetadata%2FSubcategories%2Fany%28s%3A%20s%2FId%20eq%20%274508%27%29"
    "&marketsQuery=%24filter%3DclientMetadata%2FsubCategoryId%20eq%20%274508%27%20AND%20"
    "tags%2Fall%28t%3A%20t%20ne%20%27SportcastBetBuilder%27%29"
    "&include=Events"
    "&entity=events"
)

# Essential headers only - dropped datadog/traceparent telemetry
HEADERS = {
    "accept": "*/*",
    "accept-language": "en-US,en;q=0.9",
    "content-type": "application/json charset=utf-8",
    "origin": "https://sportsbook.draftkings.com",
    "referer": "https://sportsbook.draftkings.com/",
    "user-agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/149.0.0.0 Safari/537.36"
    ),
    "x-client-feature": "leagueSubcategory",
    "x-client-name": "web",
    "x-client-page": "league",
    "x-client-version": "2630.3.1.9",
    "x-client-widget-name": "cms",
    "x-client-widget-version": "1.0.0",
    "x-pe-cn": "web",
    "x-pe-cv": "2630.3.1.9",
    "x-pe-ep": "SB",
    "x-pe-loc": "US-NJ",
}

SCRIPT_DIR = Path(__file__).parent.parent
DATA_DIR = SCRIPT_DIR / "data" / "draftkings"

# Market type ID for outright winner (stable across events)
OUTRIGHT_WINNER_MARKET_TYPE = "8996"

# Valid range for total implied probability (105% to 175%)
MIN_HOLD = 1.05
MAX_HOLD = 1.75


def american_to_implied(american_odds: int) -> float:
    """
    Convert American odds to implied probability.

    Args:
        american_odds: American odds as integer (e.g., 150 for +150, -150 for -150)

    Returns:
        Implied probability as decimal (e.g., 0.40 for 40%)
    """
    if american_odds >= 0:
        return 100 / (american_odds + 100)
    else:
        abs_odds = abs(american_odds)
        return abs_odds / (abs_odds + 100)


def parse_american_odds(odds_str: str) -> int:
    """
    Parse American odds string to integer.

    Args:
        odds_str: Odds string like "+990" or "-150"

    Returns:
        Integer odds (e.g., 990 or -150)
    """
    odds_str = odds_str.strip()
    if odds_str.startswith("+"):
        return int(odds_str[1:])
    else:
        return int(odds_str)


def slugify(text: str) -> str:
    """Convert text to URL-friendly slug."""
    text = text.lower()
    text = re.sub(r'[^a-z0-9]+', '-', text)
    return text.strip('-')


def fetch_data() -> dict:
    """Fetch data from DraftKings API."""
    response = requests.get(URL, headers=HEADERS, timeout=30)
    response.raise_for_status()
    return response.json()


def dump_raw(data: dict) -> None:
    """Dump raw JSON response for debugging."""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    output_path = DATA_DIR / "raw_response.json"
    with open(output_path, "w") as f:
        json.dump(data, f, indent=2)
    print(f"Saved raw response to: {output_path}")

    print("\n" + "=" * 60)
    print("TOP-LEVEL KEYS:")
    print("=" * 60)
    for key, value in data.items():
        if isinstance(value, dict):
            print(f"  {key}: dict ({len(value)} keys)")
        elif isinstance(value, list):
            print(f"  {key}: list ({len(value)} items)")
        else:
            print(f"  {key}: {type(value).__name__} = {repr(value)[:50]}")


def find_outright_market(markets: list) -> dict:
    """Find the outright winner market by marketType.id."""
    for market in markets:
        market_type = market.get("marketType", {})
        if market_type.get("id") == OUTRIGHT_WINNER_MARKET_TYPE:
            return market
    return {}


def parse_and_save(data: dict) -> None:
    """Parse selections and save to JSON file."""
    # Extract event info
    events = data.get("events", [])
    if not events:
        print("Error: No events found in response")
        sys.exit(1)

    event = events[0]
    event_id = event.get("id", "")
    event_name = event.get("name", "Unknown Event")

    # Find the outright winner market
    markets = data.get("markets", [])
    outright_market = find_outright_market(markets)
    if not outright_market:
        print(f"Error: No outright winner market found (marketType.id={OUTRIGHT_WINNER_MARKET_TYPE})")
        print("Available markets:")
        for m in markets:
            mt = m.get("marketType", {})
            print(f"  {m.get('id')}: {mt.get('name')} (type={mt.get('id')})")
        sys.exit(1)

    outright_market_id = outright_market.get("id")
    print(f"Found outright winner market: {outright_market_id}")

    # Filter selections to outright winner market only
    all_selections = data.get("selections", [])
    selections = [s for s in all_selections if s.get("marketId") == outright_market_id]

    if not selections:
        print("Error: No selections found for outright winner market")
        sys.exit(1)

    print(f"Filtered to {len(selections)} selections (from {len(all_selections)} total)")

    players = []
    for sel in selections:
        label = sel.get("label", "")
        display_odds = sel.get("displayOdds", {})
        american_str = display_odds.get("american", "+0")

        try:
            american_odds = parse_american_odds(american_str)
            implied_prob = american_to_implied(american_odds)
        except (ValueError, ZeroDivisionError):
            continue

        players.append({
            "player_name": label,
            "american_odds": american_odds,
            "implied_prob": round(implied_prob, 6),
        })

    # Sort by implied probability descending (favorites first)
    players.sort(key=lambda p: p["implied_prob"], reverse=True)

    # Validate total hold is in expected range
    total_implied = sum(p["implied_prob"] for p in players)
    if total_implied < MIN_HOLD or total_implied > MAX_HOLD:
        print()
        print("!" * 70)
        print("ERROR: Total implied probability out of expected range!")
        print(f"  Got: {total_implied * 100:.1f}%")
        print(f"  Expected: {MIN_HOLD * 100:.0f}% to {MAX_HOLD * 100:.0f}%")
        print()
        print("This likely indicates wrong market type or data corruption.")
        print("Use --raw to inspect the response.")
        print("!" * 70)
        sys.exit(1)

    # Build output
    output = {
        "source": "draftkings",
        "fetched_at": datetime.now(timezone.utc).isoformat(),
        "event_id": event_id,
        "event_name": event_name,
        "player_count": len(players),
        "players": players,
    }

    # Save to file
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    filename = f"{slugify(event_name)}.json"
    output_path = DATA_DIR / filename
    with open(output_path, "w") as f:
        json.dump(output, f, indent=2)
    print(f"Saved to: {output_path}")
    print(f"Event: {event_name}")
    print(f"Players: {len(players)}")
    print()

    # Print summary table
    print("=" * 60)
    print(f"{'Player':<30} {'Odds':>12} {'Impl.Prob':>12}")
    print("=" * 60)
    for p in players[:20]:
        name = p["player_name"][:28]
        odds = f"+{p['american_odds']}" if p["american_odds"] >= 0 else str(p["american_odds"])
        prob = f"{p['implied_prob'] * 100:.2f}%"
        print(f"{name:<30} {odds:>12} {prob:>12}")
    print("=" * 60)
    print(f"Showing top 20 of {len(players)} players")
    print()
    print(f"Total implied probability: {total_implied * 100:.1f}%")
    print(f"Book hold (overround): {(total_implied - 1) * 100:.1f}%")


def main():
    parser = argparse.ArgumentParser(description="Fetch DraftKings golf odds")
    parser.add_argument(
        "--raw",
        action="store_true",
        help="Dump raw JSON response instead of parsing"
    )
    args = parser.parse_args()

    print("Fetching DraftKings golf odds...")
    print()

    try:
        data = fetch_data()
    except requests.RequestException as e:
        print(f"Error fetching data: {e}")
        sys.exit(1)

    if args.raw:
        dump_raw(data)
    else:
        parse_and_save(data)


if __name__ == "__main__":
    main()
