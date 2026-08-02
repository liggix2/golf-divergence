#!/usr/bin/env bash
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
PYTHON="$PROJECT_DIR/venv/bin/python"

# Defaults (update when tournament changes)
EVENT_SLUG="rocket-classic-2026"
KALSHI_TICKER="KXPGATOUR-ROC26"
PUSH=false

# Parse arguments
while [[ $# -gt 0 ]]; do
    case $1 in
        --event-slug)
            EVENT_SLUG="$2"
            shift 2
            ;;
        --kalshi-ticker)
            KALSHI_TICKER="$2"
            shift 2
            ;;
        --push)
            PUSH=true
            shift
            ;;
        -*)
            echo "Unknown option: $1" >&2
            echo "Usage: refresh.sh [--event-slug SLUG] [--kalshi-ticker TICKER] [--push]" >&2
            exit 1
            ;;
        *)
            echo "Unknown argument: $1" >&2
            echo "Usage: refresh.sh [--event-slug SLUG] [--kalshi-ticker TICKER] [--push]" >&2
            exit 1
            ;;
    esac
done

echo "Refreshing data"
echo "  Event slug: $EVENT_SLUG"
echo "  Kalshi ticker: $KALSHI_TICKER"
echo "========================================"

# Fetch Kalshi (suppress table, capture summary)
echo "Fetching Kalshi..."
KALSHI_OUT=$("$PYTHON" "$SCRIPT_DIR/kalshi_fetch.py" "$KALSHI_TICKER" 2>&1)
KALSHI_COUNT=$(echo "$KALSHI_OUT" | grep -o "Total markets fetched: [0-9]*" | grep -o "[0-9]*")
echo "  Kalshi: $KALSHI_COUNT markets"

# Fetch DraftKings (suppress table, capture summary)
echo "Fetching DraftKings..."
DK_FILE="$PROJECT_DIR/data/draftkings/$EVENT_SLUG.json"
if DK_OUT=$("$PYTHON" "$SCRIPT_DIR/dk_fetch.py" --event-slug "$EVENT_SLUG" 2>&1); then
    DK_COUNT=$(echo "$DK_OUT" | grep -o "Players: [0-9]*" | grep -o "[0-9]*")
    DK_HOLD=$(echo "$DK_OUT" | grep -o "Total implied probability: [0-9.]*%" | grep -o "[0-9.]*%")
    echo "  DraftKings: $DK_COUNT players, hold $DK_HOLD"
elif [ -f "$DK_FILE" ]; then
    echo "  DraftKings: using cached data (no active tournament)"
else
    echo "  DraftKings: no data available (no active tournament)"
fi

# Fetch Data Golf (suppress verbose output, capture summary)
echo "Fetching Data Golf..."
DG_OUT=$("$PYTHON" "$SCRIPT_DIR/dg_fetch.py" --event-slug "$EVENT_SLUG" 2>&1)
DG_FIELD=$(echo "$DG_OUT" | grep -m1 "^Players: [0-9]*" | grep -o "[0-9]*")
DG_EVENT=$(echo "$DG_OUT" | grep "^Field:" | sed 's/Field: //' | sed 's/ ([0-9]* players)//')
DG_SKILLS=$(echo "$DG_OUT" | grep "Skill ratings coverage" | grep -o "[0-9]*/[0-9]*")
DG_PREDS=$(echo "$DG_OUT" | grep "^Predictions:" | sed 's/Predictions: //')
echo "  Data Golf: $DG_EVENT ($DG_FIELD field, $DG_SKILLS with skills)"
echo "  Predictions: $DG_PREDS"

# Run model (suppress verbose output, capture summary)
echo "Running model..."
MODEL_OUT=$("$PYTHON" "$SCRIPT_DIR/model.py" --event-slug "$EVENT_SLUG" 2>&1)
MODEL_PROB=$(echo "$MODEL_OUT" | grep "Total win probability sum:" | grep -o "[0-9.]*%")
echo "  Model: win prob sum $MODEL_PROB"

# Merge (suppress verbose output, capture match stats)
echo "Merging..."
MERGE_OUT=$("$PYTHON" "$SCRIPT_DIR/merge_odds.py" --event-slug "$EVENT_SLUG" --kalshi-ticker "$KALSHI_TICKER" 2>&1)
DK_KA_MATCHED=$(echo "$MERGE_OUT" | grep "DK-Kalshi matched:" | head -1 | grep -o "[0-9]*")
TOTAL=$(echo "$MERGE_OUT" | grep "Total merged records:" | grep -o "[0-9]*")
echo "  Merged: $DK_KA_MATCHED DK-Kalshi matched of $TOTAL total"

# Copy to current.json for site
MERGED_FILE="$PROJECT_DIR/data/merged/$EVENT_SLUG.json"
CURRENT_FILE="$PROJECT_DIR/data/merged/current.json"
cp "$MERGED_FILE" "$CURRENT_FILE"
echo "  Updated current.json"

echo "========================================"
echo "Done."

# Push if requested
if [ "$PUSH" = true ]; then
    echo ""
    echo "Committing and pushing..."
    cd "$PROJECT_DIR"

    TIMESTAMP=$(date -u +"%Y-%m-%d %H:%M UTC")
    git add data/
    git commit -m "Refresh odds data: $TIMESTAMP"
    git push origin

    echo "Pushed to origin."
fi
