# Golf Odds Divergence Tracker

Compare your fair odds against prediction markets and sportsbooks to find edge in golf tournament winner markets.

## Current State

- **Kalshi**: Live data via public API, displays American odds + implied probability
- **DraftKings**: Placeholder (not yet integrated)
- **Data Golf**: Placeholder (not yet integrated)
- **My Fair Odds**: Placeholder (manual entry not yet built)
- **Edge calculation**: Infrastructure ready, waiting on My Fair Odds data

## Data Sources

| Column | Source | Status |
|--------|--------|--------|
| My Fair Odds | Manual entry | Not built |
| DraftKings | TBD | Not built |
| Kalshi | Public API | Working |
| Data Golf | TBD | Not built |

## Setup

```bash
python3 -m venv venv
source venv/bin/activate
pip install requests
```

## Fetching Kalshi Data

```bash
# Fetch current tournament (default: 3M Open)
./venv/bin/python scripts/kalshi_fetch.py

# Fetch specific event
./venv/bin/python scripts/kalshi_fetch.py KXPGATOUR-3MO26

# Discover available golf events
./venv/bin/python scripts/kalshi_discover.py
```

Data saves to `data/kalshi/{event_ticker}.json`.

## Local Development

No build step. Open `index.html` in a browser or use a local server:

```bash
python3 -m http.server 8000
```

## Deployment

Push to `main` and enable GitHub Pages (Settings → Pages → Deploy from branch → main).

## Still To Build

- My Fair Odds input/storage
- DraftKings odds integration
- Data Golf fair value integration
- Edge calculations (formula ready, needs My Fair Odds)
- Tournament selector dropdown
