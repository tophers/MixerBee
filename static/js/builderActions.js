// static/js/builderActions.js

import { post, toast } from './utils.js';
import { confirmModal, smartPlaylistModal, smartBuildModal, previewModal } from './modals.js';
import { SMART_BUILD_TYPES } from './definitions.js';
import { getBlocks, pushBlock, setBlocks } from './builderState.js';

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

export function initBuilderActions(userSelectElement, applyDataToUI, renderBuilder) {
    const aiGeneratorContainer = document.getElementById('ai-generator-container');
    const aiPromptInput = document.getElementById('ai-prompt-input');
    const generateWithAiBtn = document.getElementById('generate-with-ai-btn');
    const generateBtn = document.getElementById('generate-mixed-playlist-btn');
    const previewBtn = document.getElementById('preview-playlist-btn');
    const collectionCb = document.getElementById('create-as-collection-cb');
    const smartBuildBtn = document.getElementById('smart-build-btn');
    const surpriseMeBtn = document.getElementById('surprise-me-btn');
    const buildModeSelect = document.getElementById('build-mode-select');
    const existingPlaylistSelect = document.getElementById('existing-playlist-select');
    const aiPromptClearBtn = document.getElementById('ai-prompt-clear-btn');

    // --- AI Generator ---
    aiPromptInput.addEventListener('input', () => aiPromptClearBtn.classList.toggle('hidden', !aiPromptInput.value));
    aiPromptClearBtn.addEventListener('click', () => {
        aiPromptInput.value = '';
        aiPromptClearBtn.classList.add('hidden');
        aiPromptInput.focus();
    });
    generateWithAiBtn.addEventListener('click', async () => {
        const prompt = aiPromptInput.value;
        if (!prompt.trim()) return toast('Please enter a prompt for the AI.', false);
        try {
            const response = await post('api/create_from_text', { prompt }, generateWithAiBtn);
            if (response.status === 'ok') {
                applyDataToUI(response.blocks, userSelectElement, renderBuilder);
            }
        } catch (e) {
            // post() handles its own errors
        }
    });

    // --- Surprise Me ---
    surpriseMeBtn.addEventListener('click', async (event) => {
        surpriseMeBtn.disabled = true;
        try {
            const response = await fetch('api/builder/random_block');
            if (!response.ok) {
                const err = await response.json();
                throw new Error(err.detail || 'Failed to generate a random block.');
            }
            const newBlock = await response.json();
            pushBlock(newBlock);
            renderBuilder(); // We need to re-render after pushing
            toast("A surprise block was added!", true);
        } catch (error) {
            toast(`Error: ${error.message}`, false);
        } finally {
            surpriseMeBtn.disabled = false;
        }
    });

    // --- Clear All ---
    document.getElementById('clear-all-blocks-btn').addEventListener('click', async () => {
        try {
            await confirmModal.show({ title: 'Clear All Blocks?', text: 'Are you sure?', confirmText: 'Clear All' });
            applyDataToUI([], userSelectElement, renderBuilder);
        } catch (err) { /* Cancelled */ }
    });

    // --- Preview Button ---
    previewBtn.addEventListener('click', async (event) => {
        const blocks = getBlocks();
        if (blocks.length === 0) return toast('Please add at least one block to preview.', false);
        try {
            const response = await post('api/builder/preview', { user_id: userSelectElement.value, blocks: blocks }, previewBtn);
            if(response.status === 'ok' && Array.isArray(response.data)) {
                 previewModal.show(response.data).catch(() => {});
            }
        } catch(e) { /* post handles errors */ }
    });

    // --- Build / Generate Button ---
    generateBtn.addEventListener('click', async (event) => {
        const blocks = getBlocks();
        if (blocks.length === 0) return toast('Please add at least one block.', false);
        const mode = buildModeSelect.value;
        const createAsCollection = collectionCb.checked;
        if (mode === 'add') {
            const playlistId = existingPlaylistSelect.value;
            if (!playlistId) return toast("Select a playlist to add to.", false);
            post(`api/playlists/${playlistId}/add-items`, { user_id: userSelectElement.value, blocks: blocks }, event);
        } else {
            if (createAsCollection && (blocks.length !== 1 || blocks[0].type !== 'movie')) {
                return toast('Collections can only be created from a single Movie Block.', false);
            }
            try {
                const { playlistName } = await smartPlaylistModal.show({
                    title: createAsCollection ? 'Name Your Collection' : 'Name Your Playlist',
                    description: 'Please provide a name to continue.', countInput: false,
                    defaultName: createAsCollection ? 'My Movie Collection' : 'My Mix',
                });
                post('api/create_mixed_playlist', { user_id: userSelectElement.value, playlist_name: playlistName, blocks: blocks, create_as_collection: createAsCollection }, event);
            } catch (err) { /* Cancelled */ }
        }
    });

    // --- Smart Build / Auto Playlists ---
    smartBuildBtn.addEventListener('click', async (event) => {
        try {
            const type = await smartBuildModal.show(SMART_BUILD_TYPES);
            await handleSmartBuildSelection(type, event.currentTarget);
        } catch (err) { console.log('Smart build cancelled.') }
    });
}