// static/js/app.js

import { toast, post } from './utils.js';
import { initModals, confirmModal, toastHistoryModal, smartPlaylistModal, smartBuildModal, previewModal, resetWatchModal } from './modals.js';
import { mixerStore } from './mixerStore.js';
import { presetStore } from './presetStore.js';
import { settingsStore } from './settingsStore.js';
import { schedulerStore } from './schedulerStore.js';
import { managerStore } from './managerStore.js';

const hydrateStores = () => {
    if (typeof Alpine === 'undefined') return;

    Object.assign(Alpine.store('mixer'), mixerStore);
    Object.assign(Alpine.store('presets'), presetStore);
    Object.assign(Alpine.store('settings'), settingsStore);
    Object.assign(Alpine.store('scheduler'), schedulerStore);
    Object.assign(Alpine.store('manager'), managerStore);

    const modalStore = Alpine.store('modals');
    modalStore.confirm = confirmModal;
    modalStore.playlist = smartPlaylistModal;
    modalStore.smartBuild = smartBuildModal;
    modalStore.preview = previewModal;
    modalStore.resetWatch = resetWatchModal;
    modalStore.history = toastHistoryModal;

    Alpine.store('mixer').init();
    Alpine.store('presets').init();
};

async function initializeApp() {
    const loadingOverlay = document.getElementById('loading-overlay');
    try {
        const userSel = document.getElementById('user-select');
        const themeToggle = document.getElementById('theme-toggle-cb');
        const body = document.body;
        const activeUserDisplay = document.getElementById('active-user-display');
        const mainContent = document.getElementById('main-content-area');
        const notConfiguredWarning = document.getElementById('not-configured-warning');
        const mainActionBar = document.getElementById('action-bar');
        const allPanes = document.querySelectorAll('.tab-pane');
        const allTabBtns = document.querySelectorAll('.tab-btn');

        initModals();
        hydrateStores();

        const applyTheme = (theme) => {
            body.dataset.theme = theme;
            localStorage.setItem('mixerbeeTheme', theme);
            themeToggle.checked = (theme === 'light');
        };

        const saveGlobalState = () => {
            if (!userSel.value) return;
            localStorage.setItem('mixerbeeGlobalState', JSON.stringify({ userId: userSel.value }));
        };

        const switchTab = (activeTab) => {
            const activeBtn = document.getElementById(`${activeTab}-tab-btn`);
            const activePane = document.getElementById(`${activeTab}-pane`);

            if (activeTab === 'scheduler') Alpine.store('scheduler').loadSchedule();
            else if (activeTab === 'manager') Alpine.store('manager').load();

            allTabBtns.forEach(b => b.classList.remove('active'));
            allPanes.forEach(p => {
                p.classList.remove('active');
                p.classList.add('hidden');
            });

            if (activeBtn) activeBtn.classList.add('active');
            if (activePane) {
                activePane.classList.add('active');
                activePane.classList.remove('hidden');
            }

            mainActionBar.classList.toggle('hidden', activeTab !== 'mixed');
        };

        applyTheme(localStorage.getItem('mixerbeeTheme') || 'dark');
        if (loadingOverlay) loadingOverlay.classList.remove('hidden');

        document.getElementById('mixed-tab-btn').addEventListener('click', () => switchTab('mixed'));
        document.getElementById('scheduler-tab-btn').addEventListener('click', () => switchTab('scheduler'));
        document.getElementById('manager-tab-btn').addEventListener('click', () => switchTab('manager'));
        themeToggle.addEventListener('change', () => applyTheme(themeToggle.checked ? 'light' : 'dark'));

        userSel.addEventListener('input', () => {
            saveGlobalState();
            const currentTab = document.querySelector('.tab-btn.active')?.id.split('-')[0];
            if (currentTab === 'manager') Alpine.store('manager').load();
            if (currentTab === 'scheduler') Alpine.store('scheduler').loadSchedule();
        });

        const historyBtn = document.getElementById('toast-history-btn');
        const toastBadge = document.getElementById('toast-badge');
        historyBtn.addEventListener('click', () => {
            Alpine.store('modals').history.show();
            toastBadge.classList.add('hidden');
            toastBadge.textContent = '0';
        });

        document.addEventListener('toast-added', () => {
            const modals = Alpine.store('modals');
            if (modals.history && modals.history.overlay.classList.contains('hidden')) {
                const currentCount = parseInt(toastBadge.textContent || '0', 10);
                toastBadge.textContent = currentCount + 1;
                toastBadge.classList.remove('hidden');
            }
        });

        try {
            const config = await post('api/config_status', null, null, 'GET', true);
            
            if (!config || config.status === 'error') {
                throw new Error(config?.detail || "Failed to contact backend.");
            }

            const sStore = Alpine.store('settings');
            sStore.version = config.version || '';
            sStore.server_type = config.server_type || 'emby';
            sStore.ai_provider = config.ai_provider || 'gemini';
            sStore.ollama_model = config.ollama_model || '';
            sStore.is_ai_configured = !!config.is_ai_configured;

            if (!config.is_configured) {
                notConfiguredWarning.classList.remove('hidden');
                mainContent.classList.add('hidden');
                return;
            }

            notConfiguredWarning.classList.add('hidden');
            mainContent.classList.remove('hidden');

            const [defUser, libraryData] = await Promise.all([
                post('api/default_user', null, null, 'GET', true),
                post('api/library_data', null, null, 'GET', true)
            ]);

            activeUserDisplay.textContent = defUser.name;
            userSel.innerHTML = '';
            const userOption = document.createElement('option');
            userOption.value = defUser.id;
            userOption.textContent = defUser.name;
            userSel.appendChild(userOption);
            userSel.value = defUser.id;
            saveGlobalState();

            const mStore = Alpine.store('mixer');
            Object.assign(mStore.library, libraryData);

            await Alpine.store('presets').refresh();

            switchTab('mixed');

        } catch (err) {
            console.error("Initialization Error:", err.message);
            toast('Initialization error. Check settings.', false);
            notConfiguredWarning.classList.remove('hidden');
            mainContent.classList.add('hidden');
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

if (typeof Alpine !== 'undefined') {
    bootstrap();
} else {
    document.addEventListener('alpine:init', bootstrap);
}
