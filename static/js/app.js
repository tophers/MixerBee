// static/js/app.js

import { api } from './apiClient.js';
import { ensureUnlocked } from './accessGate.js';
import { toast } from './utils.js';
import { useApi } from './utils.js';
import { initModals, confirmModal, toastHistoryModal, smartPlaylistModal, smartBuildModal, previewModal, resetWatchModal, importAction, presetModal } from './modals.js';
import { mixerStore } from './mixerStore.js';
import { aiStore } from './aiStore.js';
import { presetStore } from './presetStore.js';
import { settingsStore } from './settingsStore.js';
import { schedulerStore } from './schedulerStore.js';
import { managerStore } from './managerStore.js';
import { uiStore } from './uiStore.js';

let isAppInitialized = false;

const hydrateStores = () => {
    if (typeof Alpine === 'undefined') return;

    Object.assign(Alpine.store('mixer'), mixerStore);
    Object.assign(Alpine.store('ai'), aiStore);
    Object.assign(Alpine.store('presets'), presetStore);
    Object.assign(Alpine.store('settings'), settingsStore);
    Object.assign(Alpine.store('scheduler'), schedulerStore);
    Object.assign(Alpine.store('manager'), managerStore);
    Object.assign(Alpine.store('ui'), uiStore);

    initModals();

    const modalStore = Alpine.store('modals');
    modalStore.confirmAction = confirmModal;
    modalStore.playlistAction = smartPlaylistModal;
    modalStore.smartBuildAction = smartBuildModal;
    modalStore.previewAction = previewModal;
    modalStore.resetWatchAction = resetWatchModal;
    modalStore.historyAction = toastHistoryModal;
    modalStore.importAction = importAction;
    modalStore.presetAction = presetModal;

    Alpine.store('mixer').init();
    Alpine.store('ai').init();
    Alpine.store('presets').init();
};

async function initializeApp() {
    if (isAppInitialized) return;
    isAppInitialized = true;

    const loadingOverlay = document.getElementById('loading-overlay');
    try {
        await ensureUnlocked();

        const body = document.body;
        const toastBadge = document.getElementById('toast-badge');

        hydrateStores();

        const sStore = Alpine.store('settings');
        body.dataset.theme = sStore.theme;

        if (loadingOverlay) loadingOverlay.classList.remove('hidden');

        document.addEventListener('toast-added', () => {
            const modals = Alpine.store('modals');
            if (modals.history && !modals.history.isOpen) {
                toastBadge.textContent = parseInt(toastBadge.textContent || '0', 10) + 1;
                toastBadge.classList.remove('hidden');
            }
        });

        document.addEventListener('toast-cleared', () => {
            if (toastBadge) {
                toastBadge.textContent = '0';
                toastBadge.classList.add('hidden');
            }
        });

        const config = await useApi(api.get('api/config_status'), null, true, false);
        if (!config || config.status === 'error') throw new Error(config?.error?.detail || "Backend failure.");

        Object.assign(sStore, {
            version: config.data?.version || '',
            server_type: config.data?.server_type || 'emby',
            ai_provider: config.data?.ai_provider || 'gemini',
            ollama_model: config.data?.ollama_model || '',
            is_ai_configured: !!config.data?.is_ai_configured,
            starred_models: config.data?.starred_models || [],
            vector_space: config.data?.vector_space || 'cosine',
            is_access_key_set: !!config.data?.access_key_set
        });

        if (!config.data?.is_configured) return;

        const [defUser, libraryData] = await Promise.all([
            useApi(api.get('api/default_user'), null, true, false),
            useApi(api.get('api/library_data'), null, true, false)
        ]);

        sStore.activeUserId = defUser.data?.id;
        sStore.activeUserName = defUser.data?.name;
        localStorage.setItem('mixerbeeGlobalState', JSON.stringify({ userId: defUser.data?.id }));

        Object.assign(Alpine.store('mixer').library, libraryData.data);
        await Alpine.store('presets').refresh();

    } catch (err) {
        console.error("Initialization Error:", err.message);
        toast('Initialization error. Check settings.', false);
    } finally {
        if (loadingOverlay) loadingOverlay.classList.add('hidden');
    }
}

const bootstrap = () => {
    if (sessionStorage.getItem('isReloading') === 'true') {
        const poll = setInterval(async () => {
            try {
                const r = await fetch('api/config_status');
                if (r.ok) {
                    clearInterval(poll);
                    sessionStorage.removeItem('isReloading');
                    setTimeout(initializeApp, 250);
                }
            } catch(e) {}
        }, 1500);
    } else {
        initializeApp();
    }
};

if (typeof Alpine !== 'undefined') bootstrap();
else document.addEventListener('alpine:init', bootstrap);
