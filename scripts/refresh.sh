#!/usr/bin/env bash
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
PYTHON="$PROJECT_DIR/venv/bin/python"

# Defaults
EVENT_TICKER="KXPGATOUR-ROC26"
PUSH=false

# Parse arguments
while [[ $# -gt 0 ]]; do
    case $1 in
        --push)
            PUSH=true
            shift
            ;;
        -*)
            echo "Unknown option: $1" >&2
            exit 1
            ;;
        *)
            EVENT_TICKER="$1"
            shift
            ;;
    esac
done

echo "Refreshing data for $EVENT_TICKER"
echo "========================================"

# Fetch Kalshi (suppress table, capture summary)
echo "Fetching Kalshi..."
KALSHI_OUT=$("$PYTHON" "$SCRIPT_DIR/kalshi_fetch.py" "$EVENT_TICKER" 2>&1)
KALSHI_COUNT=$(echo "$KALSHI_OUT" | grep -o "Total markets fetched: [0-9]*" | grep -o "[0-9]*")
echo "  Kalshi: $KALSHI_COUNT markets"

# Fetch DraftKings (suppress table, capture summary)
echo "Fetching DraftKings..."
DK_OUT=$("$PYTHON" "$SCRIPT_DIR/dk_fetch.py" 2>&1)
DK_COUNT=$(echo "$DK_OUT" | grep -o "Players: [0-9]*" | grep -o "[0-9]*")
DK_HOLD=$(echo "$DK_OUT" | grep -o "Total implied probability: [0-9.]*%" | grep -o "[0-9.]*%")
echo "  DraftKings: $DK_COUNT players, hold $DK_HOLD"

# Fetch Data Golf (suppress verbose output, capture summary)
echo "Fetching Data Golf..."
DG_OUT=$("$PYTHON" "$SCRIPT_DIR/dg_fetch.py" 2>&1)
DG_COUNT=$(echo "$DG_OUT" | grep -o "Players: [0-9]*" | grep -o "[0-9]*")
echo "  Data Golf: $DG_COUNT players"

# Merge (suppress verbose output, capture match stats)
echo "Merging..."
MERGE_OUT=$("$PYTHON" "$SCRIPT_DIR/merge_odds.py" 2>&1)
DK_KA_MATCHED=$(echo "$MERGE_OUT" | grep -o "DK-Kalshi matched: [0-9]*" | grep -o "[0-9]*")
TOTAL=$(echo "$MERGE_OUT" | grep -o "Total merged records: [0-9]*" | grep -o "[0-9]*")
echo "  Merged: $DK_KA_MATCHED DK-Kalshi matched of $TOTAL total"

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
