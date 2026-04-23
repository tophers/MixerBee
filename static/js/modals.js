// static/js/modals.js

import { toast, toastHistory } from './utils.js';

const createModalLogic = (storeName) => {
    return {
        show(data = {}) {
            const store = Alpine.store('modals')[storeName];

            const payload = Array.isArray(data) ? { items: data } : data;

            Object.assign(store, payload, { isOpen: true });

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
    Alpine.store('modals', {
        confirm: { isOpen: false, title: '', text: '', confirmText: 'Confirm', isDanger: false },
        preset: { isOpen: false, name: '', existingNames: [] },
        playlist: { isOpen: false, title: '', description: '', playlistName: '', count: 10, countInput: true },
        import: { isOpen: false, code: '', name: '' },
        smartBuild: { isOpen: false, items: [] },
        preview: { isOpen: false, items: [], title: 'Playlist Preview' },
        resetWatch: { isOpen: false, showName: '', season: '' },
        history: { isOpen: false, toastHistory: [] },
        ollamaModels: { isOpen: false }
    });
    
    Alpine.store('modals').ollamaAction = ollamaModelsModal;
}