/**
 * Golf Odds Divergence Tracker
 * Main JavaScript file
 */

import {
    americanToImplied,
    devig,
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

    // Market sources to compare against for best available odds
    marketSources: ['DraftKings', 'Kalshi', 'DataGolf'],

    // Fair odds source (used for edge calculation)
    fairOddsSource: 'MyFairOdds',
};

// ============================================================================
// EDGE FORMATTING
// ============================================================================

/**
 * Get the CSS class for edge highlighting based on thresholds
 * @param {number} edgePoints - Edge in percentage points (e.g., 2.5)
 * @returns {string} CSS class name
 */
function getEdgeClass(edgePoints) {
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
// TABLE RENDERING
// ============================================================================

/**
 * Calculate edge for a player
 * Edge = my devigged fair probability - best available market implied probability
 * Positive edge means our fair odds show more value than the market
 * @param {number} fairProb - Devigged fair probability
 * @param {object} playerOdds - Player's odds from all sources
 * @returns {number} Edge in percentage points
 */
function calculateEdge(fairProb, playerOdds) {
    // Find the best (lowest) implied probability among market sources
    // Lower implied prob = higher odds = better value if we think fair prob is higher
    let bestMarketProb = Infinity;

    for (const source of CONFIG.marketSources) {
        if (playerOdds[source] !== undefined) {
            const impliedProb = americanToImplied(playerOdds[source]);
            if (impliedProb < bestMarketProb) {
                bestMarketProb = impliedProb;
            }
        }
    }

    if (bestMarketProb === Infinity) {
        return 0;
    }

    // Edge = fair probability - best market probability
    // If our fair prob is 20% and market is 15%, edge is +5 points (good bet)
    // If our fair prob is 15% and market is 20%, edge is -5 points (bad bet)
    return (fairProb - bestMarketProb) * 100;
}

/**
 * Format a cell with both American odds and implied probability
 * @param {number} americanOdds - American odds value
 * @param {number} impliedProb - Implied probability (optional, will calculate if not provided)
 * @returns {string} HTML for the cell content
 */
function formatOddsCell(americanOdds, impliedProb = null) {
    const prob = impliedProb !== null ? impliedProb : americanToImplied(americanOdds);
    return `
        <span class="odds-american">${formatAmericanOdds(americanOdds)}</span>
        <span class="odds-implied">${formatProbability(prob)}</span>
    `;
}

/**
 * Render the odds table with data
 * @param {object} data - Tournament data object
 */
function renderTable(data) {
    const tbody = document.querySelector('#odds-table tbody');
    if (!tbody || !data.odds || data.odds.length === 0) {
        return;
    }

    // First, calculate devigged fair probabilities
    const fairOddsRaw = data.odds.map(p => p[CONFIG.fairOddsSource]);
    const fairProbsRaw = fairOddsRaw.map(americanToImplied);
    const fairProbsDevigged = devig(fairProbsRaw);

    // Build table rows
    const rows = data.odds.map((player, index) => {
        const fairProbDevigged = fairProbsDevigged[index];
        const edge = calculateEdge(fairProbDevigged, player);
        const edgeClass = getEdgeClass(edge);

        return `
            <tr>
                <td>${player.player}</td>
                <td class="odds-cell">${formatOddsCell(player.MyFairOdds, fairProbDevigged)}</td>
                <td class="odds-cell">${formatOddsCell(player.DraftKings)}</td>
                <td class="odds-cell">${formatOddsCell(player.Kalshi)}</td>
                <td class="odds-cell">${formatOddsCell(player.DataGolf)}</td>
                <td class="edge-cell ${edgeClass}">${edge >= 0 ? '+' : ''}${edge.toFixed(1)}%</td>
            </tr>
        `;
    });

    // Add placeholder row
    rows.push(`
        <tr class="placeholder">
            <td colspan="6">Select a tournament to load odds data...</td>
        </tr>
    `);

    tbody.innerHTML = rows.join('');
}

// ============================================================================
// INITIALIZATION
// ============================================================================

document.addEventListener('DOMContentLoaded', function() {
    const tournamentSelect = document.getElementById('tournament-select');

    // Load sample data on page load for demonstration
    fetch('data/sample-tournament.json')
        .then(response => response.json())
        .then(data => {
            renderTable(data);
        })
        .catch(error => {
            console.error('Error loading sample data:', error);
        });

    // Tournament selection handler
    tournamentSelect.addEventListener('change', function() {
        const selectedTournament = this.value;
        if (selectedTournament) {
            console.log('Selected tournament:', selectedTournament);
            // TODO: Load data from data/{tournament}.json
        }
    });

    console.log('Golf Odds Divergence Tracker initialized');
    console.log('Edge thresholds:', CONFIG.edgeThresholds);
});
