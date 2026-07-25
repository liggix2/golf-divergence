/**
 * Odds Utility Functions
 * Converts between American odds and implied probability
 */

/**
 * Convert American odds to implied probability
 * @param {number} americanOdds - American odds (e.g., +150 or -150)
 * @returns {number} Implied probability as decimal (e.g., 0.40 for 40%)
 */
export function americanToImplied(americanOdds) {
    if (americanOdds >= 0) {
        // Positive odds: probability = 100 / (odds + 100)
        return 100 / (americanOdds + 100);
    } else {
        // Negative odds: probability = |odds| / (|odds| + 100)
        const absOdds = Math.abs(americanOdds);
        return absOdds / (absOdds + 100);
    }
}

/**
 * Convert implied probability to American odds
 * @param {number} impliedProb - Implied probability as decimal (e.g., 0.40)
 * @returns {number} American odds (positive or negative)
 */
export function impliedToAmerican(impliedProb) {
    if (impliedProb <= 0 || impliedProb >= 1) {
        throw new Error('Probability must be between 0 and 1 (exclusive)');
    }

    if (impliedProb < 0.5) {
        // Underdog: positive odds
        return Math.round((100 / impliedProb) - 100);
    } else {
        // Favorite: negative odds
        return Math.round(-(impliedProb / (1 - impliedProb)) * 100);
    }
}

/**
 * Devig a full field of probabilities to sum to 100%
 * Uses multiplicative method (proportional scaling)
 * @param {number[]} probabilities - Array of implied probabilities as decimals
 * @returns {number[]} Normalized probabilities summing to 1.0
 */
export function devig(probabilities) {
    const total = probabilities.reduce((sum, p) => sum + p, 0);

    if (total === 0) {
        throw new Error('Total probability cannot be zero');
    }

    return probabilities.map(p => p / total);
}

/**
 * Format probability as percentage string
 * @param {number} prob - Probability as decimal
 * @param {number} decimals - Number of decimal places (default 1)
 * @returns {string} Formatted percentage (e.g., "40.0%")
 */
export function formatProbability(prob, decimals = 1) {
    return (prob * 100).toFixed(decimals) + '%';
}

/**
 * Format American odds with + prefix for positive values
 * @param {number} odds - American odds
 * @returns {string} Formatted odds string (e.g., "+150" or "-150")
 */
export function formatAmericanOdds(odds) {
    return odds >= 0 ? `+${odds}` : `${odds}`;
}
