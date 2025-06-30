// static/mixed.js
import { post, smartPlaylistModal, debounce } from './utils.js';
import { PresetManager, createTvShowRow } from './utils.js';

let seriesData = [];
let genreData = [];
let libraryData = [];
let userSelectElement;

const icon = (txt, cls, title) => Object.assign(document.createElement('button'), { type: 'button', className: 'icon-btn ' + cls, textContent: txt, title: title });

function addBlockEventListeners(blockElement, changeCallback) {
    if (blockElement.dataset.type === 'tv') {
        const showsContainer = blockElement.querySelector('.tv-block-shows');
        new Sortable(showsContainer, {
            animation: 150,
            handle: '.drag-handle',
            ghostClass: 'sortable-ghost',
            onEnd: changeCallback // Trigger save on reorder
        });
    }
}

function getFiltersFromMovieBlock(blockElement) {
    const yearFrom = blockElement.querySelector('.movie-block-year-from').value;
    const yearTo = blockElement.querySelector('.movie-block-year-to').value;
    const filters = {
        genres: [...blockElement.querySelectorAll('.movie-block-genre-cb:checked')].map(cb => cb.value),
        genre_match: blockElement.querySelector(`input[name^="movie-block-genre-match-"]:checked`).value,
        watched_status: blockElement.querySelector('.movie-block-watched').value,
        year_from: yearFrom ? parseInt(yearFrom) : undefined,
        year_to: yearTo ? parseInt(yearTo) : undefined,
        sort_by: blockElement.querySelector('.movie-block-sort-by').value,
        parent_ids: [...blockElement.querySelectorAll('.movie-block-library-cb:checked')].map(cb => cb.value)
    };
    // For preview, we don't care about limits or duration
    return filters;
}

async function updateMovieBlockPreviewCount(blockElement) {
    const countSpan = blockElement.querySelector('.movie-block-preview-count');
    if (!countSpan) return;
    countSpan.textContent = '...';

    const previewFilters = getFiltersFromMovieBlock(blockElement);
    const requestBody = { user_id: userSelectElement.value, filters: previewFilters };

    try {
        const response = await fetch('api/movies/preview_count', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(requestBody)
        });
        if (!response.ok) throw new Error(`HTTP error! status: ${response.status}`);
        const data = await response.json();
        countSpan.textContent = `${data.count} movies match`;
    } catch (error) {
        console.error("Error fetching movie preview count:", error);
        countSpan.textContent = 'Error!';
    }
}

function renderTvBlock(data = null, changeCallback) {
    const initialRows = data?.shows || [{}];
    const isInterleaved = (data?.interleave !== false);

    const blockElement = document.createElement('div');
    blockElement.className = 'mixed-block';
    blockElement.dataset.type = 'tv';

    const header = document.createElement('div');
    header.className = 'mixed-block-header';
    const headerTitle = document.createElement('h3');
    headerTitle.innerHTML = `<span class="block-icon">📺</span> TV Block`;
    const headerControls = document.createElement('div');
    headerControls.className = 'mixed-block-controls';
    headerControls.append(
        icon('×', 'danger delete-block-btn', 'Delete Block')
    );
    header.append(icon('↕', 'drag-handle icon-btn', 'Drag to reorder'), headerTitle, headerControls);

    const body = document.createElement('div');
    body.className = 'mixed-block-body';

    const showsContainer = document.createElement('div');
    showsContainer.className = 'tv-block-shows';
    initialRows.forEach(rowData => {
        const newRow = createTvShowRow({
            rowData: rowData,
            seriesData: seriesData,
            userSelectElement: userSelectElement,
            changeCallback: changeCallback
        });
        showsContainer.appendChild(newRow);
    });

    const addShowBtn = Object.assign(document.createElement('button'), { type: 'button', className: 'secondary add-show-row-btn', textContent: '➕ Add Show' });
    const buttonGroup = document.createElement('div');
    buttonGroup.className = 'button-group';
    buttonGroup.appendChild(addShowBtn);

    const footer = document.createElement('div');
    footer.className = 'block-options-footer';
    const countLabel = document.createElement('label');
    const countInput = Object.assign(document.createElement('input'), { type: 'number', className: 'tv-block-count', value: data?.count || 1, min: 1 });
    countLabel.append('Episodes per show: ', countInput);
    const interleaveLabel = document.createElement('label');
    interleaveLabel.className = 'interleave-label';
    const interleaveCb = Object.assign(document.createElement('input'), { type: 'checkbox', className: 'tv-block-interleave', checked: isInterleaved });
    interleaveLabel.append(interleaveCb, ' Interleave');
    footer.append(countLabel, interleaveLabel);

    body.append(showsContainer, buttonGroup, footer);
    blockElement.append(header, body);

    return blockElement;
}

function renderMovieBlock(data = null) {
    const filters = data?.filters || {};
    const blockId = `block-${Date.now()}`;

    const blockElement = document.createElement('div');
    blockElement.className = 'mixed-block';
    blockElement.dataset.type = 'movie';
    blockElement.dataset.id = blockId;

    const header = document.createElement('div');
    header.className = 'mixed-block-header';
    const headerTitle = document.createElement('h3');
    headerTitle.innerHTML = `<span class="block-icon">🎬</span> Movie Block`;
    const headerControls = document.createElement('div');
    headerControls.className = 'mixed-block-controls';
    headerControls.append(
        icon('×', 'danger delete-block-btn', 'Delete Block')
    );
    header.append(icon('↕', 'drag-handle icon-btn', 'Drag to reorder'), headerTitle, headerControls);

    const body = document.createElement('div');
    body.className = 'mixed-block-body';
    
    // --- Library Filter ---
    const libraryFieldset = document.createElement('fieldset');
    libraryFieldset.className = 'filter-group';
    const libraryLegend = document.createElement('legend');
    libraryLegend.textContent = 'Libraries';
    const libraryGrid = document.createElement('div');
    libraryGrid.className = 'checkbox-grid';
    libraryData.forEach(lib => {
        const label = document.createElement('label');
        // If no libraries are saved in the preset, default to checking all of them.
        const isChecked = filters.parent_ids ? filters.parent_ids.includes(lib.Id) : true;
        const cb = Object.assign(document.createElement('input'), { type: 'checkbox', className: 'movie-block-library-cb', value: lib.Id, checked: isChecked });
        label.append(cb, ` ${lib.Name}`);
        libraryGrid.appendChild(label);
    });
    libraryFieldset.append(libraryLegend, libraryGrid);


    const genreFieldset = document.createElement('fieldset');
    genreFieldset.className = 'filter-group';
    const genreLegend = document.createElement('legend');
    genreLegend.textContent = 'Genres';

    const genreDetails = document.createElement('details');
    const genreSummary = document.createElement('summary');
    genreSummary.textContent = 'Expand/Collapse Genre List';

    const genreGrid = document.createElement('div');
    genreGrid.className = 'checkbox-grid';
    genreData.forEach(g => {
        const label = document.createElement('label');
        const cb = Object.assign(document.createElement('input'), { type: 'checkbox', className: 'movie-block-genre-cb', value: g.Name, checked: filters.genres?.includes(g.Name) });
        label.append(cb, ` ${g.Name}`);
        genreGrid.appendChild(label);
    });

    const genreMatchToggle = document.createElement('div');
    genreMatchToggle.className = 'genre-match-toggle';
    ['any', 'all'].forEach(val => {
        const label = document.createElement('label');
        const radio = Object.assign(document.createElement('input'), { type: 'radio', name: `movie-block-genre-match-${blockId}`, value: val });
        if ((val === 'any' && filters.genre_match !== 'all') || !filters.genre_match) radio.checked = true;
        if (val === 'all' && filters.genre_match === 'all') radio.checked = true;
        label.append(radio, ` Match ${val.charAt(0).toUpperCase() + val.slice(1)}`);
        genreMatchToggle.appendChild(label);
    });

    genreDetails.append(genreSummary, genreGrid, genreMatchToggle);
    genreFieldset.append(genreLegend, genreDetails);


    const otherFiltersFieldset = document.createElement('fieldset');
    otherFiltersFieldset.className = 'filter-group';
    const otherFiltersLegend = document.createElement('legend');
    otherFiltersLegend.textContent = 'Filters';

    const filterDetails = document.createElement('details');
    const filterSummary = document.createElement('summary');
    filterSummary.textContent = 'Expand/Collapse Filters';

    const otherFiltersGrid = document.createElement('div');
    otherFiltersGrid.className = 'movie-block-filter-grid';

    const watchedLabel = document.createElement('label');
    const watchedSelect = Object.assign(document.createElement('select'), { className: 'movie-block-watched' });
    watchedSelect.innerHTML = `<option value="all">All</option><option value="unplayed">Unwatched Only</option><option value="played">Watched Only</option>`;
    watchedSelect.value = filters.watched_status || 'all';
    watchedLabel.append('Watched: ', watchedSelect);

    const yearFromLabel = document.createElement('label');
    const yearFromInput = Object.assign(document.createElement('input'), { type: 'number', className: 'movie-block-year-from', placeholder: 'e.g., 1980', value: filters.year_from || '' });
    yearFromLabel.append('From Year: ', yearFromInput);

    const yearToLabel = document.createElement('label');
    const yearToInput = Object.assign(document.createElement('input'), { type: 'number', className: 'movie-block-year-to', placeholder: 'e.g., 1989', value: filters.year_to || '' });
    yearToLabel.append('To Year: ', yearToInput);

    const sortLabel = document.createElement('label');
    const sortSelect = Object.assign(document.createElement('select'), { className: 'movie-block-sort-by' });
    sortSelect.innerHTML = `<option value="Random">Random</option><option value="PremiereDate">Release Date</option><option value="DateCreated">Date Added</option><option value="SortName">Name</option>`;
    sortSelect.value = filters.sort_by || 'Random';
    sortLabel.append('Sort By: ', sortSelect);

    const limitLabel = document.createElement('label');
    const limitSelect = Object.assign(document.createElement('select'), { className: 'movie-block-limit-select' });
    limitSelect.innerHTML = `
        <optgroup label="By Count">
            <option value="limit:1">1 Movie</option>
            <option value="limit:2">2 Movies</option>
            <option value="limit:3">3 Movies</option>
            <option value="limit:5">5 Movies</option>
            <option value="limit:10">10 Movies</option>
        </optgroup>
        <optgroup label="By Duration">
            <option value="duration:180">~3 Hours</option>
            <option value="duration:240">~4 Hours</option>
            <option value="duration:360">~6 Hours</option>
            <option value="duration:480">~8 Hours</option>
            <option value="duration:600">~10 Hours</option>
        </optgroup>
        <option value="">All Matching Movies</option>
    `;

    if (filters.duration_minutes) {
        limitSelect.value = `duration:${filters.duration_minutes}`;
    } else if (filters.limit) {
        limitSelect.value = `limit:${filters.limit}`;
    } else {
        limitSelect.value = 'limit:1';
    }
    limitLabel.append('Limit: ', limitSelect);
    otherFiltersGrid.append(watchedLabel, yearFromLabel, yearToLabel, sortLabel, limitLabel);

    const movieBlockFooter = document.createElement('div');
    movieBlockFooter.className = 'movie-block-footer';
    const previewCountSpan = document.createElement('span');
    previewCountSpan.className = 'movie-block-preview-count';
    movieBlockFooter.appendChild(previewCountSpan);

    filterDetails.append(filterSummary, otherFiltersGrid, movieBlockFooter);
    otherFiltersFieldset.append(otherFiltersLegend, filterDetails);

    body.append(libraryFieldset, genreFieldset, otherFiltersFieldset);
    blockElement.append(header, body);

    return blockElement;
}

function getBlocksDataFromUI() {
    const blocksData = [];
    document.querySelectorAll('.mixed-block').forEach(blockEl => {
        const blockType = blockEl.dataset.type;
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
            blocksData.push({
                type: 'tv', shows,
                count: blockEl.querySelector('.tv-block-count').value,
                interleave: blockEl.querySelector('.tv-block-interleave').checked
            });
        } else if (blockType === 'movie') {
            const yearFrom = blockEl.querySelector('.movie-block-year-from').value;
            const yearTo = blockEl.querySelector('.movie-block-year-to').value;

            const filters = {
                genres: [...blockEl.querySelectorAll('.movie-block-genre-cb:checked')].map(cb => cb.value),
                genre_match: blockEl.querySelector(`input[name^="movie-block-genre-match-"]:checked`).value,
                watched_status: blockEl.querySelector('.movie-block-watched').value,
                year_from: yearFrom || null,
                year_to: yearTo || null,
                sort_by: blockEl.querySelector('.movie-block-sort-by').value,
                parent_ids: [...blockEl.querySelectorAll('.movie-block-library-cb:checked')].map(cb => cb.value)
            };

            const limitValue = blockEl.querySelector('.movie-block-limit-select').value;
            if (limitValue) {
                const [type, value] = limitValue.split(':');
                if (type === 'limit') {
                    filters.limit = parseInt(value, 10);
                } else if (type === 'duration') {
                    filters.duration_minutes = parseInt(value, 10);
                }
            }

            blocksData.push({ type: 'movie', filters: filters });
        }
    });
    return blocksData;
}

function applyPresetToUI(blocksData, blocksContainer, changeCallback) {
    if (!blocksData) return;
    // Instead of destroying the container, just remove the block elements
    blocksContainer.querySelectorAll('.mixed-block').forEach(el => el.remove());
    blocksData.forEach(blockData => {
        let blockElement;
        if (blockData.type === 'tv') { blockElement = renderTvBlock(blockData, changeCallback); }
        else if (blockData.type === 'movie') { blockElement = renderMovieBlock(blockData); }
        if (blockElement) {
            blocksContainer.appendChild(blockElement);
            addBlockEventListeners(blockElement, changeCallback);
            if (blockData.type === 'movie') {
                updateMovieBlockPreviewCount(blockElement);
            }
        }
    });
}

export function initMixedPane(userSel, shows, genres, movieLibraries) {
    userSelectElement = userSel;
    seriesData = shows;
    genreData = genres;
    libraryData = movieLibraries;
    const blocksContainer = document.getElementById('mixed-playlist-blocks');
    const placeholder = blocksContainer.querySelector('.placeholder-text');
    const aiGeneratorContainer = document.getElementById('ai-generator-container');
    const aiPromptInput = document.getElementById('ai-prompt-input');
    const generateWithAiBtn = document.getElementById('generate-with-ai-btn');
    const moviePreviewDebouncer = debounce(updateMovieBlockPreviewCount, 500);
    const generateBtn = document.getElementById('generate-mixed-playlist-btn');
    const collectionCb = document.getElementById('create-as-collection-cb');

    const mixedPresetManager = new PresetManager('mixerbeeMixedPresets', {
        loadSelect: document.getElementById('load-preset-select'),
        saveBtn: document.getElementById('save-preset-btn'),
        deleteBtn: document.getElementById('delete-preset-btn'),
        importBtn: document.getElementById('import-preset-btn'),
        exportBtn: document.getElementById('export-preset-btn')
    });

    // --- AUTOSAVE LOGIC ---
    const autosave = () => {
        const blocksData = getBlocksDataFromUI();
        mixedPresetManager.presets['__autosave__'] = blocksData;
        mixedPresetManager.savePresets();
        // console.log("Autosaved state.");
    };
    const debouncedAutosave = debounce(autosave, 2000);

    async function checkAiConfig() {
        try {
            const response = await fetch('api/config_status');
            const config = await response.json();
            if (config.is_ai_configured) {
                aiGeneratorContainer.style.display = 'block';
            } else {
                aiGeneratorContainer.style.display = 'none';
            }
        } catch (e) {
            console.error("Could not check AI config status, hiding feature.", e);
            aiGeneratorContainer.style.display = 'none';
        }
    }

    function checkPlaceholderVisibility() {
        const blockCount = blocksContainer.querySelectorAll('.mixed-block').length;
        if (placeholder) {
            placeholder.style.display = blockCount === 0 ? 'block' : 'none';
        }
    }
    
    collectionCb.addEventListener('change', () => {
        generateBtn.textContent = collectionCb.checked ? 'Build Collection' : 'Build Playlist';
    });

    new Sortable(blocksContainer, {
        animation: 150,
        handle: '.drag-handle',
        ghostClass: 'sortable-ghost',
        onEnd: debouncedAutosave, // Trigger save on reorder
    });

    mixedPresetManager.init(getBlocksDataFromUI, (presetData) => {
        applyPresetToUI(presetData, blocksContainer, debouncedAutosave);
        checkPlaceholderVisibility();
    });

    generateWithAiBtn.addEventListener('click', async (event) => {
        const prompt = aiPromptInput.value;
        if (!prompt.trim()) {
            alert('Please enter a prompt for the AI.');
            return;
        }

        try {
            const loadingOverlay = document.getElementById('loading-overlay');
            loadingOverlay.style.display = 'flex';
            generateWithAiBtn.disabled = true;

            const response = await fetch('api/create_from_text', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ prompt: prompt })
            });

            const result = await response.json();

            if (response.ok && result.status === 'ok') {
                applyPresetToUI(result.blocks, blocksContainer, debouncedAutosave);
                checkPlaceholderVisibility();
                debouncedAutosave();
            } else {
                alert('Error from AI: ' + (result.detail || 'Could not generate playlist.'));
            }
        } catch (error) {
            console.error("Error generating with AI:", error);
            alert('An unexpected error occurred while communicating with the AI.');
        } finally {
            const loadingOverlay = document.getElementById('loading-overlay');
            loadingOverlay.style.display = 'none';
            generateWithAiBtn.disabled = false;
        }
    });

    document.getElementById('add-tv-block-btn').addEventListener('click', () => {
        const blockElement = renderTvBlock(null, debouncedAutosave);
        blocksContainer.appendChild(blockElement);
        addBlockEventListeners(blockElement, debouncedAutosave);
        checkPlaceholderVisibility();
        debouncedAutosave();
    });
    document.getElementById('add-movie-block-btn').addEventListener('click', () => {
        const blockElement = renderMovieBlock();
        blocksContainer.appendChild(blockElement);
        addBlockEventListeners(blockElement, debouncedAutosave);
        checkPlaceholderVisibility();
        updateMovieBlockPreviewCount(blockElement);
        debouncedAutosave();
    });
    document.getElementById('clear-all-blocks-btn').addEventListener('click', () => {
        if (confirm('Are you sure you want to clear all blocks? This cannot be undone.')) {
            blocksContainer.querySelectorAll('.mixed-block').forEach(el => el.remove());
            checkPlaceholderVisibility();
            autosave(); // Save the cleared state immediately
        }
    });

    blocksContainer.addEventListener('input', (event) => {
        debouncedAutosave();
        const movieBlock = event.target.closest('.mixed-block[data-type="movie"]');
        if (movieBlock) {
            moviePreviewDebouncer(movieBlock);
        }
    });

    blocksContainer.addEventListener('click', (event) => {
        const target = event.target;
        if (target.classList.contains('delete-block-btn')) {
            target.closest('.mixed-block')?.remove();
            checkPlaceholderVisibility();
            debouncedAutosave();
        }
        if (target.classList.contains('add-show-row-btn')) {
            const showsContainer = target.closest('.mixed-block-body').querySelector('.tv-block-shows');
            const newRow = createTvShowRow({
                seriesData: seriesData,
                userSelectElement: userSelectElement,
                changeCallback: debouncedAutosave
            });
            showsContainer.appendChild(newRow);
            debouncedAutosave();
        }
    });

    blocksContainer.addEventListener('delete-row', (event) => {
        const row = event.target;
        const block = row.closest('.mixed-block');
        if (block.querySelectorAll('.show-row').length > 1) {
            row.remove();
            debouncedAutosave();
        }
    });

    generateBtn.addEventListener('click', (event) => {
        const blocks = getBlocksDataFromUI();
        const createAsCollection = collectionCb.checked;

        if (createAsCollection) {
            if (blocks.length !== 1 || blocks[0].type !== 'movie') {
                alert('Collections can only be created from a single Movie Block.');
                return;
            }
        } else {
            if (blocks.length === 0) {
                alert('Please add at least one block to build a playlist.');
                return;
            }
        }
        
        const requestBody = {
            user_id: userSelectElement.value,
            playlist_name: document.getElementById('action-bar-playlist-name').value,
            blocks: blocks,
            create_as_collection: createAsCollection
        };
        post('api/create_mixed_playlist', requestBody, event);
    });

    // --- Smart Playlist Button Logic ---
    document.getElementById('pilot-sampler-btn').addEventListener('click', (event) => {
        const clickedButton = event.currentTarget;
        smartPlaylistModal.show({
            title: 'Pilot Sampler',
            description: 'This will create a playlist with random, unwatched pilot episodes from your library.',
            countLabel: 'Number of Pilots',
            defaultCount: 10,
            defaultName: 'Pilot Sampler',
            onCreate: ({ playlistName, count }) => {
                post('api/create_pilot_sampler', {
                    user_id: userSelectElement.value,
                    playlist_name: playlistName,
                    count: count
                }, clickedButton);
            }
        });
    });

    document.getElementById('continue-watching-btn').addEventListener('click', (event) => {
        const clickedButton = event.currentTarget;
        smartPlaylistModal.show({
            title: 'Continue Watching',
            description: 'This will create a playlist with the next unwatched episode from your most recent in-progress shows.',
            countLabel: 'Number of Shows',
            defaultCount: 10,
            defaultName: 'Continue Watching',
            onCreate: ({ playlistName, count }) => {
                post('api/create_continue_watching_playlist', {
                    user_id: userSelectElement.value,
                    playlist_name: playlistName,
                    count: count
                }, clickedButton);
            }
        });
    });

    document.getElementById('forgotten-favorites-btn').addEventListener('click', (event) => {
        const clickedButton = event.currentTarget;
        smartPlaylistModal.show({
            title: 'From the Vault',
            description: 'This will create a playlist of favorited movies you haven\'t seen in a while.',
            countLabel: 'Number of Movies',
            defaultCount: 20,
            defaultName: 'From the Vault',
            onCreate: ({ playlistName, count }) => {
                post('api/create_forgotten_favorites', {
                    user_id: userSelectElement.value,
                    playlist_name: playlistName,
                    count: count
                }, clickedButton);
            }
        });
    });

    document.getElementById('random-genre-marathon-btn').addEventListener('click', (event) => {
        const clickedButton = event.currentTarget;
        if (!genreData || genreData.length === 0) {
            alert("Movie genres haven't been loaded yet. Please try again in a moment.");
            return;
        }

        const randomGenre = genreData[Math.floor(Math.random() * genreData.length)];
        const genreName = randomGenre.Name;

        smartPlaylistModal.show({
            title: `${genreName} Marathon`,
            description: `This will create a playlist of random, unwatched ${genreName} movies from your library.`,
            countLabel: 'Number of Movies',
            defaultCount: 5,
            defaultName: `${genreName} Marathon`,
            onCreate: ({ playlistName, count }) => {
                post('api/create_movie_marathon', {
                    user_id: userSelectElement.value,
                    playlist_name: playlistName,
                    genre: genreName,
                    count: count,
                }, clickedButton);
            }
        });
    });

    // --- INITIAL LOAD ---
    const autosavedState = mixedPresetManager.presets['__autosave__'];
    if (autosavedState && autosavedState.length > 0) {
        console.log("Found autosaved state, restoring...");
        applyPresetToUI(autosavedState, blocksContainer, debouncedAutosave);
    }

    checkPlaceholderVisibility();
    checkAiConfig();
}
