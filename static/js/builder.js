// static/js/builder.js
import { post, debounce, toast } from './utils.js';
import { confirmModal, smartPlaylistModal, smartBuildModal } from './modals.js';
import { PresetManager, createTvShowRow } from './components.js';
import { renderTvBlock, renderMovieBlock, renderMusicBlock, updateTvBlockSummary, updateMusicBlockSummary } from './block_renderers.js';
import { appState } from './app.js';
import { SMART_BUILD_TYPES } from './definitions.js';

const AUTOSAVE_KEY = 'mixerbee_autosave';

// --- Local Helper Functions ---
function showQuickBuildModal({ button, type, title, description, defaultName, showCount = true, defaultCount = 10, extraParams = {}, userSelect }) {
    smartPlaylistModal.show({
        title, description, defaultName,
        countInput: showCount,
        countLabel: showCount ? 'Number of Items' : '',
        defaultCount,
        onCancel: () => {
            if (button) button.disabled = false;
        },
        onCreate: ({ playlistName, count }) => {
            const options = { ...extraParams };
            if (showCount) {
                options.count = count;
            }
            const body = {
                user_id: userSelect.value,
                playlist_name: playlistName,
                quick_build_type: type,
                options
            };
            post('api/quick_builds', body, button);
        }
    });
}

async function handleFetchThenShowModal({ button, type, fetchEndpoint, modalConfigFactory, userSelect }) {
    const loadingOverlay = document.getElementById('loading-overlay');
    loadingOverlay.style.display = 'flex';
    if (button) button.disabled = true;

    try {
        const response = await fetch(fetchEndpoint);
        if (!response.ok) {
            const errData = await response.json();
            throw new Error(errData.detail || `Could not fetch data from ${fetchEndpoint}.`);
        }
        const data = await response.json();
        loadingOverlay.style.display = 'none'; // Hide before showing modal

        const modalConfig = modalConfigFactory(data);
        showQuickBuildModal({ button, userSelect, type, ...modalConfig });
    } catch (error) {
        toast(`Error: ${error.message}`, false);
        loadingOverlay.style.display = 'none';
        if (button) button.disabled = false;
    }
}


function getBlockDataFromElement(blockEl) {
    const blockType = blockEl.dataset.type;
    let blockData = { type: blockType };

    if (blockType === 'tv') {
        const shows = [];
        blockEl.querySelectorAll('.show-row').forEach(row => {
            shows.push({
                name: row.querySelector('.tv-block-show-select').value,
                season: row.querySelector('.tv-block-season').value,
                episode: row.querySelector('.tv-block-episode').value,
                unwatched: row.querySelector('.first-unwatched-cb').checked
            });
        });
        const mode = blockEl.querySelector('.tv-block-mode-select').value;
        blockData = { ...blockData, shows, mode, interleave: blockEl.querySelector('.tv-block-interleave').checked };
        if (mode === 'count') {
            blockData.count = blockEl.querySelector('.tv-block-count').value;
        } else {
            blockData.end_season = blockEl.querySelector('.tv-block-end-season').value;
            blockData.end_episode = blockEl.querySelector('.tv-block-end-episode').value;
        }
    } else if (blockType === 'movie') {
        const yearFrom = blockEl.querySelector('.movie-block-year-from').value;
        const yearTo = blockEl.querySelector('.movie-block-year-to').value;

        const genres_any = [];
        const genres_all = [];
        const genres_exclude = [];
        blockEl.querySelectorAll('.token-genre').forEach(token => {
            const state = token.dataset.state;
            const name = token.dataset.name;
            if (state === 'any') { genres_any.push(name); }
            else if (state === 'all') { genres_all.push(name); }
            else if (state === 'exclude') { genres_exclude.push(name); }
        });

        const people = [];
        const exclude_people = [];
        const studios = [];
        const exclude_studios = [];
        blockEl.querySelectorAll('.movie-block-person-tokens .token').forEach(token => {
            const state = token.dataset.state;
            if (token.dataset.type === 'person') {
                const personData = { Id: token.dataset.id, Name: token.dataset.name, Role: token.dataset.role };
                if (state === 'include') { people.push(personData); }
                else { exclude_people.push(personData); }
            } else if (token.dataset.type === 'studio') {
                const studioName = token.dataset.name;
                if (state === 'include') { studios.push(studioName); }
                else { exclude_studios.push(studioName); }
            }
        });

        const filters = {
            genres_any, genres_all, genres_exclude,
            people, exclude_people,
            studios, exclude_studios,
            watched_status: blockEl.querySelector('.movie-block-watched').dataset.state,
            year_from: yearFrom || null,
            year_to: yearTo || null,
            sort_by: blockEl.querySelector('.movie-block-sort-by').dataset.state,
            parent_ids: [...blockEl.querySelectorAll('.movie-block-library-cb:checked')].map(cb => cb.value),
        };

        const limitModeRadio = blockEl.querySelector('input[name^="limit-mode-"]:checked');
        if (limitModeRadio) {
            const limitMode = limitModeRadio.value;
            const limitValue = parseInt(blockEl.querySelector('.movie-block-limit-value').value, 10);
            if (!isNaN(limitValue)) {
                if (limitMode === 'count') {
                    filters.limit = limitValue;
                } else if (limitMode === 'duration') {
                    const durationUnits = blockEl.querySelector('.movie-block-limit-duration-units');
                    const units = parseInt(durationUnits.value, 10);
                    if (!isNaN(units)) {
                        filters.duration_minutes = limitValue * units;
                    }
                }
            }
        }

        blockData.filters = filters;
    } else if (blockType === 'music') {
        const mode = blockEl.querySelector('.music-block-mode').value;
        let musicData = { mode };
        if (mode === 'genre') {
            const genreMatchRadio = blockEl.querySelector(`input[name^="music-block-genre-match-"]:checked`);
            musicData.filters = {
                genres: [...blockEl.querySelectorAll('.music-block-genre-cb:checked')].map(cb => cb.value),
                genre_match: genreMatchRadio ? genreMatchRadio.value : 'any',
                sort_by: blockEl.querySelector('.music-block-sort-by').value,
                limit: blockEl.querySelector('.music-block-limit').value
            };
        } else {
            musicData.artistId = blockEl.querySelector('.music-block-artist').value;
            musicData.albumId = blockEl.querySelector('.music-block-album').value;
            musicData.count = blockEl.querySelector('.music-block-count').value;
        }
        blockData.music = musicData;
    }
    return blockData;
}


// --- Main Builder Pane Initialization ---
function addBlockEventListeners(blockElement) {
    if (blockElement.dataset.type === 'tv') {
        const showsContainer = blockElement.querySelector('.tv-block-shows');
        new Sortable(showsContainer, {
            animation: 150,
            handle: '.drag-handle',
            ghostClass: 'sortable-ghost',
            onEnd: () => debouncedSaveBuilderState()
         });
    }
}

function getBlocksDataFromUI() {
    const blocksData = [];
    document.querySelectorAll('.mixed-block').forEach(blockEl => {
        blocksData.push(getBlockDataFromElement(blockEl));
    });
    return blocksData;
}

const saveBuilderState = () => {
    // This function can be called before the UI is ready, so we need a guard.
    if (!document.getElementById('mixed-playlist-blocks')) return;

    const data = getBlocksDataFromUI();
    if (data.length > 0) {
        localStorage.setItem(AUTOSAVE_KEY, JSON.stringify(data));
    } else {
        localStorage.removeItem(AUTOSAVE_KEY);
    }
};
const debouncedSaveBuilderState = debounce(saveBuilderState, 1500);

export function initBuilderPane(userSelectElement) {
    // Assign all DOM elements now that the DOM is ready.
    const blocksContainer = document.getElementById('mixed-playlist-blocks');
    const placeholder = blocksContainer.querySelector('.placeholder-text');
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

    // Instantiate the manager now that its elements exist.
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
        existingPlaylistSelect.style.display = isInAddMode ? 'block' : 'none';
        if (isInAddMode && existingPlaylistSelect.options.length <= 1) populatePlaylistsDropdown();
    });

    function checkPlaceholderVisibility() {
        if (placeholder) placeholder.style.display = blocksContainer.querySelectorAll('.mixed-block').length === 0 ? 'block' : 'none';
    }

const applyPresetToUI = (blocksData) => {
    if (!blocksData) return;
    blocksContainer.querySelectorAll('.mixed-block').forEach(el => el.remove());

    // Pre-process data for robustness against old AI formats
    blocksData.forEach(blockData => {
        if (blockData.type === 'movie' && blockData.filters) {
            // If the AI gives us an old 'genres' array, convert it to 'genres_any'
            if (blockData.filters.genres && !blockData.filters.genres_any) {
                blockData.filters.genres_any = blockData.filters.genres;
                delete blockData.filters.genres;
            }
        }
    });

    if (blocksData.length > 0) {
        blocksData.forEach(blockData => {
            let blockElement;
            const renderData = { data: blockData, userSelectElement, changeCallback: debouncedSaveBuilderState };
            if (blockData.type === 'tv') blockElement = renderTvBlock(renderData);
            else if (blockData.type === 'movie') blockElement = renderMovieBlock(renderData);
            else if (blockData.type === 'music') blockElement = renderMusicBlock(renderData);
            if (blockElement) {
                blocksContainer.appendChild(blockElement);
                addBlockEventListeners(blockElement);
            }
        });
    }

    checkPlaceholderVisibility();
    if (window.featherReplace) window.featherReplace();
    debouncedSaveBuilderState();
};

    async function checkAiConfig() {
        try {
            const response = await fetch('api/config_status');
            const config = await response.json();
            aiGeneratorContainer.style.display = config.is_ai_configured ? 'block' : 'none';
        } catch (e) {
            console.error("Could not check AI config status, hiding feature.", e);
            aiGeneratorContainer.style.display = 'none';
        }
    }

    collectionCb.addEventListener('change', () => {
        generateBtn.textContent = collectionCb.checked ? 'Build Collection' : 'Build';
        const isCollection = collectionCb.checked;
        buildModeSelect.disabled = isCollection;
        if (isCollection) {
            buildModeSelect.value = 'create';
            buildModeSelect.dispatchEvent(new Event('change'));
        }
    });

    new Sortable(blocksContainer, {
        animation: 150,
        handle: '.drag-handle',
        ghostClass: 'sortable-ghost',
        onEnd: () => debouncedSaveBuilderState()
    });

    mixedPresetManager.init(getBlocksDataFromUI, applyPresetToUI);

    aiPromptInput.addEventListener('input', () => {
        aiPromptClearBtn.classList.toggle('hidden', !aiPromptInput.value);
    });

    aiPromptClearBtn.addEventListener('click', () => {
        aiPromptInput.value = '';
        aiPromptClearBtn.classList.add('hidden');
        aiPromptInput.focus();
    });

    generateWithAiBtn.addEventListener('click', async (event) => {
        const prompt = aiPromptInput.value;
        if (!prompt.trim()) return alert('Please enter a prompt for the AI.');
        try {
            document.getElementById('loading-overlay').style.display = 'flex';
            generateWithAiBtn.disabled = true;
            const response = await fetch('api/create_from_text', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ prompt }) });
            const result = await response.json();
            if (response.ok && result.status === 'ok') {
                applyPresetToUI(result.blocks);
            } else {
                alert('Error from AI: ' + (result.detail || 'Could not generate playlist.'));
            }
        } catch (error) {
            console.error("Error generating with AI:", error);
            alert('An unexpected error occurred while communicating with the AI.');
        } finally {
            document.getElementById('loading-overlay').style.display = 'none';
            generateWithAiBtn.disabled = false;
        }
    });

    addBlockBtn.addEventListener('click', (e) => {
        e.stopPropagation();
        addBlockMenu.classList.toggle('hidden');
    });

    addBlockMenu.addEventListener('click', (e) => {
        e.preventDefault();
        const target = e.target.closest('.dropdown-item');
        if (!target) return;
        const blockType = target.dataset.blockType;
        let blockElement;
        const renderData = { userSelectElement, changeCallback: debouncedSaveBuilderState };

        if (blockType === 'tv') blockElement = renderTvBlock(renderData);
        else if (blockType === 'movie') blockElement = renderMovieBlock(renderData);
        else if (blockType === 'music') blockElement = renderMusicBlock(renderData);
        if (blockElement) {
            blocksContainer.appendChild(blockElement);
            addBlockEventListeners(blockElement);
            checkPlaceholderVisibility();
            if (window.featherReplace) window.featherReplace();
            debouncedSaveBuilderState();
        }
        addBlockMenu.classList.add('hidden');
    });

    document.addEventListener('click', () => {
        if (!addBlockMenu.classList.contains('hidden')) addBlockMenu.classList.add('hidden');
    });

    document.getElementById('clear-all-blocks-btn').addEventListener('click', () => {
        confirmModal.show({
            title: 'Clear All Blocks?',
            text: 'Are you sure you want to clear all blocks? This cannot be undone.',
            confirmText: 'Clear All',
            onConfirm: () => {
                applyPresetToUI([]);
            }
        });
    });

    blocksContainer.addEventListener('click', (event) => {
        const button = event.target.closest('button');
        if (!button) return;

        if (button.classList.contains('delete-block-btn')) {
            event.preventDefault();
            button.closest('.mixed-block')?.remove();
            checkPlaceholderVisibility();
            debouncedSaveBuilderState();
        }
        else if (button.classList.contains('duplicate-block-btn')) {
            event.preventDefault();
            const sourceBlock = button.closest('.mixed-block');
            if (!sourceBlock) return;

            const blockData = getBlockDataFromElement(sourceBlock);
            const renderData = { data: blockData, userSelectElement, changeCallback: debouncedSaveBuilderState };
            let newBlockElement;

            if (blockData.type === 'tv') newBlockElement = renderTvBlock(renderData);
            else if (blockData.type === 'movie') newBlockElement = renderMovieBlock(renderData);
            else if (blockData.type === 'music') newBlockElement = renderMusicBlock(renderData);

            if (newBlockElement) {
                sourceBlock.after(newBlockElement);
                addBlockEventListeners(newBlockElement);
                if (window.featherReplace) window.featherReplace();
                debouncedSaveBuilderState();
            }
        }
        else if (button.classList.contains('add-show-row-btn')) {
            const block = button.closest('.mixed-block');
            const showsContainer = block.querySelector('.tv-block-shows');
            const newRow = createTvShowRow({ rowData: {}, seriesData: appState.seriesData, userSelectElement, changeCallback: debouncedSaveBuilderState });
            showsContainer.appendChild(newRow);
            if (block.dataset.type === 'tv') {
                updateTvBlockSummary(block);
            }
            if (window.featherReplace) window.featherReplace();
            debouncedSaveBuilderState();
        }
    });

    blocksContainer.addEventListener('input', (event) => {
        if (event.target.classList.contains('tv-block-count')) {
            const block = event.target.closest('.mixed-block[data-type="tv"]');
            if (block) {
                updateTvBlockSummary(block);
            }
        }
    });

    blocksContainer.addEventListener('delete-row', (event) => {
        const row = event.target;
        const block = row.closest('.mixed-block');
        if (block.querySelectorAll('.show-row').length > 1) {
            row.remove();
            if (block.dataset.type === 'tv') {
                updateTvBlockSummary(block);
            }
        }
        debouncedSaveBuilderState();
    });

    generateBtn.addEventListener('click', (event) => {
        const blocks = getBlocksDataFromUI();
        if (blocks.length === 0) return alert('Please add at least one block to build a playlist.');
        const mode = buildModeSelect.value;
        const userId = userSelectElement.value;
        const createAsCollection = collectionCb.checked;
        if (mode === 'add') {
            const playlistId = existingPlaylistSelect.value;
            if (!playlistId) return alert("Please select a playlist to add to.");
            post(`api/playlists/${playlistId}/add-items`, { user_id: userId, blocks }, event);
        } else {
            if (createAsCollection && (blocks.length !== 1 || blocks[0].type !== 'movie')) {
                return alert('Collections can only be created from a single Movie Block.');
            }
            smartPlaylistModal.show({
                title: createAsCollection ? 'Name Your Collection' : 'My Collection',
                description: 'Please provide a name to continue.',
                countInput: false,
                defaultName: createAsCollection ? 'My Movie Collection' : 'My Mix',
                onCreate: ({ playlistName }) => {
                    const requestBody = { user_id: userId, playlist_name: playlistName, blocks, create_as_collection: createAsCollection };
                    post('api/create_mixed_playlist', requestBody, event);
                }
            });
        }
    });

    // --- Smart Build Logic ---
    function handleSmartBuildSelection(type, button) {
        const commonConfig = { button, type, userSelect: userSelectElement };
        switch (type) {
            case 'recently_added':
                showQuickBuildModal({ ...commonConfig, title: 'Recently Added', description: 'Creates a playlist of the newest movies and episodes.', defaultName: 'Recently Added', defaultCount: 25 });
                break;
            case 'next_up':
                showQuickBuildModal({ ...commonConfig, title: 'Next Up', description: 'Creates a playlist from your most recent in-progress shows.', defaultName: 'Next Up' });
                break;
            case 'pilot_sampler':
                showQuickBuildModal({ ...commonConfig, title: 'Pilot Sampler', description: 'Creates a playlist with random, unwatched pilot episodes.', defaultName: 'Pilot Sampler' });
                break;
            case 'from_the_vault':
                showQuickBuildModal({ ...commonConfig, title: 'From the Vault', description: 'Creates a playlist of favorited movies you haven\'t seen in a while.', defaultName: 'From the Vault', defaultCount: 20 });
                break;
            case 'genre_roulette':
                if (!appState.movieGenreData?.length) return toast("Movie genres not loaded yet.", false);
                const randomMovieGenre = appState.movieGenreData[Math.floor(Math.random() * appState.movieGenreData.length)];
                showQuickBuildModal({ ...commonConfig, title: `Movie Roulette: ${randomMovieGenre.Name}`, description: `A playlist of random, unwatched ${randomMovieGenre.Name} movies.`, defaultName: `Movie Roulette: ${randomMovieGenre.Name}`, defaultCount: 5, extraParams: { genre: randomMovieGenre.Name } });
                break;
            case 'artist_spotlight':
                handleFetchThenShowModal({ ...commonConfig, fetchEndpoint: 'api/music/random_artist', modalConfigFactory: (artist) => ({ title: `Artist Spotlight: ${artist.Name}`, description: `A playlist with the most popular tracks from ${artist.Name}.`, defaultName: `Spotlight: ${artist.Name}`, defaultCount: 15, extraParams: { artist_id: artist.Id } }) });
                break;
            case 'album_roulette':
                handleFetchThenShowModal({ ...commonConfig, fetchEndpoint: 'api/music/random_album', modalConfigFactory: (album) => ({ title: `Album: ${album.Name}`, description: `A playlist of all tracks from "${album.Name}" by ${album.ArtistItems?.[0]?.Name || 'Unknown Artist'}.`, defaultName: `Album: ${album.Name}`, showCount: false, extraParams: { album_id: album.Id } }) });
                break;
            case 'genre_sampler':
                if (!appState.musicGenreData?.length) return toast("Music genres not loaded yet.", false);
                const randomMusicGenre = appState.musicGenreData[Math.floor(Math.random() * appState.musicGenreData.length)];
                showQuickBuildModal({ ...commonConfig, title: `Music Sampler: ${randomMusicGenre.Name}`, description: `A playlist of random songs from the ${randomMusicGenre.Name} genre.`, defaultName: `Sampler: ${randomMusicGenre.Name}`, defaultCount: 20, extraParams: { genre: randomMusicGenre.Name } });
                break;
        }
    }

    smartBuildBtn.addEventListener('click', (event) => {
        smartBuildModal.show(SMART_BUILD_TYPES, (type) => handleSmartBuildSelection(type, event.currentTarget));
    });

    // --- Final Initialization ---
    function restoreAutosavedState() {
        const savedData = localStorage.getItem(AUTOSAVE_KEY);
        if (savedData) {
            try {
                const blocks = JSON.parse(savedData);
                if (Array.isArray(blocks) && blocks.length > 0) {
                    confirmModal.show({
                        title: 'Restore Previous Session?',
                        text: 'We found some unsaved blocks from your last session. Would you like to restore them?',
                        confirmText: 'Restore',
                        onConfirm: () => {
                            applyPresetToUI(blocks);
                        },
                        onCancel: () => {
                            localStorage.removeItem(AUTOSAVE_KEY);
                        }
                    });
                }
            } catch (e) {
                console.error("Could not parse autosaved data.", e);
                localStorage.removeItem(AUTOSAVE_KEY);
            }
        }
    }

    checkPlaceholderVisibility();
    checkAiConfig();
    populatePlaylistsDropdown();
    restoreAutosavedState();
}