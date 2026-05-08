// static/js/app.js

import { toast, post } from './utils.js';
import { initModals, confirmModal, toastHistoryModal, smartPlaylistModal, smartBuildModal, previewModal, resetWatchModal, importAction, presetModal } from './modals.js';
import { mixerStore } from './mixerStore.js';
import { presetStore } from './presetStore.js';
import { settingsStore } from './settingsStore.js';
import { schedulerStore } from './schedulerStore.js';
import { managerStore } from './managerStore.js';
import { uiStore } from './uiStore.js';

let isAppInitialized = false;

const hydrateStores = () => {
    if (typeof Alpine === 'undefined') return;

    Object.assign(Alpine.store('mixer'), mixerStore);
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
    Alpine.store('presets').init();
};

async function initializeApp() {
    if (isAppInitialized) return;
    isAppInitialized = true;

    const loadingOverlay = document.getElementById('loading-overlay');
    try {
        const body = document.body;
        const toastBadge = document.getElementById('toast-badge');

        hydrateStores();

        const sStore = Alpine.store('settings');
        body.dataset.theme = sStore.theme;

        if (loadingOverlay) loadingOverlay.classList.remove('hidden');

        document.addEventListener('toast-added', () => {
            const modals = Alpine.store('modals');
            if (modals.history && !modals.history.isOpen) {
                const currentCount = parseInt(toastBadge.textContent || '0', 10);
                toastBadge.textContent = currentCount + 1;
                toastBadge.classList.remove('hidden');
            }
        });

        document.addEventListener('toast-cleared', () => {
            if (toastBadge) {
                toastBadge.textContent = '0';
                toastBadge.classList.add('hidden');
            }
        });

        try {
            const config = await post('api/config_status', null, null, 'GET', true);
            if (!config || config.status === 'error') throw new Error(config?.detail || "Backend failure.");

            Object.assign(sStore, {
                version: config.version || '',
                server_type: config.server_type || 'emby',
                ai_provider: config.ai_provider || 'gemini',
                ollama_model: config.ollama_model || '',
                is_ai_configured: !!config.is_ai_configured,
                starred_models: config.starred_models || [],
                vector_space: config.vector_space || 'cosine'
            });

            if (!config.is_configured) return;

            const [defUser, libraryData] = await Promise.all([
                post('api/default_user', null, null, 'GET', true),
                post('api/library_data', null, null, 'GET', true)
            ]);

            sStore.activeUserId = defUser.id;
            sStore.activeUserName = defUser.name;
            localStorage.setItem('mixerbeeGlobalState', JSON.stringify({ userId: defUser.id }));

            Object.assign(Alpine.store('mixer').library, libraryData);
            await Alpine.store('presets').refresh();

        } catch (err) {
            console.error("Initialization Error:", err.message);
            toast('Initialization error. Check settings.', false);
        }
    } finally {
        if (loadingOverlay) loadingOverlay.classList.add('hidden');
    }
}

const bootstrap = () => {
    if (sessionStorage.getItem('isReloading') === 'true') {
        const poll = setInterval(() => {
            fetch('api/config_status').then(r => {
                if (r.ok) {
                    clearInterval(poll);
                    sessionStorage.removeItem('isReloading');
                    setTimeout(initializeApp, 250);
                }
            }).catch(() => {});
        }, 1500);
    } else {
        initializeApp();
    }
};

if (typeof Alpine !== 'undefined') bootstrap();
else document.addEventListener('alpine:init', bootstrap);