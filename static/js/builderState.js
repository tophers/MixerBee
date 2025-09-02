// static/js/builderState.js

import { toast } from './utils.js';

const AUTOSAVE_KEY = 'mixerbee_autosave';

let builderState = {
    blocks: []
};

// --- State Accessors and Mutators ---

export function getBuilderState() {
    return builderState;
}

export function getBlocks() {
    return builderState.blocks;
}

export function setBlocks(newBlocks) {
    builderState.blocks = newBlocks;
}

export function spliceBlock(index, deleteCount, newBlock) {
    if (newBlock) {
        builderState.blocks.splice(index, deleteCount, newBlock);
    } else {
        builderState.blocks.splice(index, deleteCount);
    }
}

export function pushBlock(newBlock) {
    builderState.blocks.push(newBlock);
}

// --- State Management Functions ---

export const saveBuilderState = () => {
    if (builderState.blocks.length > 0) {
        localStorage.setItem(AUTOSAVE_KEY, JSON.stringify(builderState));
    } else {
        localStorage.removeItem(AUTOSAVE_KEY);
    }
};

const hydratePresetData = async (blocksData, userSelectElement) => {
    const promises = [];
    (blocksData || []).forEach(block => {
        if (block.type === 'tv') {
            block.shows.forEach(show => {
                if (show.unwatched) {
                    const series = window.appState.seriesData.find(s => s.name === show.name);
                    if (series) {
                        const promise = fetch(`api/shows/${series.id}/first_unwatched?user_id=${userSelectElement.value}`)
                            .then(response => response.ok ? response.json() : null)
                            .then(ep => {
                                if (ep) {
                                    show.season = ep.ParentIndexNumber;
                                    show.episode = ep.IndexNumber;
                                }
                            });
                        promises.push(promise);
                    }
                }
            });
        }
    });
    await Promise.all(promises);
};

export const applyDataToUI = async (blocksData = [], userSelectElement) => {
    console.log("[STATE] applyDataToUI called with:", blocksData);
    const loadingOverlay = document.getElementById('loading-overlay');
    if (loadingOverlay) loadingOverlay.classList.remove('hidden');

    await new Promise(resolve => setTimeout(resolve, 10));

    try {
        (blocksData || []).forEach(blockData => {
            if (blockData.type === 'movie' && blockData.filters?.genres && !blockData.filters.genres_any) {
                blockData.filters.genres_any = blockData.filters.genres;
                delete blockData.filters.genres;
            }
        });
        
        console.log("[STATE] Hydrating data...");
        await hydratePresetData(blocksData, userSelectElement);
        console.log("[STATE] Hydration complete.");

        setBlocks(blocksData);
        console.log("[STATE] Internal state has been set to new blocks:", getBlocks());

    } catch (e) {
        console.error("Error applying preset data:", e);
        toast("Could not apply preset data.", false);
    } finally {
        if (loadingOverlay) loadingOverlay.classList.add('hidden');
        console.log("[STATE] applyDataToUI finished.");
    }
};

export function restoreSessionFromAutosave() {
    const savedData = localStorage.getItem(AUTOSAVE_KEY);
    if (savedData) {
        try {
            const savedState = JSON.parse(savedData);
            return savedState.blocks;
        } catch (e) {
            console.error("Failed to parse restored state.", e);
            localStorage.removeItem(AUTOSAVE_KEY);
        }
    }
    return null;
}

export function clearAutosave() {
    localStorage.removeItem(AUTOSAVE_KEY);
}