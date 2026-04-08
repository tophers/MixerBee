// static/js/builderState.js

import { toast } from './utils.js';

export const appState = {
    seriesData: [],
    movieGenreData: [],
    libraryData: [],
    artistData: [],
    musicGenreData: [],
};

const AUTOSAVE_KEY = 'mixerbee_autosave';

let builderState = {
    blocks: [],
    scheduler: null
};

try {
    const saved = localStorage.getItem(AUTOSAVE_KEY);
    if (saved) {
        const parsed = JSON.parse(saved);
        builderState.blocks = parsed.blocks || [];
        builderState.scheduler = parsed.scheduler || null;
    }
} catch(e) {}

export function getBuilderState() { return builderState; }
export function getBlocks() { return builderState.blocks; }
export function setBlocks(newBlocks) { builderState.blocks = newBlocks; }

export function getSchedulerAutosave() {
    return builderState.scheduler;
}

export function setSchedulerAutosave(data) {
    builderState.scheduler = data;
    saveBuilderState();
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

export const saveBuilderState = () => {
    const hasBlocks = builderState.blocks && builderState.blocks.length > 0;
    const hasScheduler = builderState.scheduler && Object.keys(builderState.scheduler).length > 0;
    
    if (hasBlocks || hasScheduler) {
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
                    const series = appState.seriesData.find(s => s.name === show.name);
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
        
        await hydratePresetData(blocksData, userSelectElement);

        setBlocks(blocksData);

    } catch (e) {
        toast("Could not apply preset data.", false);
    } finally {
        if (loadingOverlay) loadingOverlay.classList.add('hidden');
    }
};

export function restoreSessionFromAutosave() {
    return builderState.blocks;
}

export function clearAutosave() {
    builderState = { blocks: [], scheduler: null };
    localStorage.removeItem(AUTOSAVE_KEY);
}