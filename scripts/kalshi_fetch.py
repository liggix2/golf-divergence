#!/usr/bin/env python3
"""
Kalshi Golf Tournament Market Fetcher

Fetches all markets for a golf tournament event from Kalshi and saves to JSON.
Handles pagination to capture the full field.

Usage:
    python kalshi_fetch.py [EVENT_TICKER]

Example:
    python kalshi_fetch.py KXPGATOUR-3MO26
"""

import argparse
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

try:
    import requests
except ImportError:
    print("Error: requests library required. Install with: pip install requests")
    sys.exit(1)


BASE_URL = "https://external-api.kalshi.com/trade-api/v2"
DEFAULT_EVENT_TICKER = "KXPGATOUR-3MO26"

# Output directory relative to script location
SCRIPT_DIR = Path(__file__).parent.parent
DATA_DIR = SCRIPT_DIR / "data" / "kalshi"


def fetch_markets_for_event(event_ticker: str) -> list:
    """
    Fetch all markets for a given event ticker, handling pagination.

    Args:
        event_ticker: The event ticker to query (e.g., KXPGATOUR-3MO26)

    Returns:
        List of market objects
    """
    all_markets = []
    cursor = None
    page = 1

    while True:
        params = {
            "event_ticker": event_ticker,
            "limit": 200,  # Max per page
        }
        if cursor:
            params["cursor"] = cursor

        print(f"Fetching page {page}...", end=" ", flush=True)

        try:
            response = requests.get(
                f"{BASE_URL}/markets",
                params=params,
                timeout=30
            )
            response.raise_for_status()
            data = response.json()
        except requests.RequestException as e:
            print(f"\nError fetching markets: {e}")
            return all_markets

        markets = data.get("markets", [])
        print(f"got {len(markets)} markets")

        if not markets:
            break

        all_markets.extend(markets)

        # Check for next page
        cursor = data.get("cursor")
        if not cursor:
            break

        page += 1

    return all_markets


def extract_player_ticker(market_ticker: str, event_ticker: str) -> str:
    """
    Extract the player ticker suffix from a market ticker.

    Example: KXPGATOUR-3MO26-SSCH -> SSCH
    """
    prefix = f"{event_ticker}-"
    if market_ticker.startswith(prefix):
        return market_ticker[len(prefix):]
    return market_ticker


def extract_player_name(title: str) -> str:
    """
    Parse the player's full name from the market title.

    Examples:
        "Will Keith Mitchell win the 3M Open?" -> "Keith Mitchell"
        "Will Scottie Scheffler win the Masters?" -> "Scottie Scheffler"
    """
    # Pattern: "Will {Name} win the {Tournament}?"
    match = re.match(r"Will (.+?) win the .+\?", title)
    if match:
        return match.group(1).strip()

    # Fallback: return empty string if pattern doesn't match
    return ""


def calculate_spread(bid_dollars: str, ask_dollars: str) -> Optional[float]:
    """
    Calculate spread (ask - bid) from dollar strings.

    Returns None if either value is missing or invalid.
    """
    try:
        if not bid_dollars or not ask_dollars:
            return None
        bid = float(bid_dollars)
        ask = float(ask_dollars)
        return round(ask - bid, 4)
    except (ValueError, TypeError):
        return None


def parse_market(market: dict, event_ticker: str) -> dict:
    """
    Extract relevant fields from a market object.
    """
    ticker = market.get("ticker", "")
    title = market.get("title", "")
    yes_bid_dollars = market.get("yes_bid_dollars")
    yes_ask_dollars = market.get("yes_ask_dollars")

    return {
        "ticker": ticker,
        "player_code": extract_player_ticker(ticker, event_ticker),
        "player_name": extract_player_name(title),
        "title": title,
        "subtitle": market.get("subtitle") or market.get("yes_sub_title", ""),
        "status": market.get("status", ""),
        "yes_bid": market.get("yes_bid"),
        "yes_ask": market.get("yes_ask"),
        "yes_bid_dollars": yes_bid_dollars,
        "yes_ask_dollars": yes_ask_dollars,
        "spread": calculate_spread(yes_bid_dollars, yes_ask_dollars),
        "last_price": market.get("last_price"),
        "last_price_dollars": market.get("last_price_dollars"),
        "volume": market.get("volume"),
        "volume_fp": market.get("volume_fp"),
        "open_interest": market.get("open_interest"),
        "open_interest_fp": market.get("open_interest_fp"),
        "close_time": market.get("close_time"),
    }


def save_to_json(event_ticker: str, markets: list) -> Path:
    """
    Save market data to JSON file.
    """
    DATA_DIR.mkdir(parents=True, exist_ok=True)

    output = {
        "event_ticker": event_ticker,
        "fetched_at": datetime.now(timezone.utc).isoformat(),
        "market_count": len(markets),
        "markets": markets,
    }

    # Sanitize filename
    safe_ticker = event_ticker.replace("/", "_").replace("\\", "_")
    filepath = DATA_DIR / f"{safe_ticker}.json"

    with open(filepath, "w") as f:
        json.dump(output, f, indent=2)

    return filepath


def print_summary_table(markets: list, limit: int = 20) -> None:
    """
    Print a summary table sorted by yes_ask descending (favorites first).

    Args:
        markets: List of parsed market dicts
        limit: Maximum number of rows to display (default 20)
    """
    # Filter to active markets (exclude $1.00 asks = eliminated, and $0.00 asks = no market)
    valid_markets = [
        m for m in markets
        if m.get("yes_ask_dollars")
        and float(m["yes_ask_dollars"]) > 0
        and float(m["yes_ask_dollars"]) < 1.0
    ]

    # Sort by yes_ask_dollars descending (highest ask = highest implied prob = favorites)
    sorted_markets = sorted(
        valid_markets,
        key=lambda m: float(m.get("yes_ask_dollars") or "0"),
        reverse=True
    )

    # Print header
    print("\n" + "=" * 78)
    print(f"{'Player':<28} {'Bid':>10} {'Ask':>10} {'Spread':>10} {'Volume':>14}")
    print("=" * 78)

    for m in sorted_markets[:limit]:
        player_name = m.get("player_name", "") or m.get("player_code", "")
        display_name = player_name[:26]

        bid = m.get("yes_bid_dollars", "—")
        ask = m.get("yes_ask_dollars", "—")
        spread = m.get("spread")
        volume = m.get("volume_fp", "0")

        # Format values
        if bid and bid != "—":
            bid = f"${float(bid):.2f}"
        if ask and ask != "—":
            ask = f"${float(ask):.2f}"
        spread_str = f"${spread:.3f}" if spread is not None else "—"

        # Format volume with K/M suffix
        try:
            vol = float(volume)
            if vol >= 1_000_000:
                volume_str = f"{vol/1_000_000:.1f}M"
            elif vol >= 1_000:
                volume_str = f"{vol/1_000:.0f}K"
            else:
                volume_str = f"{vol:.0f}"
        except (ValueError, TypeError):
            volume_str = "—"

        print(f"{display_name:<28} {bid:>10} {ask:>10} {spread_str:>10} {volume_str:>14}")

    print("=" * 78)
    shown = min(limit, len(sorted_markets))
    print(f"Showing top {shown} of {len(sorted_markets)} markets with active asks")


def main():
    parser = argparse.ArgumentParser(
        description="Fetch golf tournament markets from Kalshi"
    )
    parser.add_argument(
        "event_ticker",
        nargs="?",
        default=DEFAULT_EVENT_TICKER,
        help=f"Event ticker to fetch (default: {DEFAULT_EVENT_TICKER})"
    )
    args = parser.parse_args()

    event_ticker = args.event_ticker
    print(f"Fetching markets for event: {event_ticker}")
    print(f"API: {BASE_URL}/markets?event_ticker={event_ticker}")
    print()

    # Fetch all markets
    raw_markets = fetch_markets_for_event(event_ticker)

    if not raw_markets:
        print(f"\nNo markets found for event ticker: {event_ticker}")
        print("\nPossible reasons:")
        print("  - The event ticker may be incorrect")
        print("  - The event may not exist or has expired")
        print("  - Try using the series ticker instead (e.g., KXPGATOUR)")
        print("\nTo discover available events, run: python kalshi_discover.py")
        sys.exit(0)

    print(f"\nTotal markets fetched: {len(raw_markets)}")

    # Parse markets
    parsed_markets = [parse_market(m, event_ticker) for m in raw_markets]

    # Save to JSON
    filepath = save_to_json(event_ticker, parsed_markets)
    print(f"Saved to: {filepath}")

    # Print summary
    print_summary_table(parsed_markets)


if __name__ == "__main__":
    main()
