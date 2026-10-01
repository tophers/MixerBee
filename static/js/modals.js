// static/js/modals.js

import { toast, toastHistory } from './utils.js';

const createModalLogic = (storeName) => {
    return {
        show(data = {}) {
            const store = Alpine.store('modals')[storeName];

            const payload = Array.isArray(data) ? { items: data } : data;

            Object.assign(store, payload, { isOpen: true });
            if (storeName === 'preview') store.removedCount = 0;

            return new Promise((resolve, reject) => {
                store._resolve = resolve;
                store._reject = reject;
            });
        },
        close(value, isCancel = false) {
            const store = Alpine.store('modals')[storeName];
            store.isOpen = false;
            if (isCancel) {
                if (store._reject) store._reject(new Error('Modal cancelled by user.'));
            } else {
                if (store._resolve) store._resolve(value);
            }
            store._resolve = null;
            store._reject = null;
        }
    };
};

export const confirmModal = createModalLogic('confirm');
export const presetModal = createModalLogic('preset');
export const smartPlaylistModal = createModalLogic('playlist');
export const importPresetModal = createModalLogic('import');
export const smartBuildModal = createModalLogic('smartBuild');
export const previewModal = createModalLogic('preview');
export const resetWatchModal = createModalLogic('resetWatch');
export const ollamaModelsModal = createModalLogic('ollamaModels');
export const aiTweaksModal = createModalLogic('aiTweaks');
export const recipeLibraryModal = createModalLogic('recipeLibrary');
export const saveRecipeModal = createModalLogic('saveRecipe');
export const mixRulesModal = createModalLogic('mixRules');
export const renamePresetModal = createModalLogic('renamePreset');
export const musicQuickBuildModal = createModalLogic('musicQuickBuild');
const aiHubBase = createModalLogic('aiHub');
// The hub edits the same saved AI fields as the Settings modal, but opens straight
// from the header pill. Settings' own opener is what loads those values, so without
// this the hub's inputs show constructor defaults and saving writes them over the
// stored configuration -- erasing the Gemini key and resetting the Ollama settings.
export const aiHubModal = {
    ...aiHubBase,
    async show(data = {}) {
        const settings = Alpine.store('settings');
        // Guarded here as well as in the templates: the hub holds the provider controls,
        // so a stale click must not reopen it once the account has opted out.
        if (settings?.ai_disabled) {
            toast('AI features are turned off for this account.', false);
            return;
        }
        if (settings && typeof settings.hydrate === 'function' && !settings.isHydrated) {
            await settings.hydrate();
        }
        return aiHubBase.show(data);
    }
};

export const toastHistoryModal = {
    show() {
        const store = Alpine.store('modals').history;
        store.toastHistory = [...toastHistory];
        store.isOpen = true;
    },
    close() { Alpine.store('modals').history.isOpen = false; },
    clear() {
        toastHistory.length = 0;
        Alpine.store('modals').history.toastHistory = [];
        document.dispatchEvent(new CustomEvent('toast-cleared'));
    }
};

export const importAction = {
    ...importPresetModal,
    performImport() {
        const store = Alpine.store('modals').import;
        const rawCode = store.code || '';
        const name = store.name || '';

        if (!rawCode.trim() || !name.trim()) {
            toast('Please provide both a share code and a new name.', false);
            return;
        }

        try {
            const lines = rawCode.split('\n').filter(line => line.trim() !== '');
            const base64String = lines.length > 0 ? lines[lines.length - 1] : '';
            if (!base64String) throw new Error("Could not find a valid code.");

            const binString = atob(base64String);
            const bytes = Uint8Array.from(binString, (c) => c.charCodeAt(0));
            const jsonString = new TextDecoder().decode(bytes);
            const payload = JSON.parse(jsonString);

            if (!payload.data || !Array.isArray(payload.data)) {
                throw new Error("Invalid format.");
            }

            this.close({ name, data: payload.data });
        } catch (e) {
            console.error("Import failed:", e);
            toast(`Invalid share code.`, false);
        }
    }
};

export function initModals() {
    let store = Alpine.store('modals');
    if (!store) {
        store = Alpine.store('modals', {});
    }

    const defaultData = {
        confirm: { isOpen: false, existingNames: [], title: '', text: '', confirmText: 'Confirm', isDanger: false },
        preset: { isOpen: false, name: '', existingNames: [] },
        playlist: { isOpen: false, title: '', description: '', playlistName: '', count: 10, countInput: true },
        import: { isOpen: false, code: '', name: '' },
        smartBuild: { isOpen: false, items: [] },
        preview: { isOpen: false, items: [], title: 'Playlist Preview', totalDuration: '', parentBlockUid: null, removedCount: 0 },
        resetWatch: { isOpen: false, showName: '', season: '' },
        history: { isOpen: false, toastHistory: [] },
        ollamaModels: { isOpen: false },
        aiTweaks: { isOpen: false },
        recipeLibrary: { isOpen: false, recipes: [], starters: [], filterQuery: '', activeTab: 'saved' },
        saveRecipe: { isOpen: false, name: '', description: '', tags: '', is_favorite: false, blockToSave: null },
        mixRules: { isOpen: false },
        renamePreset: { isOpen: false, presetId: '', oldName: '', newName: '' },
        aiHub: { isOpen: false },
        shortcuts: { isOpen: false, list: [] },
        musicQuickBuild: {
            isOpen: false,
            type: 'artist_spotlight',
            title: '',
            playlistName: '',
            count: 25,
            selectedArtistId: '',
            selectedGenre: '',
            selectedAlbumId: '',
            selectedAlbumName: '',
            albums: [],
            loadingAlbums: false
        }
    };

    for (const [key, val] of Object.entries(defaultData)) {
        if (!store[key]) {
            store[key] = val;
        } else {
            Object.assign(store[key], val);
        }
    }

    store.confirmAction = confirmModal;
    store.presetAction = presetModal;
    store.playlistAction = smartPlaylistModal;
    store.importAction = importAction;
    store.smartBuildAction = smartBuildModal;
    store.previewAction = previewModal;
    store.resetWatchAction = resetWatchModal;
    store.historyAction = toastHistoryModal;
    store.ollamaAction = ollamaModelsModal;
    store.aiTweaksAction = aiTweaksModal;
    store.aiHubAction = aiHubModal;
    store.recipeLibraryAction = recipeLibraryModal;
    store.saveRecipeAction = saveRecipeModal;
    store.mixRulesAction = mixRulesModal;
    store.renamePresetAction = renamePresetModal;
    store.musicQuickBuildAction = musicQuickBuildModal;
}