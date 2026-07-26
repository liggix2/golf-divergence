/**
 * Golf Odds Divergence Tracker
 * Main JavaScript file
 */

import {
    impliedToAmerican,
    formatProbability,
    formatAmericanOdds,
    effectivePrice
} from './odds-utils.js';

// ============================================================================
// CONFIGURATION
// ============================================================================
const CONFIG = {
    // Edge threshold configuration (in percentage points)
    // Determines conditional formatting intensity for Edge column
    edgeThresholds: {
        none: 1,      // Below 1pt = no highlight
        light: 3,     // 1 to 3pt = light highlight
        medium: 6,    // 3 to 6pt = medium highlight
        // Above 6pt = strong highlight
    },

    // Data source path - merged data from Kalshi + DraftKings
    dataPath: 'data/merged/rocket-classic-2026.json',

    // Use fee-adjusted effective price for Kalshi edge calculations
    // When true, adds the 7% taker fee to the raw ask price before calculating edge
    // This mirrors the "payout multiple" shown in the Kalshi app
    useEffectivePrice: true,
};

// ============================================================================
// UTILITY FUNCTIONS
// ============================================================================

/**
 * Convert implied probability (decimal) to American odds
 * @param {number} impliedProb - Implied probability as decimal (e.g., 0.31)
 * @returns {number} American odds (e.g., +223 for 31% implied)
 */
function probToAmericanOdds(impliedProb) {
    if (impliedProb <= 0 || impliedProb >= 1) {
        return 0;
    }
    return impliedToAmerican(impliedProb);
}

/**
 * Get the Kalshi price to use for edge calculations.
 * When CONFIG.useEffectivePrice is true, returns the fee-adjusted price.
 * When false, returns the raw ask price.
 *
 * Display always shows raw ask; this only affects edge math.
 *
 * @param {number} rawPrice - Raw implied probability
 * @returns {number} Price to use for edge calculation (raw or fee-adjusted)
 */
function getKalshiEdgePrice(rawPrice) {
    if (rawPrice <= 0 || rawPrice >= 1) {
        return rawPrice;
    }
    return CONFIG.useEffectivePrice ? effectivePrice(rawPrice) : rawPrice;
}

/**
 * Format timestamp for display (short format)
 * @param {string} isoTimestamp - ISO timestamp string
 * @returns {string} Formatted timestamp
 */
function formatTimestamp(isoTimestamp) {
    if (!isoTimestamp) return 'Unknown';
    const date = new Date(isoTimestamp);
    return date.toLocaleString('en-US', {
        month: 'short',
        day: 'numeric',
        hour: 'numeric',
        minute: '2-digit',
    });
}

/**
 * Get the CSS class for edge highlighting based on thresholds
 * @param {number|null} edgePoints - Edge in percentage points (e.g., 2.5)
 * @returns {string} CSS class name
 */
function getEdgeClass(edgePoints) {
    if (edgePoints === null) {
        return 'edge-none';
    }
    const absEdge = Math.abs(edgePoints);
    const { none, light, medium } = CONFIG.edgeThresholds;

    if (absEdge < none) {
        return 'edge-none';
    } else if (absEdge < light) {
        return 'edge-light';
    } else if (absEdge < medium) {
        return 'edge-medium';
    } else {
        return 'edge-strong';
    }
}

// ============================================================================
// DATA INFO RENDERING
// ============================================================================

/**
 * Render the data info header showing event name and source timestamps
 * @param {object} data - Merged data object
 */
function renderDataInfo(data) {
    const dataInfo = document.getElementById('data-info');
    if (!dataInfo) return;

    const eventName = data.event_name || 'Unknown Event';
    const sources = data.sources || {};
    const playerCount = data.players ? data.players.length : 0;

    const dkFetched = sources.draftkings?.fetched_at
        ? formatTimestamp(sources.draftkings.fetched_at)
        : 'N/A';
    const kalshiFetched = sources.kalshi?.fetched_at
        ? formatTimestamp(sources.kalshi.fetched_at)
        : 'N/A';

    dataInfo.innerHTML = `
        <span class="event-ticker">${eventName}</span>
        <span class="fetched-at">DK: ${dkFetched} · Kalshi: ${kalshiFetched} · ${playerCount} players</span>
    `;
}

// ============================================================================
// TABLE RENDERING
// ============================================================================

/**
 * Render empty placeholder cell
 * @returns {string} HTML for empty cell
 */
function renderEmptyCell() {
    return '<td class="odds-cell empty">—</td>';
}

/**
 * Render DraftKings odds cell with American odds and raw implied probability
 * Uses raw implied probability, never devigged
 * @param {object} player - Player data object from merged data
 * @returns {string} HTML for the cell
 */
function renderDraftKingsCell(player) {
    const americanOdds = player.dk_american_odds;
    const impliedProb = player.dk_implied_prob;

    if (americanOdds === null || americanOdds === undefined) {
        return renderEmptyCell();
    }

    const oddsStr = americanOdds >= 0 ? `+${americanOdds}` : `${americanOdds}`;

    return `
        <td class="odds-cell">
            <span class="odds-american">${oddsStr}</span>
            <span class="odds-implied">${formatProbability(impliedProb, 2)}</span>
        </td>
    `;
}

/**
 * Render Kalshi odds cell with American odds and implied probability
 * @param {object} player - Player data object from merged data
 * @returns {string} HTML for the cell
 */
function renderKalshiCell(player) {
    const impliedProb = player.kalshi_implied_prob;

    if (impliedProb === null || impliedProb === undefined) {
        return renderEmptyCell();
    }

    const americanOdds = probToAmericanOdds(impliedProb);
    const oddsStr = formatAmericanOdds(americanOdds);

    return `
        <td class="odds-cell">
            <span class="odds-american">${oddsStr}</span>
            <span class="odds-implied">${formatProbability(impliedProb, 2)}</span>
        </td>
    `;
}

/**
 * Render edge cell
 * @param {number|null} edge - Edge value in percentage points, or null if not calculable
 * @returns {string} HTML for edge cell
 */
function renderEdgeCell(edge) {
    if (edge === null) {
        return '<td class="edge-cell edge-none">—</td>';
    }
    const edgeClass = getEdgeClass(edge);
    const sign = edge >= 0 ? '+' : '';
    return `<td class="edge-cell ${edgeClass}">${sign}${edge.toFixed(1)}%</td>`;
}

/**
 * Render the odds table with merged data
 * @param {object} data - Merged data object
 */
function renderTable(data) {
    const tbody = document.querySelector('#odds-table tbody');
    if (!tbody || !data.players || data.players.length === 0) {
        tbody.innerHTML = '<tr class="placeholder"><td colspan="6">No market data available</td></tr>';
        return;
    }

    // Filter to players with at least DK or Kalshi data
    const activePlayers = data.players.filter(p =>
        p.dk_implied_prob !== null || p.kalshi_implied_prob !== null
    );

    if (activePlayers.length === 0) {
        tbody.innerHTML = '<tr class="placeholder"><td colspan="6">No active markets found</td></tr>';
        return;
    }

    // Sort by DK implied probability descending (favorites first)
    activePlayers.sort((a, b) => {
        const probA = a.dk_implied_prob || 0;
        const probB = b.dk_implied_prob || 0;
        return probB - probA;
    });

    // Build table rows
    const rows = activePlayers.map(player => {
        const playerName = player.player_name || 'Unknown';

        // Edge calculation: my fair probability - best market effective price
        // Edge is null when My Fair Odds is missing
        const myFairProb = null; // TODO: Load from My Fair Odds data
        const edge = null; // No edge until fair odds exist

        return `
            <tr>
                <td>${playerName}</td>
                ${renderEmptyCell()}
                ${renderDraftKingsCell(player)}
                ${renderKalshiCell(player)}
                ${renderEmptyCell()}
                ${renderEdgeCell(edge)}
            </tr>
        `;
    });

    tbody.innerHTML = rows.join('');
}

// ============================================================================
// INITIALIZATION
// ============================================================================

document.addEventListener('DOMContentLoaded', function() {
    const tournamentSelect = document.getElementById('tournament-select');

    // Load merged data on page load
    fetch(CONFIG.dataPath)
        .then(response => {
            if (!response.ok) {
                throw new Error(`HTTP error! status: ${response.status}`);
            }
            return response.json();
        })
        .then(data => {
            renderDataInfo(data);
            renderTable(data);
            console.log(`Loaded ${data.players?.length || 0} players for ${data.event_name}`);
        })
        .catch(error => {
            console.error('Error loading data:', error);
            const tbody = document.querySelector('#odds-table tbody');
            if (tbody) {
                tbody.innerHTML = `<tr class="placeholder"><td colspan="6">Error loading data: ${error.message}</td></tr>`;
            }
        });

    // Tournament selection handler (placeholder for future)
    tournamentSelect.addEventListener('change', function() {
        const selectedTournament = this.value;
        if (selectedTournament) {
            console.log('Selected tournament:', selectedTournament);
            // TODO: Load data for selected tournament
        }
    });

    console.log('Golf Odds Divergence Tracker initialized');
});
