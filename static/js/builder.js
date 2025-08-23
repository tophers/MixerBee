// static/js/builder.js
import { post, debounce, toast } from './utils.js';
import { confirmModal, smartPlaylistModal, smartBuildModal } from './modals.js';
import { PresetManager } from './components.js';
import { renderTvBlock, renderMovieBlock, renderMusicBlock, updateAllBlockPreviews } from './block_renderers.js';
import { SMART_BUILD_TYPES } from './definitions.js';

const AUTOSAVE_KEY = 'mixerbee_autosave';

// The builderState object is the single source of truth for the entire builder UI.
let builderState = {
    blocks: []
};

// The main render function. It rebuilds the UI from the state.
function renderBuilder() {
    const blocksContainer = document.getElementById('mixed-playlist-blocks');
    const placeholder = blocksContainer.querySelector('.placeholder-text');

    const openStates = new Set();
    blocksContainer.querySelectorAll('.mixed-block[data-block-index]').forEach(blockEl => {
        const index = blockEl.dataset.blockIndex;
        if (blockEl.open) {
            openStates.add(`block-${index}`);
        }
        blockEl.querySelectorAll('details[open][data-section]').forEach(detailEl => {
            openStates.add(`${index}-${detailEl.dataset.section}`);
        });
    });

    blocksContainer.innerHTML = '';
    blocksContainer.appendChild(placeholder);

    builderState.blocks.forEach((blockData, index) => {
        let blockElement;
        const renderData = { blockData, index };
        if (blockData.type === 'tv') blockElement = renderTvBlock(renderData);
        else if (blockData.type === 'movie') blockElement = renderMovieBlock(renderData);
        else if (blockData.type === 'music') blockElement = renderMusicBlock(renderData);

        if (blockElement) {
            if (openStates.has(`block-${index}`)) {
                blockElement.open = true;
            }
            blockElement.querySelectorAll('details[data-section]').forEach(detailEl => {
                if (openStates.has(`${index}-${detailEl.dataset.section}`)) {
                    detailEl.open = true;
                }
            });
            blocksContainer.appendChild(blockElement);
        }
    });

    checkPlaceholderVisibility();
    if (window.featherReplace) window.featherReplace();
    updateAllBlockPreviews();
    saveBuilderState();
}

function checkPlaceholderVisibility() {
    const blocksContainer = document.getElementById('mixed-playlist-blocks');
    const placeholder = blocksContainer.querySelector('.placeholder-text');
    if (placeholder) {
        placeholder.classList.toggle('hidden', builderState.blocks.length > 0);
    }
}

const saveBuilderState = () => {
    if (builderState.blocks.length > 0) {
        localStorage.setItem(AUTOSAVE_KEY, JSON.stringify(builderState));
    } else {
        localStorage.removeItem(AUTOSAVE_KEY);
    }
};

async function showQuickBuildModal({ button, type, title, description, defaultName, showCount = true, defaultCount = 10, extraParams = {} }) {
    const userSelect = document.getElementById('user-select');
    try {
        const { playlistName, count } = await smartPlaylistModal.show({
            title, description, defaultName, countInput: showCount,
            countLabel: showCount ? 'Number of Items' : '',
            defaultCount,
        });
        const options = { ...extraParams };
        if (showCount) options.count = count;
        const body = { user_id: userSelect.value, playlist_name: playlistName, quick_build_type: type, options };
        post('api/quick_builds', body, button);
    } catch (err) {
        if (button) button.disabled = false;
    }
}

async function handleFetchThenShowModal({ button, type, fetchEndpoint, modalConfigFactory }) {
    const loadingOverlay = document.getElementById('loading-overlay');
    loadingOverlay.classList.remove('hidden');
    if (button) button.disabled = true;
    try {
        const response = await fetch(fetchEndpoint);
        if (!response.ok) {
            const errData = await response.json();
            throw new Error(errData.detail || `Could not fetch data from ${fetchEndpoint}.`);
        }
        const data = await response.json();
        loadingOverlay.classList.add('hidden');
        const modalConfig = modalConfigFactory(data);
        await showQuickBuildModal({ button, type, ...modalConfig });
    } catch (error) {
        toast(`Error: ${error.message}`, false);
        loadingOverlay.classList.add('hidden');
        if (button) button.disabled = false;
    }
}

export function initBuilderPane(userSelectElement) {
    window.appState.builderState = builderState;

    const blocksContainer = document.getElementById('mixed-playlist-blocks');
    const aiGeneratorContainer = document.getElementById('ai-generator-container');
    const aiPromptInput = document.getElementById('ai-prompt-input');
    const generateWithAiBtn = document.getElementById('generate-with-ai-btn');
    const generateBtn = document.getElementById('generate-mixed-playlist-btn');
    const collectionCb = document.getElementById('create-as-collection-cb');
    const addBlockBtn = document.getElementById('add-block-btn');
    const addBlockMenu = document.getElementById('add-block-menu');
    const smartBuildBtn = document.getElementById('smart-build-btn');
    const buildModeSelect = document.getElementById('build-mode-select');
    const existingPlaylistSelect = document.getElementById('existing-playlist-select');
    const aiPromptClearBtn = document.getElementById('ai-prompt-clear-btn');

    const mixedPresetManager = new PresetManager('mixerbeeMixedPresets', {
        loadSelect: document.getElementById('load-preset-select'),
        updateBtn: document.getElementById('update-preset-btn'),
        saveAsBtn: document.getElementById('save-as-preset-btn'),
        deleteBtn: document.getElementById('delete-preset-btn'),
        importBtn: document.getElementById('import-preset-btn'),
        exportBtn: document.getElementById('export-preset-btn')
    });

    const populatePlaylistsDropdown = async () => {
        try {
            const userId = userSelectElement.value;
            const playlists = await (await fetch(`api/users/${userId}/playlists`)).json();
            existingPlaylistSelect.innerHTML = '<option value="">-- Select a playlist --</option>';
            playlists.forEach(p => {
                const option = document.createElement('option');
                option.value = p.Id;
                option.textContent = p.Name;
                existingPlaylistSelect.appendChild(option);
            });
        } catch (err) {
            console.error("Failed to fetch user playlists:", err);
            toast("Could not load existing playlists.", false);
        }
    };

    buildModeSelect.addEventListener('change', () => {
        const isInAddMode = buildModeSelect.value === 'add';
        existingPlaylistSelect.classList.toggle('hidden', !isInAddMode);
        if (isInAddMode && existingPlaylistSelect.options.length <= 1) {
            populatePlaylistsDropdown();
        }
    });

    const applyDataToUI = (blocksData = []) => {
        (blocksData || []).forEach(blockData => {
            if (blockData.type === 'movie' && blockData.filters?.genres && !blockData.filters.genres_any) {
                blockData.filters.genres_any = blockData.filters.genres;
                delete blockData.filters.genres;
            }
        });
        builderState.blocks = blocksData;
        renderBuilder();
    };

    async function checkAiConfig() {
        try {
            const response = await fetch('api/config_status');
            const config = await response.json();
            aiGeneratorContainer.classList.toggle('hidden', !config.is_ai_configured);
        } catch (e) {
            console.error("Could not check AI config status, hiding feature.", e);
            aiGeneratorContainer.classList.add('hidden');
        }
    }
    
    collectionCb.addEventListener('change', () => {
        generateBtn.textContent = collectionCb.checked ? 'Build Collection' : 'Build';
        buildModeSelect.disabled = collectionCb.checked;
        if (collectionCb.checked) {
            buildModeSelect.value = 'create';
            buildModeSelect.dispatchEvent(new Event('change'));
        }
    });

    new Sortable(blocksContainer, {
        animation: 150, handle: '.drag-handle', ghostClass: 'sortable-ghost',
        onEnd: (evt) => {
            if (evt.oldIndex === evt.newIndex) return;
            const [movedItem] = builderState.blocks.splice(evt.oldIndex - 1, 1);
            builderState.blocks.splice(evt.newIndex - 1, 0, movedItem);
            renderBuilder();
        }
    });

    mixedPresetManager.init(() => builderState.blocks, applyDataToUI);

    aiPromptInput.addEventListener('input', () => aiPromptClearBtn.classList.toggle('hidden', !aiPromptInput.value));
    aiPromptClearBtn.addEventListener('click', () => {
        aiPromptInput.value = '';
        aiPromptClearBtn.classList.add('hidden');
        aiPromptInput.focus();
    });
    generateWithAiBtn.addEventListener('click', async () => {
        const prompt = aiPromptInput.value;
        if (!prompt.trim()) return toast('Please enter a prompt for the AI.', false);
        const loadingOverlay = document.getElementById('loading-overlay');
        try {
            loadingOverlay.classList.remove('hidden');
            generateWithAiBtn.disabled = true;
            const response = await post('api/create_from_text', { prompt });
            if (response.status === 'ok') {
                applyDataToUI(response.blocks);
            }
        } finally {
            loadingOverlay.classList.add('hidden');
            generateWithAiBtn.disabled = false;
        }
    });

    addBlockBtn.addEventListener('click', (e) => { e.stopPropagation(); addBlockMenu.classList.toggle('hidden'); });
    addBlockMenu.addEventListener('click', (e) => {
        e.preventDefault();
        const target = e.target.closest('.dropdown-item');
        if (!target) return;
        const blockType = target.dataset.blockType;
        let newBlockData;

        if (blockType === 'tv') {
            const defaultShowObject = {
                name: window.appState.seriesData[0]?.name || '',
                season: 1,
                episode: 1,
                unwatched: false
            };
            newBlockData = { type: 'tv', shows: [defaultShowObject], mode: 'count', count: 1, interleave: true };
        } 
        else if (blockType === 'movie') {
            newBlockData = { type: 'movie', filters: { watched_status: 'unplayed', sort_by: 'Random', parent_ids: appState.libraryData.map(l => l.Id) } };
        } 
        else if (blockType === 'music') {
            newBlockData = { type: 'music', music: { mode: 'album' } };
        }

        if (newBlockData) { builderState.blocks.push(newBlockData); renderBuilder(); }
        addBlockMenu.classList.add('hidden');
    });

    document.addEventListener('click', () => !addBlockMenu.classList.contains('hidden') && addBlockMenu.classList.add('hidden'));

    document.getElementById('clear-all-blocks-btn').addEventListener('click', async () => {
        try {
            await confirmModal.show({ title: 'Clear All Blocks?', text: 'Are you sure?', confirmText: 'Clear All' });
            applyDataToUI([]);
        } catch (err) { /* Cancelled */ }
    });

    blocksContainer.addEventListener('input', debounce((event) => {
        const target = event.target;
        const blockEl = target.closest('.mixed-block');
        if (!blockEl) return;

        const blockIndex = parseInt(blockEl.dataset.blockIndex, 10);
        if (isNaN(blockIndex) || !builderState.blocks[blockIndex]) return;
        const blockData = builderState.blocks[blockIndex];

        let shouldReRender = true;
        
        if (target.matches('.token-input')) { shouldReRender = false; }
        else if (target.matches('.tv-block-show-select, .tv-block-season, .tv-block-episode, .first-unwatched-cb')) {
            const rowIndex = parseInt(target.closest('.show-row').dataset.rowIndex, 10);
            const showData = blockData.shows[rowIndex];
            if (target.matches('.tv-block-show-select')) showData.name = target.value;
            else if (target.matches('.tv-block-season')) showData.season = target.value;
            else if (target.matches('.tv-block-episode')) showData.episode = target.value;
            else if (target.matches('.first-unwatched-cb')) {
                showData.unwatched = target.checked;
                shouldReRender = false;
            }
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
    
    blocksContainer.addEventListener('click', async (event) => {
        const target = event.target;
        const button = target.closest('button, .token-state, .filter-toggle-btn, li, .first-unwatched-cb');
        if (!button) return;

        const blockEl = button.closest('.mixed-block');
        if (!blockEl) return;

        const blockIndex = parseInt(blockEl.dataset.blockIndex, 10);
        if (isNaN(blockIndex) || !builderState.blocks[blockIndex]) return;

        const blockData = builderState.blocks[blockIndex];
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
            builderState.blocks.splice(blockIndex, 1);
        } else if (button.matches('.duplicate-block-btn')) {
            const newBlock = JSON.parse(JSON.stringify(blockData));
            builderState.blocks.splice(blockIndex + 1, 0, newBlock);
        } else if (button.matches('.add-show-row-btn')) {
            if (!blockData.shows) blockData.shows = [];
            const defaultShowObject = {
                name: window.appState.seriesData[0]?.name || '',
                season: 1, episode: 1, unwatched: false
            };
            blockData.shows.push(defaultShowObject);
        } else if (button.matches('.show-row .delete-btn')) {
            const rowIndex = parseInt(button.closest('.show-row').dataset.rowIndex, 10);
            if (blockData.shows.length > 1) blockData.shows.splice(rowIndex, 1);
        } else if (button.matches('.first-unwatched-cb')) {
            shouldReRender = false;
            const rowIndex = parseInt(button.closest('.show-row').dataset.rowIndex, 10);
            const showData = blockData.shows[rowIndex];
            showData.unwatched = button.checked;
            if (button.checked) {
                const seriesId = appState.seriesData.find(s => s.name === showData.name)?.id;
                if (!seriesId) { toast('Select a show first.', false); return; }
                const ep = await (await fetch(`api/shows/${seriesId}/first_unwatched?user_id=${userSelectElement.value}`)).json();
                if (ep) {
                    showData.season = ep.ParentIndexNumber;
                    showData.episode = ep.IndexNumber;
                }
            }
            renderBuilder();
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

    generateBtn.addEventListener('click', async (event) => {
        if (builderState.blocks.length === 0) return toast('Please add at least one block.', false);
        const mode = buildModeSelect.value;
        const createAsCollection = collectionCb.checked;
        if (mode === 'add') {
            const playlistId = existingPlaylistSelect.value;
            if (!playlistId) return toast("Select a playlist to add to.", false);
            post(`api/playlists/${playlistId}/add-items`, { user_id: userSelectElement.value, blocks: builderState.blocks }, event);
        } else {
            if (createAsCollection && (builderState.blocks.length !== 1 || builderState.blocks[0].type !== 'movie')) {
                return toast('Collections can only be created from a single Movie Block.', false);
            }
            try {
                const { playlistName } = await smartPlaylistModal.show({
                    title: createAsCollection ? 'Name Your Collection' : 'Name Your Playlist',
                    description: 'Please provide a name to continue.', countInput: false,
                    defaultName: createAsCollection ? 'My Movie Collection' : 'My Mix',
                });
                post('api/create_mixed_playlist', { user_id: userSelectElement.value, playlist_name: playlistName, blocks: builderState.blocks, create_as_collection: createAsCollection }, event);
            } catch (err) { /* Cancelled */ }
        }
    });

    async function handleSmartBuildSelection(type, button) {
        const commonConfig = { button, type };
        switch (type) {
            case 'recently_added':
                await showQuickBuildModal({ ...commonConfig, title: 'Recently Added', description: 'Creates a playlist of the newest movies and episodes.', defaultName: 'Recently Added', defaultCount: 25 });
                break;
            case 'next_up':
                await showQuickBuildModal({ ...commonConfig, title: 'Next Up', description: 'Creates a playlist from your most recent in-progress shows.', defaultName: 'Next Up' });
                break;
            case 'pilot_sampler':
                await showQuickBuildModal({ ...commonConfig, title: 'Pilot Sampler', description: 'Creates a playlist with random, unwatched pilot episodes.', defaultName: 'Pilot Sampler' });
                break;
            case 'from_the_vault':
                await showQuickBuildModal({ ...commonConfig, title: 'From the Vault', description: 'Creates a playlist of favorited movies you haven\'t seen in a while.', defaultName: 'From the Vault', defaultCount: 20 });
                break;
            case 'genre_roulette':
                if (!appState.movieGenreData?.length) return toast("Movie genres not loaded yet.", false);
                const randomMovieGenre = appState.movieGenreData[Math.floor(Math.random() * appState.movieGenreData.length)];
                await showQuickBuildModal({ ...commonConfig, title: `Movie Roulette: ${randomMovieGenre.Name}`, description: `A playlist of random, unwatched ${randomMovieGenre.Name} movies.`, defaultName: `Movie Roulette: ${randomMovieGenre.Name}`, defaultCount: 5, extraParams: { genre: randomMovieGenre.Name } });
                break;
            case 'artist_spotlight':
                await handleFetchThenShowModal({ ...commonConfig, fetchEndpoint: 'api/music/random_artist', modalConfigFactory: (artist) => ({ title: `Artist Spotlight: ${artist.Name}`, description: `A playlist with the most popular tracks from ${artist.Name}.`, defaultName: `Spotlight: ${artist.Name}`, defaultCount: 15, extraParams: { artist_id: artist.Id } }) });
                break;
            case 'album_roulette':
                await handleFetchThenShowModal({ ...commonConfig, fetchEndpoint: 'api/music/random_album', modalConfigFactory: (album) => ({ title: `Album: ${album.Name}`, description: `A playlist of all tracks from "${album.Name}" by ${album.ArtistItems?.[0]?.Name || 'Unknown Artist'}.`, defaultName: `Album: ${album.Name}`, showCount: false, extraParams: { album_id: album.Id } }) });
                break;
            case 'genre_sampler':
                if (!appState.musicGenreData?.length) return toast("Music genres not loaded yet.", false);
                const randomMusicGenre = appState.musicGenreData[Math.floor(Math.random() * appState.musicGenreData.length)];
                await showQuickBuildModal({ ...commonConfig, title: `Music Sampler: ${randomMusicGenre.Name}`, description: `A playlist of random songs from the ${randomMusicGenre.Name} genre.`, defaultName: `Sampler: ${randomMusicGenre.Name}`, defaultCount: 20, extraParams: { genre: randomMusicGenre.Name } });
                break;
        }
    }

    smartBuildBtn.addEventListener('click', async (event) => {
        try {
            const type = await smartBuildModal.show(SMART_BUILD_TYPES);
            await handleSmartBuildSelection(type, event.currentTarget);
        } catch (err) { console.log('Smart build cancelled.') }
    });

    blocksContainer.addEventListener('input', debounce(async (e) => {
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
    
    blocksContainer.addEventListener('focusout', (e) => {
        if(e.target.matches('.token-input')) {
            setTimeout(() => e.target.nextElementSibling.innerHTML = '', 150);
        }
    });

    // FIX: Re-introduce the restore function definition
    async function restoreAutosavedState() {
        const savedData = localStorage.getItem(AUTOSAVE_KEY);
        if (savedData) {
            try {
                const blocks = JSON.parse(savedData);
                if (Array.isArray(blocks) && blocks.length > 0) {
                    await confirmModal.show({
                        title: 'Restore Previous Session?',
                        text: 'We found some unsaved blocks from your last session. Would you like to restore them?',
                        confirmText: 'Restore',
                    });
                    applyDataToUI(blocks);
                }
            } catch (e) {
                if (e.message.includes('Modal cancelled')) {
                    // If user says no, clear the storage so they aren't asked again.
                    localStorage.removeItem(AUTOSAVE_KEY);
                } else {
                    console.error("Could not parse or restore autosaved data.", e);
                    localStorage.removeItem(AUTOSAVE_KEY);
                }
            }
        }
    }

    checkAiConfig();
    populatePlaylistsDropdown();
    restoreAutosavedState(); // This call now works because the function is defined above.
    renderBuilder();
}