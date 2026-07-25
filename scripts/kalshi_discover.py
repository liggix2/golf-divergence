#!/usr/bin/env python3
"""
Kalshi API Discovery Script

Queries the Kalshi public API to discover golf/PGA-related series, events, and markets.
Prints raw structure to understand ticker naming conventions.

API Base: https://external-api.kalshi.com/trade-api/v2
"""

import json
import sys
from typing import Any

try:
    import requests
except ImportError:
    print("Error: requests library required. Install with: pip install requests")
    sys.exit(1)


BASE_URL = "https://external-api.kalshi.com/trade-api/v2"

# Keywords to filter for golf-related content
GOLF_KEYWORDS = [
    "golf", "pga", "masters", "open championship", "us open golf",
    "british open", "ryder cup", "lpga", "liv golf", "tour championship",
    "players championship", "scheffler", "mcilroy", "rahm", "koepka",
    "dechambeau", "hovland", "spieth", "thomas", "woods"
]


def is_golf_related(text: str) -> bool:
    """Check if text contains any golf-related keywords."""
    if not text:
        return False
    text_lower = text.lower()
    return any(kw in text_lower for kw in GOLF_KEYWORDS)


def print_separator(title: str) -> None:
    """Print a section separator."""
    print("\n" + "=" * 70)
    print(f"  {title}")
    print("=" * 70)


def print_raw_json(obj: Any, indent: int = 2) -> None:
    """Pretty print JSON object."""
    print(json.dumps(obj, indent=indent, default=str))


def fetch_series() -> list:
    """Fetch all series from Kalshi API."""
    url = f"{BASE_URL}/series"
    print(f"\nFetching series from: {url}")

    try:
        response = requests.get(url, timeout=30)
        response.raise_for_status()
        data = response.json()
        return data.get("series", [])
    except requests.RequestException as e:
        print(f"Error fetching series: {e}")
        return []


def fetch_events(series_ticker: str = None, status: str = None, limit: int = 200) -> list:
    """Fetch events, optionally filtered by series ticker."""
    url = f"{BASE_URL}/events"
    params = {"limit": limit}

    if series_ticker:
        params["series_ticker"] = series_ticker
    if status:
        params["status"] = status

    print(f"\nFetching events from: {url}")
    print(f"  Params: {params}")

    try:
        response = requests.get(url, params=params, timeout=30)
        response.raise_for_status()
        data = response.json()
        return data.get("events", [])
    except requests.RequestException as e:
        print(f"Error fetching events: {e}")
        return []


def fetch_markets(event_ticker: str = None, series_ticker: str = None, limit: int = 200) -> list:
    """Fetch markets, optionally filtered by event or series ticker."""
    url = f"{BASE_URL}/markets"
    params = {"limit": limit}

    if event_ticker:
        params["event_ticker"] = event_ticker
    if series_ticker:
        params["series_ticker"] = series_ticker

    print(f"\nFetching markets from: {url}")
    print(f"  Params: {params}")

    try:
        response = requests.get(url, params=params, timeout=30)
        response.raise_for_status()
        data = response.json()
        return data.get("markets", [])
    except requests.RequestException as e:
        print(f"Error fetching markets: {e}")
        return []


def main():
    print("Kalshi API Discovery - Golf/PGA Markets")
    print(f"Base URL: {BASE_URL}")

    # -------------------------------------------------------------------------
    # 1. Fetch and filter series
    # -------------------------------------------------------------------------
    print_separator("SERIES")

    all_series = fetch_series()
    print(f"\nTotal series found: {len(all_series)}")

    golf_series = [s for s in all_series if is_golf_related(s.get("title", "")) or
                   is_golf_related(s.get("ticker", "")) or
                   is_golf_related(s.get("category", ""))]

    print(f"Golf-related series: {len(golf_series)}")

    if golf_series:
        print("\n--- Golf Series (Raw Structure) ---")
        for series in golf_series:
            print_raw_json(series)
            print("-" * 40)
    else:
        print("\nNo golf-related series found. Showing sample series structure:")
        if all_series:
            print_raw_json(all_series[0])

    # Also check for sports category
    sports_series = [s for s in all_series if "sport" in s.get("category", "").lower()]
    if sports_series:
        print(f"\n--- Sports Category Series ({len(sports_series)} total) ---")
        for series in sports_series[:10]:  # Limit to first 10
            print(f"  Ticker: {series.get('ticker', 'N/A')}")
            print(f"  Title: {series.get('title', 'N/A')}")
            print(f"  Category: {series.get('category', 'N/A')}")
            print("-" * 40)

    # -------------------------------------------------------------------------
    # 2. Fetch and filter events
    # -------------------------------------------------------------------------
    print_separator("EVENTS")

    all_events = fetch_events(limit=500)
    print(f"\nTotal events found: {len(all_events)}")

    golf_events = [e for e in all_events if is_golf_related(e.get("title", "")) or
                   is_golf_related(e.get("ticker", "")) or
                   is_golf_related(e.get("sub_title", "")) or
                   is_golf_related(e.get("category", ""))]

    print(f"Golf-related events: {len(golf_events)}")

    if golf_events:
        print("\n--- Golf Events (Raw Structure) ---")
        for event in golf_events:
            print_raw_json(event)
            print("-" * 40)
    else:
        print("\nNo golf-related events found. Showing sample event structure:")
        if all_events:
            print_raw_json(all_events[0])

    # -------------------------------------------------------------------------
    # 3. Fetch markets for golf events (or general sports)
    # -------------------------------------------------------------------------
    print_separator("MARKETS")

    # Try fetching markets directly with search
    all_markets = fetch_markets(limit=500)
    print(f"\nTotal markets found: {len(all_markets)}")

    golf_markets = [m for m in all_markets if is_golf_related(m.get("title", "")) or
                    is_golf_related(m.get("ticker", "")) or
                    is_golf_related(m.get("subtitle", "")) or
                    is_golf_related(m.get("event_ticker", ""))]

    print(f"Golf-related markets: {len(golf_markets)}")

    if golf_markets:
        print("\n--- Golf Markets (Summary) ---")
        for market in golf_markets:
            print(f"  Ticker: {market.get('ticker', 'N/A')}")
            print(f"  Title: {market.get('title', 'N/A')}")
            print(f"  Subtitle: {market.get('subtitle', 'N/A')}")
            print(f"  Status: {market.get('status', 'N/A')}")
            print(f"  Event Ticker: {market.get('event_ticker', 'N/A')}")
            print(f"  Yes Bid: {market.get('yes_bid', 'N/A')}")
            print(f"  Yes Ask: {market.get('yes_ask', 'N/A')}")
            print("-" * 40)

        print("\n--- First Golf Market (Full Raw Structure) ---")
        print_raw_json(golf_markets[0])
    else:
        print("\nNo golf-related markets found.")

        # Show sample market structure
        if all_markets:
            print("\n--- Sample Market Structure ---")
            print_raw_json(all_markets[0])

    # -------------------------------------------------------------------------
    # 4. Summary of ticker naming conventions
    # -------------------------------------------------------------------------
    print_separator("TICKER NAMING CONVENTIONS")

    print("\nSample tickers from each level:")

    if all_series:
        print("\nSeries tickers (first 10):")
        for s in all_series[:10]:
            print(f"  {s.get('ticker', 'N/A'):30} - {s.get('title', 'N/A')[:40]}")

    if all_events:
        print("\nEvent tickers (first 10):")
        for e in all_events[:10]:
            print(f"  {e.get('ticker', 'N/A'):30} - {e.get('title', 'N/A')[:40]}")

    if all_markets:
        print("\nMarket tickers (first 10):")
        for m in all_markets[:10]:
            print(f"  {m.get('ticker', 'N/A'):30} - {m.get('title', 'N/A')[:40]}")

    # -------------------------------------------------------------------------
    # 5. Look for any sports-related content
    # -------------------------------------------------------------------------
    print_separator("SPORTS-RELATED CONTENT")

    sports_keywords = ["sport", "nfl", "nba", "mlb", "nhl", "soccer", "tennis",
                       "golf", "pga", "boxing", "ufc", "mma", "f1", "nascar"]

    def is_sports_related(text: str) -> bool:
        if not text:
            return False
        text_lower = text.lower()
        return any(kw in text_lower for kw in sports_keywords)

    sports_events = [e for e in all_events if is_sports_related(e.get("title", "")) or
                     is_sports_related(e.get("category", ""))]

    print(f"\nSports-related events: {len(sports_events)}")
    for event in sports_events[:20]:
        print(f"  {event.get('ticker', 'N/A'):30} - {event.get('title', 'N/A')[:50]}")
        print(f"    Status: {event.get('status', 'N/A')}, Category: {event.get('category', 'N/A')}")

    sports_markets = [m for m in all_markets if is_sports_related(m.get("title", ""))]

    print(f"\nSports-related markets: {len(sports_markets)}")
    for market in sports_markets[:20]:
        print(f"  {market.get('ticker', 'N/A'):30} - {market.get('title', 'N/A')[:50]}")
        print(f"    Status: {market.get('status', 'N/A')}")


if __name__ == "__main__":
    main()
