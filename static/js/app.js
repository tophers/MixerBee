// static/js/app.js

import { post, toast } from './utils.js';
import { initModals, confirmModal } from './modals.js';
import { initBuilderPane, renderBuilder } from './builder.js';
import { initSchedulerPane, loadSchedulerData } from './scheduler.js';
import { initManager, loadManagerData } from './manager.js';
import { applyDataToUI, restoreSessionFromAutosave, clearAutosave } from './builderState.js';

window.appState = {
    seriesData: [],
    movieGenreData: [],
    libraryData: [],
    artistData: [],
    musicGenreData: [],
};

const AUTOSAVE_KEY = 'mixerbee_autosave';

function initSettingsModal() {
    const settingsBtn = document.getElementById('settings-btn');
    const settingsModal = document.getElementById('settings-modal-overlay');
    const closeBtn = settingsModal.querySelector('.js-modal-close');
    const cancelBtn = settingsModal.querySelector('.js-modal-cancel');
    const saveBtn = document.getElementById('settings-save-btn');
    const testBtn = document.getElementById('settings-test-btn');
    const notConfiguredBtn = document.getElementById('not-configured-settings-btn');
    const serverTypeSelect = document.getElementById('settings-server-type-select');
    const urlInput = document.getElementById('settings-url-input');
    const userInput = document.getElementById('settings-user-input');
    const passInput = document.getElementById('settings-pass-input');
    const geminiInput = document.getElementById('settings-gemini-input');
    const geminiRemoveBtn = document.getElementById('settings-gemini-remove-btn');

    const showModal = () => settingsModal.classList.remove('hidden');
    const hideModal = () => settingsModal.classList.add('hidden');

    settingsBtn.addEventListener('click', showModal);
    if (notConfiguredBtn) { notConfiguredBtn.addEventListener('click', showModal); }
    closeBtn.addEventListener('click', hideModal);
    if(cancelBtn) { cancelBtn.addEventListener('click', hideModal); }

    geminiRemoveBtn.addEventListener('click', () => {
        geminiInput.value = '';
        toast('Gemini API key has been cleared. Click Save to finalize.', true);
    });

    testBtn.addEventListener('click', (event) => { post('api/settings/test', {}, event).then(res => { toast(res.log.join(' '), res.status === 'ok'); }); });

    saveBtn.addEventListener('click', (event) => {
        const payload = { server_type: serverTypeSelect.value, emby_url: urlInput.value.trim(), emby_user: userInput.value.trim(), emby_pass: passInput.value, gemini_key: geminiInput.value.trim() };
        if (!payload.emby_url || !payload.emby_user) { toast('URL and Username are required.', false); return; }

        post('api/settings', payload, event).then(res => {
            if (res.status === 'ok') {
                hideModal();
                sessionStorage.setItem('isReloading', 'true');
                toast("Settings saved! Server is restarting. The page will reload automatically...", true);
                // Give the toast time to appear before reloading.
                setTimeout(() => window.location.reload(), 500);
            }
        });
    });
}

async function handleEarlyRestorePrompt() {
    const savedData = localStorage.getItem(AUTOSAVE_KEY);
    if (!savedData) return 'none';

    try {
        const savedState = JSON.parse(savedData);
        const blocks = savedState.blocks;
        if (Array.isArray(blocks) && blocks.length > 0) {
            await confirmModal.show({
                title: 'Restore Previous Session?',
                text: 'We found some unsaved blocks from your last session. Would you like to restore them?',
                confirmText: 'Restore',
            });
            return 'restore';
        }
    } catch (e) {
        if (e.message.includes('Modal cancelled')) {
             return 'cancel';
        }
        console.error("Could not parse or prompt for autosaved data.", e);
        localStorage.removeItem(AUTOSAVE_KEY);
    }
    return 'none';
}

async function initializeApp() {
    const loadingOverlay = document.getElementById('loading-overlay');
    try {
        let isSchedulerInitialized = false;
        let isManagerInitialized = false;

        const userSel = document.getElementById('user-select');
        const themeToggle = document.getElementById('theme-toggle-cb');
        const body = document.body;
        const activeUserDisplay = document.getElementById('active-user-display');
        const mainContent = document.getElementById('main-content-area');
        const notConfiguredWarning = document.getElementById('not-configured-warning');
        const mainActionBar = document.getElementById('action-bar');
        const allPanes = document.querySelectorAll('.tab-pane');
        const allTabBtns = document.querySelectorAll('.tab-btn');

        const applyTheme = (theme) => {
            body.dataset.theme = theme;
            localStorage.setItem('mixerbeeTheme', theme);
            themeToggle.checked = (theme === 'light');
            if (typeof window.featherReplace === 'function') window.featherReplace();
        };

        const saveGlobalState = () => {
            if (!userSel.value) return;
            localStorage.setItem('mixerbeeGlobalState', JSON.stringify({ userId: userSel.value }));
        };

        const switchTab = (activeTab) => {
            const activeBtn = document.getElementById(`${activeTab}-tab-btn`);
            const activePane = document.getElementById(`${activeTab}-pane`);

            if (activeTab === 'scheduler' && !isSchedulerInitialized) {
                initSchedulerPane();
                isSchedulerInitialized = true;
            } else if (activeTab === 'manager' && !isManagerInitialized) {
                initManager();
                isManagerInitialized = true;
            }
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

            if (activeTab === 'scheduler') {
                loadSchedulerData();
            } else if (activeTab === 'manager') {
                loadManagerData();
            }

            if (typeof window.featherReplace === 'function') window.featherReplace();
        };

        const apiFetch = (url) => fetch(url).then(r => {
            if (!r.ok) throw new Error(`API call to ${url} failed with status ${r.status}`);
            return r.json();
        });

        const initializeBaseUI = (defUser, restoreDecision) => {
            activeUserDisplay.textContent = defUser.name;
            userSel.innerHTML = '';
            const userOption = document.createElement('option');
            userOption.value = defUser.id;
            userOption.textContent = defUser.name;
            userSel.appendChild(userOption);
            userSel.value = defUser.id;
            saveGlobalState();
            initBuilderPane(userSel, restoreDecision);
        };

        initModals();
        initSettingsModal();
        applyTheme(localStorage.getItem('mixerbeeTheme') || 'dark');

        const restoreDecision = await handleEarlyRestorePrompt();

        // This is the main page load spinner, show it now.
        if (loadingOverlay) loadingOverlay.classList.remove('hidden');

        document.getElementById('mixed-tab-btn').addEventListener('click', () => switchTab('mixed'));
        document.getElementById('scheduler-tab-btn').addEventListener('click', () => switchTab('scheduler'));
        document.getElementById('manager-tab-btn').addEventListener('click', () => switchTab('manager'));
        themeToggle.addEventListener('change', () => applyTheme(themeToggle.checked ? 'light' : 'dark'));
        userSel.addEventListener('input', () => {
            saveGlobalState();
            if (document.getElementById('manager-tab-btn').classList.contains('active')) loadManagerData();
            if (document.getElementById('scheduler-tab-btn').classList.contains('active')) loadSchedulerData();
        });

        try {
            const config = await apiFetch('api/config_status');
            if (!config.is_configured) {
                 throw new Error("Application is not configured.");
            }

            notConfiguredWarning.classList.add('hidden');
            mainContent.classList.remove('hidden');

            const [defUser, libraryData] = await Promise.all([
                apiFetch('api/default_user'),
                apiFetch('api/library_data')
            ]);

            Object.assign(window.appState, libraryData);

            initializeBaseUI(defUser, restoreDecision);

            switchTab('mixed');

        } catch (err) {
            console.error("Initialization Error:", err.message);
            toast('Initialization error. Check settings or server status.', false);
            notConfiguredWarning.classList.remove('hidden');
            mainContent.classList.add('hidden');
            if (typeof window.featherReplace === 'function') window.featherReplace();
        }
    } finally {
        if (loadingOverlay) loadingOverlay.classList.add('hidden');
    }
}


document.addEventListener('DOMContentLoaded', () => {
    if (sessionStorage.getItem('isReloading') === 'true') {
        const loadingOverlay = document.getElementById('loading-overlay');
        loadingOverlay.classList.remove('hidden');
        toast("Connecting to server after restart...", true);

        const pollForServerReady = () => {
            const intervalId = setInterval(() => {
                fetch('api/config_status')
                    .then(response => {
                        if (response.ok) {
                            clearInterval(intervalId);
                            sessionStorage.removeItem('isReloading');
                            setTimeout(initializeApp, 250);
                        }
                    })
                    .catch(() => {
                    });
            }, 1500);
        };
        pollForServerReady();
    } else {
        initializeApp();
    }
});
