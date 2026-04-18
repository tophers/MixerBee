// static/js/app.js

import { toast } from './utils.js';
import { initModals, confirmModal, toastHistoryModal, smartPlaylistModal, smartBuildModal, previewModal, resetWatchModal } from './modals.js';
import { mixerStore } from './mixerStore.js';
import { settingsStore } from './settingsStore.js';
import { schedulerStore } from './schedulerStore.js';
import { managerStore } from './managerStore.js';

/** Merges module logic into the shells defined in _head.html */
const hydrateStores = () => {
    if (typeof Alpine === 'undefined') return;

    Object.assign(Alpine.store('mixer'), mixerStore);
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
            if (window.featherReplace) window.featherReplace();
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
            if (window.featherReplace) window.featherReplace();
        };

        const apiFetch = (url) => {
            const separator = url.includes('?') ? '&' : '?';
            return fetch(`${url}${separator}_cb=${new Date().getTime()}`, {
                cache: 'no-store'
            }).then(r => {
                if (!r.ok) throw new Error(`API call failed: ${r.status}`);
                return r.json();
            });
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
            const config = await apiFetch('api/config_status');
            const sStore = Alpine.store('settings');
            sStore.version = config.version || '';
            sStore.server_type = config.server_type || 'emby';
            
            // --- DEBUGGING LOGS ---
            console.log("📡 Backend Config Response:", config);
            sStore.is_ai_configured = !!config.is_ai_configured;
            console.log("🧠 Frontend Settings Store 'is_ai_configured' set to:", sStore.is_ai_configured);
            // ----------------------

            if (!config.is_configured) throw new Error("Not configured.");

            notConfiguredWarning.classList.add('hidden');
            mainContent.classList.remove('hidden');

            const [defUser, libraryData] = await Promise.all([
                apiFetch('api/default_user'),
                apiFetch('api/library_data')
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
            await mStore.refreshPresets();

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
