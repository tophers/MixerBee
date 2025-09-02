// Filename: static/js/builder.js

import { PresetManager } from './components.js';
import { renderTvBlock, renderMovieBlock, renderMusicBlock, updateAllBlockPreviews } from './block_renderers.js';
import { getBuilderState, getBlocks, setBlocks, saveBuilderState, applyDataToUI, spliceBlock, restoreSessionFromAutosave, clearAutosave } from './builderState.js';
import { initBuilderActions } from './builderActions.js';
import { attachBuilderEventListeners } from './builderEvents.js';

export function renderBuilder() {
    const blocksContainer = document.getElementById('mixed-playlist-blocks');
    const placeholder = blocksContainer.querySelector('.placeholder-text');
    const builderState = getBuilderState();

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
    const blocks = getBlocks();
    if (placeholder) {
        placeholder.classList.toggle('hidden', blocks.length > 0);
    }
}

async function checkAiConfig() {
    try {
        const response = await fetch('api/config_status');
        const config = await response.json();
        const aiGeneratorContainer = document.getElementById('ai-generator-container');
        aiGeneratorContainer.classList.toggle('hidden', !config.is_ai_configured);
    } catch (e) {
        console.error("Could not check AI config status, hiding feature.", e);
        aiGeneratorContainer.classList.add('hidden');
    }
}

export function initBuilderPane(userSelectElement, restoreDecision) {
    const blocksContainer = document.getElementById('mixed-playlist-blocks');
    const addBlockBtn = document.getElementById('add-block-btn');
    const addBlockMenu = document.getElementById('add-block-menu');
    const collectionCb = document.getElementById('create-as-collection-cb');
    const generateBtn = document.getElementById('generate-mixed-playlist-btn');
    const buildModeSelect = document.getElementById('build-mode-select');
    const existingPlaylistSelect = document.getElementById('existing-playlist-select');

    const applyPresetFn = (data) => applyDataToUI(data, userSelectElement);

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
        }
    };
    
    initBuilderActions(userSelectElement, async (data) => {
        await applyPresetFn(data);
        renderBuilder();
    }, renderBuilder);
    
    attachBuilderEventListeners(blocksContainer, userSelectElement, renderBuilder);
    
    new Sortable(blocksContainer, {
        animation: 150, handle: '.drag-handle', ghostClass: 'sortable-ghost',
        onEnd: (evt) => {
            if (evt.oldIndex === evt.newIndex) return;
            const blocks = getBlocks();
            const [movedItem] = blocks.splice(evt.oldIndex - 1, 1);
            blocks.splice(evt.newIndex - 1, 0, movedItem);
            renderBuilder();
        }
    });

    mixedPresetManager.init(getBlocks, applyPresetFn, renderBuilder);

    buildModeSelect.addEventListener('change', () => {
        const isInAddMode = buildModeSelect.value === 'add';
        existingPlaylistSelect.classList.toggle('hidden', !isInAddMode);
        if (isInAddMode && existingPlaylistSelect.options.length <= 1) {
            populatePlaylistsDropdown();
        }
    });
    
    collectionCb.addEventListener('change', () => {
        generateBtn.textContent = collectionCb.checked ? 'Build Collection' : 'Build';
        buildModeSelect.disabled = collectionCb.checked;
        if (collectionCb.checked) {
            buildModeSelect.value = 'create';
            buildModeSelect.dispatchEvent(new Event('change'));
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
            const defaultShowObject = { name: window.appState.seriesData[0]?.name || '', season: 1, episode: 1, unwatched: true };
            newBlockData = { type: 'tv', shows: [defaultShowObject], mode: 'count', count: 3, interleave: true };
        } else if (blockType === 'movie') {
            newBlockData = { type: 'movie', filters: { watched_status: 'unplayed', sort_by: 'Random', parent_ids: appState.libraryData.map(l => l.Id) } };
        } else if (blockType === 'music') {
            newBlockData = { type: 'music', music: { mode: 'album' } };
        }

        if (newBlockData) {
            const currentBlocks = getBlocks();
            setBlocks([...currentBlocks, newBlockData]);
            renderBuilder();
        }
        addBlockMenu.classList.add('hidden');
    });

    document.addEventListener('click', () => !addBlockMenu.classList.contains('hidden') && addBlockMenu.classList.add('hidden'));

    if (restoreDecision === 'restore') {
        const blocksToRestore = restoreSessionFromAutosave();
        if (blocksToRestore) {
            applyPresetFn(blocksToRestore).then(() => {
                renderBuilder();
            });
        }
    } else {
        clearAutosave();
        renderBuilder();
    }

    checkAiConfig();
    populatePlaylistsDropdown();
}