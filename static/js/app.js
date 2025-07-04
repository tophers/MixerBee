// static/js/app.js
import { post, toast, initModals } from './utils.js';
import { initBuilderPane } from './builder.js';
import { initSchedulerPane } from './scheduler.js';
import { initManager } from './manager.js';
import { initQuickPlaylists } from './quick_playlists.js';

function initSettingsModal() {
    const settingsBtn = document.getElementById('settings-btn');
    const settingsModal = document.getElementById('settings-modal-overlay');
    const closeBtn = document.getElementById('settings-close-btn');
    const cancelBtn = document.getElementById('settings-cancel-btn');
    const saveBtn = document.getElementById('settings-save-btn');
    const testBtn = document.getElementById('settings-test-btn');
    const notConfiguredBtn = document.getElementById('not-configured-settings-btn');

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
                toast(res.log.join(' '), true);
                // Reload the page after a short delay to apply changes
                setTimeout(() => {
                    window.location.reload();
                }, 1500);
            }
        });
    });
}


document.addEventListener('DOMContentLoaded', () => {

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

    const applyTheme = (theme) => {
        body.dataset.theme = theme;
        localStorage.setItem('mixerbeeTheme', theme);
        themeToggle.checked = (theme === 'light');
        if (typeof feather !== 'undefined') {
            feather.replace();
        }
    };

    const toggleTheme = () => {
        const newTheme = themeToggle.checked ? 'light' : 'dark';
        applyTheme(newTheme);
    };

    themeToggle.addEventListener('change', toggleTheme);

    function saveGlobalState() {
        if (!userSel.value) return;
        localStorage.setItem('mixerbeeGlobalState', JSON.stringify({
            userId: userSel.value,
        }));
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

        if (typeof feather !== 'undefined') {
            feather.replace();
        }
    }

    mixedTabBtn.addEventListener('click', () => switchTab('mixed'));
    schedulerTabBtn.addEventListener('click', () => switchTab('scheduler'));
    managerTabBtn.addEventListener('click', () => switchTab('manager'));

    userSel.addEventListener('input', () => {
        saveGlobalState();
        if (managerPane.classList.contains('active')) {
            initManager();
        }
    });

    const savedTheme = localStorage.getItem('mixerbeeTheme');
    applyTheme(savedTheme || 'dark');

    // This helper function makes fetch errors more informative
    const apiFetch = (url) => fetch(url)
        .then(r => {
            if (!r.ok) {
                throw new Error(`API call to ${url} failed with status ${r.status}`);
            }
            return r.json();
        });

    // Initial Load sequence
    fetch('api/config_status').then(r => r.json()).then(config => {
        if (!config.is_configured) {
            mainContent.style.display = 'none';
            notConfiguredWarning.style.display = 'block';
            if (typeof feather !== 'undefined') feather.replace();
            return; 
        }

        mainContent.style.display = 'block';
        notConfiguredWarning.style.display = 'none';

        // *** DIAGNOSTIC: Fetch data sequentially to find the failing API call ***
        const loadInitialData = async () => {
            try {
                console.log("Fetching default_user...");
                const defUser = await apiFetch('api/default_user');
                console.log("...OK", defUser);

                console.log("Fetching shows...");
                const seriesData = await apiFetch('api/shows');
                console.log("...OK", seriesData);

                console.log("Fetching movie_genres...");
                const movieGenreData = await apiFetch('api/movie_genres');
                console.log("...OK", movieGenreData);

                console.log("Fetching movie_libraries...");
                const libraryData = await apiFetch('api/movie_libraries');
                console.log("...OK", libraryData);

                console.log("Fetching music_artists...");
                const artistData = await apiFetch('api/music/artists');
                console.log("...OK", artistData);

                console.log("Fetching music_genres...");
                const musicGenreData = await apiFetch('api/music/genres');
                console.log("...OK", musicGenreData);

                // If we get here, all calls succeeded. Now render the UI.
                console.log("All data fetched successfully. Rendering UI...");
                
                activeUserDisplay.textContent = defUser.name;

                userSel.innerHTML = ''; 
                const userOption = Object.assign(document.createElement('option'), {
                    value: defUser.id,
                    textContent: defUser.name
                });
                userSel.appendChild(userOption);
                userSel.value = defUser.id;
                
                saveGlobalState();

                const allData = { seriesData, movieGenreData, libraryData, artistData, musicGenreData };

                initBuilderPane(userSel, allData);
                initQuickPlaylists(userSel, movieGenreData, musicGenreData);
                initSchedulerPane();

                switchTab('mixed');

                if (typeof feather !== 'undefined') {
                    feather.replace();
                }

            } catch (err) {
                console.error("Initialization failed during sequential fetch:", err);
                toast('Init error. Check browser console (F12) for details.', false);
            }
        };

        loadInitialData();
    });
});
