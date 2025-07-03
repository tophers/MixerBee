// static/js/builder.js
import { post, debounce, confirmModal } from './utils.js';
import { PresetManager, createTvShowRow } from './utils.js';
import { initQuickPlaylists } from './quick_playlists.js';
import { renderTvBlock, renderMovieBlock, renderMusicBlock } from './block_renderers.js';

function addBlockEventListeners(blockElement, changeCallback) {
    if (blockElement.dataset.type === 'tv') {
        const showsContainer = blockElement.querySelector('.tv-block-shows');
        new Sortable(showsContainer, {
            animation: 150,
            handle: '.drag-handle',
            ghostClass: 'sortable-ghost',
            onEnd: changeCallback
        });
    }
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
            blocksData.push({ type: 'tv', shows, count: blockEl.querySelector('.tv-block-count').value, interleave: blockEl.querySelector('.tv-block-interleave').checked });
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
                if (type === 'limit') filters.limit = parseInt(value, 10);
                else if (type === 'duration') filters.duration_minutes = parseInt(value, 10);
            }
            blocksData.push({ type: 'movie', filters: filters });
        } else if (blockType === 'music') {
            const mode = blockEl.querySelector('.music-block-mode').value;
            let musicData = { mode };
            if (mode === 'genre') {
                musicData.filters = {
                    genres: [...blockEl.querySelectorAll('.music-block-genre-cb:checked')].map(cb => cb.value),
                    genre_match: blockEl.querySelector(`input[name^="music-block-genre-match-"]:checked`).value,
                    sort_by: blockEl.querySelector('.music-block-sort-by').value,
                    limit: blockEl.querySelector('.music-block-limit').value
                };
            } else {
                musicData.artistId = blockEl.querySelector('.music-block-artist').value;
                musicData.albumId = blockEl.querySelector('.music-block-album').value;
                musicData.count = blockEl.querySelector('.music-block-count').value;
            }
            blocksData.push({ type: 'music', music: musicData });
        }
    });
    return blocksData;
}

export function initBuilderPane(userSelectElement, allData) {
    const { seriesData, movieGenreData, libraryData, artistData, musicGenreData } = allData;
    const blocksContainer = document.getElementById('mixed-playlist-blocks');
    const placeholder = blocksContainer.querySelector('.placeholder-text');
    const aiGeneratorContainer = document.getElementById('ai-generator-container');
    const aiPromptInput = document.getElementById('ai-prompt-input');
    const generateWithAiBtn = document.getElementById('generate-with-ai-btn');
    const generateBtn = document.getElementById('generate-mixed-playlist-btn');
    const collectionCb = document.getElementById('create-as-collection-cb');
    const addBlockBtn = document.getElementById('add-block-btn');
    const addBlockMenu = document.getElementById('add-block-menu');

    const mixedPresetManager = new PresetManager('mixerbeeMixedPresets', {
        loadSelect: document.getElementById('load-preset-select'),
        saveBtn: document.getElementById('save-preset-btn'),
        deleteBtn: document.getElementById('delete-preset-btn'),
        importBtn: document.getElementById('import-preset-btn'),
        exportBtn: document.getElementById('export-preset-btn')
    });

    const autosave = () => {
        const blocksData = getBlocksDataFromUI();
        mixedPresetManager.presets['__autosave__'] = blocksData;
        mixedPresetManager.savePresets();
    };
    const debouncedAutosave = debounce(autosave, 2000);

    const applyPresetToUI = (blocksData) => {
        if (!blocksData) return;
        blocksContainer.innerHTML = ''; // Clear existing blocks
        blocksData.forEach(blockData => {
            let blockElement;
            const renderData = { data: blockData, userSelectElement, changeCallback: debouncedAutosave, ...allData };
            if (blockData.type === 'tv') blockElement = renderTvBlock(renderData);
            else if (blockData.type === 'movie') blockElement = renderMovieBlock(renderData);
            else if (blockData.type === 'music') blockElement = renderMusicBlock(renderData);
    
            if (blockElement) {
                blocksContainer.appendChild(blockElement);
                addBlockEventListeners(blockElement, debouncedAutosave);
            }
        });
        checkPlaceholderVisibility();
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

    function checkPlaceholderVisibility() {
        const blockCount = blocksContainer.querySelectorAll('.mixed-block').length;
        if (placeholder) placeholder.style.display = blockCount === 0 ? 'block' : 'none';
    }

    collectionCb.addEventListener('change', () => {
        generateBtn.textContent = collectionCb.checked ? 'Build Collection' : 'Build Playlist';
    });

    new Sortable(blocksContainer, { animation: 150, handle: '.drag-handle', ghostClass: 'sortable-ghost', onEnd: debouncedAutosave });

    mixedPresetManager.init(getBlocksDataFromUI, applyPresetToUI);

    generateWithAiBtn.addEventListener('click', async (event) => {
        const prompt = aiPromptInput.value;
        if (!prompt.trim()) return alert('Please enter a prompt for the AI.');
        try {
            document.getElementById('loading-overlay').style.display = 'flex';
            generateWithAiBtn.disabled = true;
            const response = await fetch('api/create_from_text', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ prompt: prompt })
            });
            const result = await response.json();
            if (response.ok && result.status === 'ok') {
                applyPresetToUI(result.blocks);
                debouncedAutosave();
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
        const renderData = { userSelectElement, changeCallback: debouncedAutosave, ...allData };

        if (blockType === 'tv') blockElement = renderTvBlock(renderData);
        else if (blockType === 'movie') blockElement = renderMovieBlock(renderData);
        else if (blockType === 'music') blockElement = renderMusicBlock(renderData);
        
        if (blockElement) {
            blocksContainer.appendChild(blockElement);
            addBlockEventListeners(blockElement, debouncedAutosave);
            checkPlaceholderVisibility();
            debouncedAutosave();
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
                blocksContainer.innerHTML = '';
                checkPlaceholderVisibility();
                autosave();
            }
        });
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
            const newRow = createTvShowRow({ rowData: {}, seriesData, userSelectElement, changeCallback: debouncedAutosave });
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
            if (blocks.length !== 1 || blocks[0].type !== 'movie') return alert('Collections can only be created from a single Movie Block.');
        } else {
            if (blocks.length === 0) return alert('Please add at least one block to build a playlist.');
        }
        const requestBody = { user_id: userSelectElement.value, playlist_name: document.getElementById('action-bar-playlist-name').value, blocks, create_as_collection: createAsCollection };
        post('api/create_mixed_playlist', requestBody, event);
    });

    // Initialize all the one-click playlist buttons
    initQuickPlaylists(userSelectElement, allData.movieGenreData, allData.musicGenreData);

    // --- INITIAL LOAD ---
    const autosavedState = mixedPresetManager.presets['__autosave__'];
    if (autosavedState && autosavedState.length > 0) {
        console.log("Found autosaved state, restoring...");
        applyPresetToUI(autosavedState);
    }

    checkPlaceholderVisibility();
    checkAiConfig();
}