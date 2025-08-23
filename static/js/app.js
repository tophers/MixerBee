// static/js/app.js
import { post, toast } from './utils.js';
import { initModals } from './modals.js';
import { initBuilderPane } from './builder.js';
import { initSchedulerPane, loadSchedulerData } from './scheduler.js';
import { initManager, loadManagerData } from './manager.js';

window.appState = {
    seriesData: [],
    movieGenreData: [],
    libraryData: [],
    artistData: [],
    musicGenreData: [],
    builderState: { blocks: [] },
};

const CACHE_KEY = 'mixerbee_api_cache';

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
    const showModal = () => settingsModal.classList.remove('hidden');
    const hideModal = () => settingsModal.classList.add('hidden');
    settingsBtn.addEventListener('click', showModal);
    if (notConfiguredBtn) { notConfiguredBtn.addEventListener('click', showModal); }
    closeBtn.addEventListener('click', hideModal);
    if(cancelBtn) { cancelBtn.addEventListener('click', hideModal); }
    testBtn.addEventListener('click', (event) => { post('api/settings/test', {}, event).then(res => { toast(res.log.join(' '), res.status === 'ok'); }); });
    saveBtn.addEventListener('click', (event) => {
        const payload = { server_type: serverTypeSelect.value, emby_url: urlInput.value.trim(), emby_user: userInput.value.trim(), emby_pass: passInput.value, gemini_key: geminiInput.value.trim() };
        if (!payload.emby_url || !payload.emby_user || !payload.emby_pass) { toast('URL, Username, and Password are required.', false); return; }
        post('api/settings', payload, event).then(res => { if (res.status === 'ok') { hideModal(); sessionStorage.removeItem(CACHE_KEY); toast(res.log.join(' '), true); setTimeout(() => window.location.reload(), 1500); } });
    });
}

document.addEventListener('DOMContentLoaded', async () => {
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

    // FIX: This function is now async to handle the await below
    const initializeBaseUI = async (defUser) => {
        activeUserDisplay.textContent = defUser.name;
        userSel.innerHTML = '';
        const userOption = document.createElement('option');
        userOption.value = defUser.id;
        userOption.textContent = defUser.name;
        userSel.appendChild(userOption);
        userSel.value = defUser.id;
        saveGlobalState();
        // FIX: We now await the builder initialization to ensure restore logic finishes.
        await initBuilderPane(userSel);
    };

    initModals();
    initSettingsModal();
    applyTheme(localStorage.getItem('mixerbeeTheme') || 'dark');

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
        if (!config.is_configured) throw new Error("Application is not configured.");
        const defUser = await apiFetch('api/default_user');

        notConfiguredWarning.classList.add('hidden');
        mainContent.classList.remove('hidden');

        const [seriesData, movieGenreData, libraryData, artistData, musicGenreData] = await Promise.all([
            apiFetch('api/shows'),
            apiFetch('api/movie_genres'),
            apiFetch('api/movie_libraries'),
            apiFetch('api/music/artists'),
            apiFetch('api/music/genres'),
        ]);

        Object.assign(window.appState, { seriesData, movieGenreData, libraryData, artistData, musicGenreData });
        
        // FIX: This call is now awaited.
        await initializeBaseUI(defUser);

        switchTab('mixed');

    } catch (err) {
        console.error("Initialization Error:", err.message);
        toast('Initialization error. Check settings or server status.', false);
        notConfiguredWarning.classList.remove('hidden');
        mainContent.classList.add('hidden');
        if (typeof window.featherReplace === 'function') window.featherReplace();
    }
});
