/**
 * Golf Odds Divergence Tracker
 * Main JavaScript file
 */

document.addEventListener('DOMContentLoaded', function() {
    const tournamentSelect = document.getElementById('tournament-select');
    const oddsTable = document.getElementById('odds-table');

    // Placeholder for future functionality
    tournamentSelect.addEventListener('change', function() {
        const selectedTournament = this.value;
        if (selectedTournament) {
            console.log('Selected tournament:', selectedTournament);
            // TODO: Load data from data/{tournament}.json
        }
    });

    console.log('Golf Odds Divergence Tracker initialized');
});
