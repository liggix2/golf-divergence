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


# =============================================================================
# DRAFTKINGS CONFIGURATION
# =============================================================================

SUBCATEGORY_ID = "4508"  # Tournament Winner market (stable across events)
API_BASE = "https://sportsbook-nash.draftkings.com/sites/US-NJ-SB/api/sportscontent"
GOLF_PAGE_URL = "https://sportsbook.draftkings.com/leagues/golf"

# Golf sport display group ID (stable)
GOLF_DISPLAY_GROUP_ID = 12

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


def fetch_golf_leagues() -> dict:
    """
    Fetch golf leagues from DraftKings site's __INITIAL_STATE__.

    Returns dict mapping nameIdentifier -> eventGroupId
    """
    response = requests.get(GOLF_PAGE_URL, headers=HEADERS, timeout=30)
    response.raise_for_status()

    # Extract __INITIAL_STATE__ JSON from the page
    match = re.search(r'window\.__INITIAL_STATE__\s*=\s*(\{.*?\});', response.text, re.DOTALL)
    if not match:
        return {}

    try:
        state = json.loads(match.group(1))
    except json.JSONDecodeError:
        return {}

    # Find golf sport and extract event groups
    leagues = {}
    sports_data = state.get("sports", {}).get("data", [])

    for sport in sports_data:
        if sport.get("displayGroupId") == str(GOLF_DISPLAY_GROUP_ID):
            for event_group in sport.get("eventGroupInfos", []):
                name_id = event_group.get("nameIdentifier", "")
                group_id = event_group.get("eventGroupId")
                if name_id and group_id:
                    leagues[name_id] = str(group_id)
            break

    return leagues


def resolve_league_id(event_slug: str) -> str:
    """
    Resolve event slug to DraftKings league ID.

    Strips year suffix (e.g., "wyndham-championship-2026" -> "wyndham-championship")
    and looks up the league ID from DraftKings.
    """
    # Strip year suffix if present
    base_slug = re.sub(r'-\d{4}$', '', event_slug)

    print(f"Looking up DraftKings league ID for '{base_slug}'...")
    leagues = fetch_golf_leagues()

    if not leagues:
        print("Warning: Could not fetch golf leagues from DraftKings")
        return None

    if base_slug in leagues:
        league_id = leagues[base_slug]
        print(f"  Found: {base_slug} -> {league_id}")
        return league_id

    # Try partial match
    for name_id, league_id in leagues.items():
        if base_slug in name_id or name_id in base_slug:
            print(f"  Partial match: {base_slug} -> {name_id} -> {league_id}")
            return league_id

    print(f"  Not found. Available leagues:")
    for name_id, league_id in sorted(leagues.items()):
        print(f"    {name_id}: {league_id}")
    return None


def build_api_url(league_id: str) -> str:
    """Build the DraftKings API URL for a given league ID."""
    return (
        f"{API_BASE}/controldata/league/leagueSubcategory/v1/markets"
        f"?isBatchable=false"
        f"&templateVars={league_id}%2C{SUBCATEGORY_ID}"
        f"&eventsQuery=%24filter%3DleagueId%20eq%20%27{league_id}%27%20AND%20"
        f"clientMetadata%2FSubcategories%2Fany%28s%3A%20s%2FId%20eq%20%27{SUBCATEGORY_ID}%27%29"
        f"&marketsQuery=%24filter%3DclientMetadata%2FsubCategoryId%20eq%20%27{SUBCATEGORY_ID}%27%20AND%20"
        f"tags%2Fall%28t%3A%20t%20ne%20%27SportcastBetBuilder%27%29"
        f"&include=Events"
        f"&entity=events"
    )


def fetch_data(league_id: str) -> dict:
    """Fetch data from DraftKings API for a given league ID."""
    url = build_api_url(league_id)
    response = requests.get(url, headers=HEADERS, timeout=30)
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


def parse_and_save(data: dict, event_slug: str = None) -> None:
    """Parse selections and save to JSON file."""
    # Extract event info
    events = data.get("events", [])
    if not events:
        print()
        print("!" * 70)
        print("ERROR: No events found in DraftKings response!")
        print()
        print("The resolved league ID returned no data.")
        print("This could mean:")
        print("  - The tournament is not yet available for betting")
        print("  - The league ID mapping has changed")
        print()
        print("Try --list-leagues to see available tournaments.")
        print("!" * 70)
        sys.exit(1)

    event = events[0]
    event_id = event.get("id", "")
    event_name = event.get("name", "Unknown Event")

    # Use provided slug or derive from event name
    if event_slug is None:
        event_slug = slugify(event_name)

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
    filename = f"{event_slug}.json"
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
    parser.add_argument(
        "--event-slug",
        type=str,
        default=None,
        help="Event slug to look up (e.g., wyndham-championship-2026)"
    )
    parser.add_argument(
        "--list-leagues",
        action="store_true",
        help="List available golf leagues and exit"
    )
    args = parser.parse_args()

    print("Fetching DraftKings golf odds...")
    print()

    # List leagues mode
    if args.list_leagues:
        leagues = fetch_golf_leagues()
        if leagues:
            print("Available golf leagues:")
            for name_id, league_id in sorted(leagues.items()):
                print(f"  {name_id}: {league_id}")
        else:
            print("Could not fetch golf leagues")
        return

    # Resolve league ID from event slug
    if args.event_slug:
        league_id = resolve_league_id(args.event_slug)
        if not league_id:
            print("Error: Could not resolve league ID")
            sys.exit(1)
    else:
        # Try to find any active golf tournament
        print("No --event-slug provided, looking for active tournaments...")
        leagues = fetch_golf_leagues()
        if not leagues:
            print("Error: Could not fetch golf leagues")
            sys.exit(1)
        # Use first available league
        name_id, league_id = next(iter(leagues.items()))
        print(f"  Using: {name_id} ({league_id})")

    try:
        data = fetch_data(league_id)
    except requests.RequestException as e:
        print(f"Error fetching data: {e}")
        sys.exit(1)

    if args.raw:
        dump_raw(data)
    else:
        parse_and_save(data, event_slug=args.event_slug)


if __name__ == "__main__":
    main()
