/**
 * Golf Odds Divergence Tracker
 * Main JavaScript file
 */

import {
    impliedToAmerican,
    formatProbability,
    formatAmericanOdds
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

    // Data source path
    kalshiDataPath: 'data/kalshi/KXPGATOUR-3MO26.json',
};

// ============================================================================
// UTILITY FUNCTIONS
// ============================================================================

/**
 * Convert a dollar price to implied probability as decimal
 * @param {string|number} dollars - Price in dollars (e.g., "0.31" = 31%)
 * @returns {number} Implied probability as decimal (e.g., 0.31)
 */
function dollarToImpliedProb(dollars) {
    return parseFloat(dollars) || 0;
}

/**
 * Convert a dollar price to American odds
 * Note: yes_ask_dollars is the price field; yes_ask (integer) is null in Kalshi data
 * @param {string|number} dollars - Price in dollars (e.g., "0.31" = 31% implied)
 * @returns {number} American odds (e.g., +223 for 31% implied)
 */
function dollarToAmericanOdds(dollars) {
    const impliedProb = dollarToImpliedProb(dollars);
    if (impliedProb <= 0 || impliedProb >= 1) {
        return 0;
    }
    return impliedToAmerican(impliedProb);
}

/**
 * Format volume with K/M suffix
 * @param {string|number} volume - Volume value
 * @returns {string} Formatted volume (e.g., "1.3M", "450K")
 */
function formatVolume(volume) {
    const vol = parseFloat(volume) || 0;
    if (vol >= 1_000_000) {
        return (vol / 1_000_000).toFixed(1) + 'M';
    } else if (vol >= 1_000) {
        return Math.round(vol / 1_000) + 'K';
    }
    return vol.toFixed(0);
}

/**
 * Format spread value
 * @param {number|null} spread - Spread value
 * @returns {string} Formatted spread (e.g., "$0.010")
 */
function formatSpread(spread) {
    if (spread === null || spread === undefined) {
        return '—';
    }
    return '$' + spread.toFixed(3);
}

/**
 * Format timestamp for display
 * @param {string} isoTimestamp - ISO timestamp string
 * @returns {string} Formatted timestamp
 */
function formatTimestamp(isoTimestamp) {
    const date = new Date(isoTimestamp);
    return date.toLocaleString('en-US', {
        month: 'short',
        day: 'numeric',
        year: 'numeric',
        hour: 'numeric',
        minute: '2-digit',
        timeZoneName: 'short'
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
 * Render the data info header showing event ticker and fetch timestamp
 * @param {object} data - Kalshi data object
 */
function renderDataInfo(data) {
    const dataInfo = document.getElementById('data-info');
    if (!dataInfo) return;

    const eventTicker = data.event_ticker || 'Unknown';
    const fetchedAt = data.fetched_at ? formatTimestamp(data.fetched_at) : 'Unknown';
    const marketCount = data.market_count || 0;

    dataInfo.innerHTML = `
        <span class="event-ticker">${eventTicker}</span>
        <span class="fetched-at">Fetched: ${fetchedAt} · ${marketCount} markets</span>
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
 * Render Kalshi odds cell with American odds, implied probability, and volume
 * Note: All price reads use yes_ask_dollars since yes_ask (integer) is null in Kalshi data
 * @param {object} market - Market data object
 * @returns {string} HTML for the cell
 */
function renderKalshiCell(market) {
    const americanOdds = dollarToAmericanOdds(market.yes_ask_dollars);
    const impliedProb = dollarToImpliedProb(market.yes_ask_dollars);
    const volume = formatVolume(market.volume_fp);

    return `
        <td class="odds-cell">
            <span class="odds-american">${formatAmericanOdds(americanOdds)}</span>
            <span class="odds-implied">${formatProbability(impliedProb, 2)}</span>
            <span class="odds-volume">Vol: ${volume}</span>
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
 * Render the odds table with Kalshi data
 * @param {object} data - Kalshi data object
 */
function renderTable(data) {
    const tbody = document.querySelector('#odds-table tbody');
    if (!tbody || !data.markets || data.markets.length === 0) {
        tbody.innerHTML = '<tr class="placeholder"><td colspan="6">No market data available</td></tr>';
        return;
    }

    // Filter out inactive markets (ask of 0 or 1.00)
    const activeMarkets = data.markets.filter(m => {
        const ask = parseFloat(m.yes_ask_dollars) || 0;
        return ask > 0 && ask < 1.0;
    });

    if (activeMarkets.length === 0) {
        tbody.innerHTML = '<tr class="placeholder"><td colspan="6">No active markets found</td></tr>';
        return;
    }

    // Sort by ask descending (favorites first)
    activeMarkets.sort((a, b) => {
        const askA = parseFloat(a.yes_ask_dollars) || 0;
        const askB = parseFloat(b.yes_ask_dollars) || 0;
        return askB - askA;
    });

    // Build table rows
    const rows = activeMarkets.map(market => {
        const playerName = market.player_name || market.player_code || 'Unknown';

        // Edge is null when My Fair Odds is missing
        const edge = null;

        return `
            <tr>
                <td>${playerName}</td>
                ${renderEmptyCell()}
                ${renderEmptyCell()}
                ${renderKalshiCell(market)}
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

    // Load Kalshi data on page load
    fetch(CONFIG.kalshiDataPath)
        .then(response => {
            if (!response.ok) {
                throw new Error(`HTTP error! status: ${response.status}`);
            }
            return response.json();
        })
        .then(data => {
            renderDataInfo(data);
            renderTable(data);
            console.log(`Loaded ${data.market_count} markets from ${data.event_ticker}`);
        })
        .catch(error => {
            console.error('Error loading Kalshi data:', error);
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
