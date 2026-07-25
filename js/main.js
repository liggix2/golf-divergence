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

    // Bettable market sources to compare against for edge calculation
    // Does NOT include reference sources like DataGolf
    marketSources: ['DraftKings', 'Kalshi'],

    // Fair odds source (used for edge calculation)
    fairOddsSource: 'MyFairOdds',

    // Whether to devig market probabilities
    // When false: display raw implied probability from American odds
    // When true: devig each market's full field separately so probabilities sum to 100%
    // NOTE: Devigging requires complete field data for accurate results
    devigMarkets: false,
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
 * Edge = my implied probability - lowest implied probability among bettable markets
 * Positive edge means we think the player has higher win probability than market implies
 * @param {number} myImpliedProb - My fair implied probability (raw, not devigged)
 * @param {object} playerOdds - Player's odds from all sources
 * @param {object} deviggedMarketProbs - Optional map of source -> devigged probability for this player
 * @returns {number} Edge in percentage points
 */
function calculateEdge(myImpliedProb, playerOdds, deviggedMarketProbs = null) {
    // Find the lowest implied probability among bettable market sources
    // Lower implied prob = higher odds = better value
    let lowestMarketProb = Infinity;

    for (const source of CONFIG.marketSources) {
        if (playerOdds[source] !== undefined) {
            let prob;
            if (CONFIG.devigMarkets && deviggedMarketProbs && deviggedMarketProbs[source] !== undefined) {
                prob = deviggedMarketProbs[source];
            } else {
                prob = americanToImplied(playerOdds[source]);
            }
            if (prob < lowestMarketProb) {
                lowestMarketProb = prob;
            }
        }
    }

    if (lowestMarketProb === Infinity) {
        return 0;
    }

    // Edge = my probability - lowest market probability
    // If my prob is 20% and market is 15%, edge is +5 points (I think player is undervalued)
    // If my prob is 15% and market is 20%, edge is -5 points (I think player is overvalued)
    return (myImpliedProb - lowestMarketProb) * 100;
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
 * Devig a specific market's probabilities across the full field
 * @param {object[]} odds - Array of player odds objects
 * @param {string} source - The market source to devig (e.g., 'DraftKings')
 * @returns {number[]} Array of devigged probabilities, one per player
 */
function devigMarket(odds, source) {
    const rawProbs = odds.map(p => americanToImplied(p[source]));
    return devig(rawProbs);
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

    // Calculate raw implied probabilities for My Fair Odds (no devigging)
    const myFairProbs = data.odds.map(p => americanToImplied(p[CONFIG.fairOddsSource]));

    // Optionally devig market probabilities
    // NOTE: Devigging requires complete field data for accurate results
    let deviggedMarkets = {};
    if (CONFIG.devigMarkets) {
        for (const source of CONFIG.marketSources) {
            deviggedMarkets[source] = devigMarket(data.odds, source);
        }
        // Also devig DataGolf for display if present
        if (data.odds[0].DataGolf !== undefined) {
            deviggedMarkets['DataGolf'] = devigMarket(data.odds, 'DataGolf');
        }
    }

    // Build table rows
    const rows = data.odds.map((player, index) => {
        const myFairProb = myFairProbs[index];

        // Build devigged probs map for this player (if devigging enabled)
        let playerDeviggedProbs = null;
        if (CONFIG.devigMarkets) {
            playerDeviggedProbs = {};
            for (const source of Object.keys(deviggedMarkets)) {
                playerDeviggedProbs[source] = deviggedMarkets[source][index];
            }
        }

        const edge = calculateEdge(myFairProb, player, playerDeviggedProbs);
        const edgeClass = getEdgeClass(edge);

        // Get display probabilities for each market
        const dkProb = CONFIG.devigMarkets && playerDeviggedProbs
            ? playerDeviggedProbs['DraftKings']
            : null;
        const kalshiProb = CONFIG.devigMarkets && playerDeviggedProbs
            ? playerDeviggedProbs['Kalshi']
            : null;
        const dgProb = CONFIG.devigMarkets && playerDeviggedProbs
            ? playerDeviggedProbs['DataGolf']
            : null;

        return `
            <tr>
                <td>${player.player}</td>
                <td class="odds-cell">${formatOddsCell(player.MyFairOdds, myFairProb)}</td>
                <td class="odds-cell">${formatOddsCell(player.DraftKings, dkProb)}</td>
                <td class="odds-cell">${formatOddsCell(player.Kalshi, kalshiProb)}</td>
                <td class="odds-cell">${formatOddsCell(player.DataGolf, dgProb)}</td>
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
    console.log('Devig markets:', CONFIG.devigMarkets);
});
