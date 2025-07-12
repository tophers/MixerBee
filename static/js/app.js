// static/js/app.js
import { post, toast } from './utils.js';
import { initModals } from './modals.js';
import { initBuilderPane } from './builder.js';
import { initSchedulerPane } from './scheduler.js';
import { initManager } from './manager.js';

// Central store for application-wide data
export const appState = {
    seriesData: [],
    movieGenreData: [],
    libraryData: [],
    artistData: [],
    musicGenreData: [],
};

// Key for session storage cache
const CACHE_KEY = 'mixerbee_api_cache';

function initSettingsModal() {
    const settingsBtn = document.getElementById('settings-btn');
    const settingsModal = document.getElementById('settings-modal-overlay');
    const closeBtn = document.getElementById('settings-close-btn');
    const cancelBtn = document.getElementById('settings-cancel-btn');
    const saveBtn = document.getElementById('settings-save-btn');
    const testBtn = document.getElementById('settings-test-btn');
    const notConfiguredBtn = document.getElementById('not-configured-settings-btn');

    const serverTypeSelect = document.getElementById('settings-server-type-select');
    const urlInput = document.getElementById('settings-url-input');
    const userInput = document.getElementById('settings-user-input');
    const passInput = document.getElementById('settings-pass-input');
    const geminiInput = document.getElementById('settings-gemini-input');

    const showModal = () => settingsModal.style.display = 'flex';
    const hideModal = () => settingsModal.style.display = 'none';

    settingsBtn.addEventListener('click', showModal);
    notConfiguredBtn.addEventListener('click', showModal);
    closeBtn.addEventListener('click', hideModal);
    cancelBtn.addEventListener('click', hideModal);

    testBtn.addEventListener('click', (event) => {
        post('api/settings/test', {}, event).then(res => {
            toast(res.log.join(' '), res.status === 'ok');
        });
    });

    saveBtn.addEventListener('click', (event) => {
        const payload = {
            server_type: serverTypeSelect.value,
            emby_url: urlInput.value.trim(),
            emby_user: userInput.value.trim(),
            emby_pass: passInput.value,
            gemini_key: geminiInput.value.trim()
        };

        if (!payload.emby_url || !payload.emby_user || !payload.emby_pass) {
            toast('URL, Username, and Password are required.', false);
            return;
        }

        post('api/settings', payload, event).then(res => {
            if (res.status === 'ok') {
                hideModal();
                sessionStorage.removeItem(CACHE_KEY);
                toast(res.log.join(' '), true);
                setTimeout(() => {
                    window.location.reload();
                }, 1500);
            }
        });
    });
}


document.addEventListener('DOMContentLoaded', () => {

    // Initialize modals and settings first, as they are always needed.
    initModals();
    initSettingsModal();

    const userSel = document.getElementById('user-select');
    const themeToggle = document.getElementById('theme-toggle-cb');
    const body = document.body;
    const activeUserDisplay = document.getElementById('active-user-display');
    const mixedTabBtn = document.getElementById('mixed-tab-btn');
    const schedulerTabBtn = document.getElementById('scheduler-tab-btn');
    const managerTabBtn = document.getElementById('manager-tab-btn');
    const mainContent = document.getElementById('main-content-area');
    const notConfiguredWarning = document.getElementById('not-configured-warning');
    const mixedPane = document.getElementById('mixed-pane');
    const schedulerPane = document.getElementById('scheduler-pane');
    const managerPane = document.getElementById('manager-pane');
    const mainActionBar = document.getElementById('action-bar');

    let uiInitialized = false;

    const applyTheme = (theme) => {
        body.dataset.theme = theme;
        localStorage.setItem('mixerbeeTheme', theme);
        themeToggle.checked = (theme === 'light');
        if (typeof window.featherReplace === 'function') window.featherReplace();
    };

    const toggleTheme = () => {
        const newTheme = themeToggle.checked ? 'light' : 'dark';
        applyTheme(newTheme);
    };

    themeToggle.addEventListener('change', toggleTheme);

    function saveGlobalState() {
        if (!userSel.value) return;
        localStorage.setItem('mixerbeeGlobalState', JSON.stringify({ userId: userSel.value }));
    }

    function switchTab(activeTab) {
        [mixedTabBtn, schedulerTabBtn, managerTabBtn].forEach(b => b.classList.remove('active'));
        [mixedPane, schedulerPane, managerPane].forEach(p => p.classList.remove('active'));
        mainActionBar.style.display = 'none';

        if (activeTab === 'mixed') {
            mixedTabBtn.classList.add('active');
            mixedPane.classList.add('active');
            mainActionBar.style.display = 'flex';
        } else if (activeTab === 'scheduler') {
            schedulerTabBtn.classList.add('active');
            schedulerPane.classList.add('active');
        } else if (activeTab === 'manager') {
            managerTabBtn.classList.add('active');
            managerPane.classList.add('active');
            initManager();
        }

        mixedPane.style.display = (activeTab === 'mixed') ? 'block' : 'none';
        schedulerPane.style.display = (activeTab === 'scheduler') ? 'block' : 'none';
        managerPane.style.display = (activeTab === 'manager') ? 'block' : 'none';
        if (typeof window.featherReplace === 'function') window.featherReplace();
    }

    mixedTabBtn.addEventListener('click', () => switchTab('mixed'));
    schedulerTabBtn.addEventListener('click', () => switchTab('scheduler'));
    managerTabBtn.addEventListener('click', () => switchTab('manager'));
    userSel.addEventListener('input', () => {
        saveGlobalState();
        if (managerPane.classList.contains('active')) initManager();
    });

    const savedTheme = localStorage.getItem('mixerbeeTheme');
    applyTheme(savedTheme || 'dark');

    const apiFetch = (url) => fetch(url).then(r => {
        if (!r.ok) throw new Error(`API call to ${url} failed with status ${r.status}`);
        return r.json();
    });

    // START: Refactored initialization function
    function initializeUI(data, defUser) {
        if (uiInitialized) return;

        activeUserDisplay.textContent = defUser.name;
        userSel.innerHTML = '';
        const userOption = Object.assign(document.createElement('option'), {
            value: defUser.id,
            textContent: defUser.name
        });
        userSel.appendChild(userOption);
        userSel.value = defUser.id;
        saveGlobalState();

        Object.assign(appState, data);

        // This is the key change: The init functions are ONLY called here,
        // after we are 100% sure the app is configured and data is ready.
        initBuilderPane(userSel);
        initSchedulerPane();
        switchTab('mixed');
        
        if (typeof window.featherReplace === 'function') window.featherReplace();
        uiInitialized = true;
    }
    // END: Refactored initialization function

    fetch('api/config_status')
    .then(r => {
        if (!r.ok) throw new Error(`API error: ${r.status}`);
        return r.json();
    })
    .then(async config => {
        if (config.is_configured) {
            try {
                // We must successfully fetch the user before doing anything else
                const defUser = await apiFetch('api/default_user');
                
                // Now that we have a user, we can show the main content
                notConfiguredWarning.style.display = 'none';
                mainContent.style.display = 'block';

                const cachedData = sessionStorage.getItem(CACHE_KEY);

                if (cachedData) {
                    console.log("Loading UI from session cache...");
                    initializeUI(JSON.parse(cachedData), defUser);
                }

                console.log("Fetching fresh data from server...");
                const [seriesData, movieGenreData, libraryData, artistData, musicGenreData] = await Promise.all([
                    apiFetch('api/shows'),
                    apiFetch('api/movie_genres'),
                    apiFetch('api/movie_libraries'),
                    apiFetch('api/music/artists'),
                    apiFetch('api/music/genres'),
                ]);

                const freshData = { seriesData, movieGenreData, libraryData, artistData, musicGenreData };
                sessionStorage.setItem(CACHE_KEY, JSON.stringify(freshData));
                Object.assign(appState, freshData);

                if (!uiInitialized) {
                    console.log("Initializing UI with fresh data...");
                    initializeUI(freshData, defUser);
                }

            } catch (err) {
                // If any part of the configured path fails, we fall back to the unconfigured state.
                console.error("Initialization Error:", err);
                toast('Initialization error. Check settings or server status.', false);
                notConfiguredWarning.style.display = 'block';
                mainContent.style.display = 'none';
                if (typeof window.featherReplace === 'function') window.featherReplace();
            }
        } else {
            // This is the unconfigured path. We do nothing but ensure the warning is visible.
            notConfiguredWarning.style.display = 'block';
            mainContent.style.display = 'none';
            if (typeof window.featherReplace === 'function') window.featherReplace();
        }
    })
    .catch(err => {
        // This catches network errors etc. before we even know the config status.
        console.error("Failed to connect to MixerBee backend:", err);
        notConfiguredWarning.style.display = 'block';
        mainContent.style.display = 'none';
        if (typeof window.featherReplace === 'function') window.featherReplace();
    });
});
