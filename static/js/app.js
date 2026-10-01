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
import { assistStore } from './assistStore.js';
import { logStore } from './logStore.js';
import { initA11y } from './a11y.js';
import { initShortcuts, SHORTCUTS } from './shortcuts.js';

let isAppInitialized = false;
let storesHydrated = false;

const safeMergeStore = (target, source) => {
    if (!target || !source) return;
    const rawTarget = target.__v_raw || (typeof Alpine !== 'undefined' && Alpine.raw ? Alpine.raw(target) : target);
    const descriptors = Object.getOwnPropertyDescriptors(source);
    for (const [key, descriptor] of Object.entries(descriptors)) {
        if (descriptor.get || descriptor.set) {
            try {
                Object.defineProperty(rawTarget, key, descriptor);
            } catch (e) {}
        } else if (
            target[key] &&
            typeof target[key] === 'object' &&
            !Array.isArray(target[key]) &&
            !(target[key] instanceof Set) &&
            descriptor.value &&
            typeof descriptor.value === 'object' &&
            !Array.isArray(descriptor.value) &&
            !(descriptor.value instanceof Set)
        ) {
            try {
                Object.assign(target[key], descriptor.value);
            } catch (e) {
                target[key] = descriptor.value;
            }
        } else {
            try {
                target[key] = descriptor.value;
            } catch (e) {
                try {
                    Object.defineProperty(rawTarget, key, descriptor);
                } catch (e2) {}
            }
        }
    }
};

export const hydrateStores = () => {
    if (typeof Alpine === 'undefined') return;
    if (storesHydrated) return;
    storesHydrated = true;

    safeMergeStore(Alpine.store('mixer'), mixerStore);
    safeMergeStore(Alpine.store('ai'), aiStore);
    safeMergeStore(Alpine.store('presets'), presetStore);
    safeMergeStore(Alpine.store('settings'), settingsStore);
    safeMergeStore(Alpine.store('scheduler'), schedulerStore);
    safeMergeStore(Alpine.store('manager'), managerStore);
    safeMergeStore(Alpine.store('ui'), uiStore);
    safeMergeStore(Alpine.store('assist'), assistStore);
    safeMergeStore(Alpine.store('logs'), logStore);

    initModals();
    Alpine.store('modals').shortcuts.list = SHORTCUTS;

    Alpine.store('ai').init();
    Alpine.store('assist').init();
    Alpine.store('logs').init();
};

// Immediately hydrate real store references if Alpine is ready
if (typeof Alpine !== 'undefined') {
    hydrateStores();
} else {
    document.addEventListener('alpine:init', hydrateStores, { once: true });
}

async function initializeApp() {
    if (isAppInitialized) return;
    isAppInitialized = true;

    hydrateStores();

    const loadingOverlay = document.getElementById('loading-overlay');
    try {
        await ensureUnlocked();

        const body = document.body;
        const toastBadge = document.getElementById('toast-badge');

        const sStore = Alpine.store('settings');
        body.dataset.theme = sStore.theme;
        await sStore.initAccount();

        // Before the media-connection checks below, every one of which can return
        // early. The log viewer is installation-wide and is most useful precisely when
        // there is no working connection, so its availability must not depend on one.
        await Alpine.store('logs').refreshAvailability();
        // The backend stays authoritative for a tab left open in the background: verbose
        // logging turned on or off in another tab or browser shows up on the next focus.
        window.addEventListener('focus', () => Alpine.store('logs').refreshAvailability());

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
            is_configured: !!config.data?.is_configured,
            connection_unavailable: false,
            connection_error: '',
            server_type: config.data?.server_type || 'emby',
            ai_provider: config.data?.ai_provider || '',
            ollama_model: config.data?.ollama_model || '',
            starred_models: config.data?.starred_models || [],
            vector_space: config.data?.vector_space || 'cosine'
        });
        // Authoritative AI capability, applied before any AI store starts work.
        sStore.applyCapability(config.data);

        if (!config.data?.is_configured) return;

        const [defUser, libraryData] = await Promise.all([
            useApi(api.get('api/default_user'), null, true, false),
            useApi(api.get('api/library_data'), null, true, false)
        ]);

        if (defUser.status !== 'ok' || libraryData.status !== 'ok') {
            const failed = defUser.status !== 'ok' ? defUser : libraryData;
            sStore.connection_unavailable = true;
            sStore.connection_error = failed.error?.detail || 'MixerBee could not reach this media account. Check the server and saved credentials.';
            return;
        }

        sStore.activeUserId = defUser.data?.id;
        sStore.activeUserName = defUser.data?.name;
        sStore.can_manage_collections = !!defUser.data?.can_manage_collections;

        Object.assign(Alpine.store('mixer').library, libraryData.data);
        Alpine.store('mixer').init(defUser.data?.connection_id);
        await Alpine.store('presets').refresh();
        Alpine.store('ui').restoreTab();

        // The backend stays authoritative for a tab left open in the background: a
        // preference changed in another tab or another browser is picked up on focus,
        // and again whenever a request is refused on policy grounds.
        document.addEventListener('visibilitychange', () => {
            if (document.visibilityState === 'visible') sStore.refreshCapability();
        });
        document.addEventListener('mixerbee:policy-rejected', (event) => {
            if (event.detail?.reason === 'disabled_by_user' || event.detail?.reason === 'ai_not_configured') {
                sStore.refreshCapability();
            }
        });

    } catch (err) {
        console.error("Initialization Error:", err.message);
        toast('Initialization error. Check settings.', false);
    } finally {
        if (loadingOverlay) loadingOverlay.classList.add('hidden');
    }
}

let interactionInitialized = false;
const bootstrap = () => {
    if (!interactionInitialized) {
        interactionInitialized = true;
        initA11y();
        initShortcuts();
    }
    initializeApp();
};

if (typeof Alpine !== 'undefined') bootstrap();
else document.addEventListener('alpine:init', bootstrap);
