// static/js/builderEvents.js

import { debounce, toast } from './utils.js';
import { getBlocks, spliceBlock, pushBlock } from './builderState.js';

async function updateRowToNextUnwatched(showData, userSelectElement, renderBuilder) {
    const seriesId = appState.seriesData.find(s => s.name === showData.name)?.id;
    if (!seriesId) {
        toast('Could not find that show in the library.', false);
        renderBuilder();
        return;
    }
    const loadingOverlay = document.getElementById('loading-overlay');
    try {
        loadingOverlay.style.display = 'flex';
        const response = await fetch(`api/shows/${seriesId}/first_unwatched?user_id=${userSelectElement.value}`);
        if (response.ok) {
            const ep = await response.json();
            showData.season = ep.ParentIndexNumber;
            showData.episode = ep.IndexNumber;
        } else {
            toast('Could not find next unwatched episode.', false);
        }
    } catch (e) {
        toast('Error fetching next unwatched episode.', false);
    } finally {
        loadingOverlay.style.display = 'none';
        renderBuilder();
    }
};

export function attachBuilderEventListeners(container, userSelectElement, renderBuilder) {
    // --- DEBOUNCED INPUT EVENT LISTENER ---
    container.addEventListener('input', debounce(async (event) => {
        const target = event.target;
        const blockEl = target.closest('.mixed-block');
        if (!blockEl) return;

        const blockIndex = parseInt(blockEl.dataset.blockIndex, 10);
        const blocks = getBlocks();
        if (isNaN(blockIndex) || !blocks[blockIndex]) return;
        const blockData = blocks[blockIndex];

        let shouldReRender = true;

        if (target.matches('.token-input')) { shouldReRender = false; }
        else if (target.matches('.tv-block-show-select')) {
            const rowEl = target.closest('.show-row');
            const rowIndex = parseInt(rowEl.dataset.rowIndex, 10);
            const showData = blockData.shows[rowIndex];

            showData.name = target.value;
            showData.unwatched = true;
            await updateRowToNextUnwatched(showData, userSelectElement, renderBuilder);
            return;
        }
        else if (target.matches('.tv-block-season')) {
            const rowEl = target.closest('.show-row');
            const rowIndex = parseInt(rowEl.dataset.rowIndex, 10);
            blockData.shows[rowIndex].season = target.value;
        }
        else if (target.matches('.tv-block-episode')) {
            const rowEl = target.closest('.show-row');
            const rowIndex = parseInt(rowEl.dataset.rowIndex, 10);
            blockData.shows[rowIndex].episode = target.value;
        } else if (target.matches('.tv-block-mode-select, .tv-block-count, .tv-block-end-season, .tv-block-end-episode, .tv-block-interleave')) {
            if (target.matches('.tv-block-mode-select')) blockData.mode = target.value;
            else if (target.matches('.tv-block-count')) blockData.count = target.value;
            else if (target.matches('.tv-block-end-season')) blockData.end_season = target.value;
            else if (target.matches('.tv-block-end-episode')) blockData.end_episode = target.value;
            else if (target.matches('.tv-block-interleave')) blockData.interleave = target.checked;
        } else if (target.matches('.movie-block-library-cb')) {
            blockData.filters.parent_ids = [...blockEl.querySelectorAll('.movie-block-library-cb:checked')].map(cb => cb.value);
        } else if (target.matches('.movie-block-year-from, .movie-block-year-to')) {
            blockData.filters.year_from = blockEl.querySelector('.movie-block-year-from').value;
            blockData.filters.year_to = blockEl.querySelector('.movie-block-year-to').value;
        } else if (target.matches('input[name^="limit-mode-"]')) {
            if (target.checked) {
                blockData.filters.limit = target.value === 'count' ? 5 : null;
                blockData.filters.duration_minutes = target.value === 'duration' ? 180 : null;
            }
        } else if (target.matches('.movie-block-limit-value, .movie-block-limit-duration-units')) {
            const limitModeRadio = blockEl.querySelector(`input[name^="limit-mode-"]:checked`);
            if (limitModeRadio && limitModeRadio.value === 'count') {
                blockData.filters.limit = parseInt(blockEl.querySelector('.movie-block-limit-value').value, 10);
            } else if(limitModeRadio && limitModeRadio.value === 'duration') {
                const units = parseInt(blockEl.querySelector('.movie-block-limit-duration-units')?.value || '60', 10);
                blockData.filters.duration_minutes = parseInt(blockEl.querySelector('.movie-block-limit-value').value, 10) * units;
            }
        } else {
            shouldReRender = false;
        }

        if (shouldReRender) renderBuilder();
    }, 400));

    // --- CLICK EVENT LISTENER (DELEGATED) ---
    container.addEventListener('click', async (event) => {
        const target = event.target;
        const button = target.closest('button, .token-state, .filter-toggle-btn, li, .first-unwatched-cb');
        if (!button) return;

        const blockEl = button.closest('.mixed-block');
        if (!blockEl) return;

        const blockIndex = parseInt(blockEl.dataset.blockIndex, 10);
        const blocks = getBlocks();
        if (isNaN(blockIndex) || !blocks[blockIndex]) return;

        const blockData = blocks[blockIndex];
        let shouldReRender = true;

        if(button.matches('.autocomplete-suggestions li')) {
            const input = button.closest('.token-field-wrapper').querySelector('.token-input');
            const itemType = button.dataset.itemType;
            const itemData = JSON.parse(button.dataset.itemData);
            if (itemType === 'genre') {
                if (!blockData.filters.genres_any) blockData.filters.genres_any = [];
                blockData.filters.genres_any.push(itemData.Name);
            } else if (itemType === 'person') {
                if (!blockData.filters.people) blockData.filters.people = [];
                blockData.filters.people.push(itemData);
            } else if (itemType === 'studio') {
                if (!blockData.filters.studios) blockData.filters.studios = [];
                blockData.filters.studios.push(itemData.Name);
            }
            input.value = ''; input.focus(); button.parentElement.innerHTML = '';
        } else if (button.matches('.delete-block-btn')) {
            spliceBlock(blockIndex, 1);
        } else if (button.matches('.duplicate-block-btn')) {
            const newBlock = JSON.parse(JSON.stringify(blockData));
            spliceBlock(blockIndex + 1, 0, newBlock);
        } else if (button.matches('.add-show-row-btn')) {
            if (!blockData.shows) blockData.shows = [];
            const defaultShowObject = {
                name: window.appState.seriesData[0]?.name || '',
                season: 1, episode: 1, unwatched: true
            };
            blockData.shows.push(defaultShowObject);
            await updateRowToNextUnwatched(defaultShowObject, userSelectElement, renderBuilder);
            return;
        } else if (button.matches('.show-row .delete-btn')) {
            const rowIndex = parseInt(button.closest('.show-row').dataset.rowIndex, 10);
            if (blockData.shows.length > 1) blockData.shows.splice(rowIndex, 1);
        } else if (button.matches('.first-unwatched-cb')) {
            const rowEl = button.closest('.show-row');
            const rowIndex = parseInt(rowEl.dataset.rowIndex, 10);
            const showData = blockData.shows[rowIndex];
            showData.unwatched = button.checked;

            if (button.checked) {
                await updateRowToNextUnwatched(showData, userSelectElement, renderBuilder);
            } else {
                renderBuilder();
            }
            return;
        } else if (button.matches('.random-ep-btn')) {
            shouldReRender = false;
            const rowIndex = parseInt(button.closest('.show-row').dataset.rowIndex, 10);
            const seriesId = appState.seriesData.find(s => s.name === blockData.shows[rowIndex].name)?.id;
            if (!seriesId) { toast('Select a show first.', false); return; }
            const ep = await (await fetch(`api/shows/${seriesId}/random_unwatched?user_id=${userSelectElement.value}`)).json();
            if (ep) {
                blockData.shows[rowIndex].season = ep.season;
                blockData.shows[rowIndex].episode = ep.episode;
                renderBuilder();
            }
        } else if (button.matches('.filter-toggle-btn.movie-block-watched')) {
             const cycle = { 'all': 'unplayed', 'unplayed': 'played', 'played': 'all' };
             blockData.filters.watched_status = cycle[blockData.filters.watched_status];
        } else if (button.matches('.filter-toggle-btn.movie-block-sort-by')) {
             const cycle = { 'Random': 'PremiereDate', 'PremiereDate': 'DateCreated', 'DateCreated': 'SortName', 'SortName': 'Random' };
             blockData.filters.sort_by = cycle[blockData.filters.sort_by];
        } else if (button.matches('.token-remove')) {
            const tokenEl = button.closest('.token');
            const tokenType = tokenEl.dataset.tokenType;
            const tokenIndex = parseInt(tokenEl.dataset.tokenIndex, 10);
            if(blockData.filters[tokenType]?.[tokenIndex] !== undefined) {
                blockData.filters[tokenType].splice(tokenIndex, 1);
            }
        } else if(button.matches('.token-state')) {
            const tokenEl = button.closest('.token');
            const tokenType = tokenEl.dataset.tokenType;
            const tokenIndex = parseInt(tokenEl.dataset.tokenIndex, 10);
            const token = blockData.filters[tokenType][tokenIndex];

            if(tokenEl.matches('.token-genre')) {
                const cycle = {'any': 'all', 'all': 'exclude', 'exclude': 'any'};
                const currentType = tokenEl.dataset.state;
                const newTypeKey = `genres_${cycle[currentType]}`;
                blockData.filters[tokenType].splice(tokenIndex, 1);
                if (!blockData.filters[newTypeKey]) blockData.filters[newTypeKey] = [];
                blockData.filters[newTypeKey].push(token);
            } else {
                const newTypeKey = tokenType === 'people' ? 'exclude_people' : tokenType === 'exclude_people' ? 'people' : tokenType === 'studios' ? 'exclude_studios' : 'studios';
                blockData.filters[tokenType].splice(tokenIndex, 1);
                if (!blockData.filters[newTypeKey]) blockData.filters[newTypeKey] = [];
                blockData.filters[newTypeKey].push(token);
            }
        } else { shouldReRender = false; }

        if (shouldReRender) renderBuilder();
    });

    // --- AUTOCOMPLETE EVENT LISTENERS ---
    container.addEventListener('input', debounce(async (e) => {
        const input = e.target;
        if (!input.matches('.token-input')) return;
        const suggestionsEl = input.nextElementSibling;
        const searchTerm = input.value.trim();
        suggestionsEl.innerHTML = '';
        if (searchTerm.length < 2) return;
        try {
            let suggestions = [];
            if (input.matches('.movie-block-genre-input')) {
                suggestions = appState.movieGenreData
                    .filter(g => g.Name.toLowerCase().includes(searchTerm.toLowerCase()))
                    .map(g => ({ type: 'genre', data: g, text: g.Name }));
            } else if (input.matches('.movie-block-person-input')) {
                const [people, studios] = await Promise.all([
                    fetch(`api/people?name=${encodeURIComponent(searchTerm)}`).then(res => res.json()),
                    fetch(`api/studios?name=${encodeURIComponent(searchTerm)}`).then(res => res.json())
                ]);
                people.forEach(p => suggestions.push({type: 'person', data: p, text: `${p.Name} (${p.Role || 'Person'})`}));
                studios.forEach(s => suggestions.push({type: 'studio', data: s, text: `${s.Name} (Studio)`}));
            }
            if (suggestions.length > 0) {
                const ul = document.createElement('ul');
                suggestions.forEach(item => {
                    const li = document.createElement('li');
                    li.dataset.itemType = item.type;
                    li.dataset.itemData = JSON.stringify(item.data);
                    li.textContent = item.text;
                    ul.appendChild(li);
                });
                suggestionsEl.appendChild(ul);
            }
        } catch (error) { console.error("Error fetching autocomplete:", error); }
    }, 300));

    container.addEventListener('focusout', (e) => {
        if(e.target.matches('.token-input')) {
            setTimeout(() => e.target.nextElementSibling.innerHTML = '', 150);
        }
    });
}