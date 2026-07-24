# Golf Odds Divergence Tracker

A static site for comparing golf tournament odds across multiple sportsbooks to identify divergences and potential value.

## Structure

```
golf-divergence/
├── index.html          # Main page with odds comparison table
├── css/
│   └── styles.css      # Styling
├── js/
│   └── main.js         # JavaScript functionality
├── data/
│   └── *.json          # Weekly tournament odds data
└── README.md
```

## Data Format

Weekly odds data is stored in JSON files in the `data/` directory:

```json
{
  "tournament": "Tournament Name",
  "week": "2024-W01",
  "lastUpdated": "2024-01-15T12:00:00Z",
  "sources": ["DraftKings", "FanDuel", "BetMGM", "Caesars"],
  "odds": [
    {
      "player": "Player Name",
      "DraftKings": 650,
      "FanDuel": 700,
      "BetMGM": 625,
      "Caesars": 675
    }
  ]
}
```

Odds are stored as positive integers (e.g., `650` represents `+650`).

## Deployment

This site is designed for GitHub Pages. Push to the `main` branch and enable GitHub Pages in repository settings.

## Development

No build step required. Open `index.html` in a browser to preview locally.
