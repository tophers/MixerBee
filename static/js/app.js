// static/js/app.js
import { toast, initModals } from './utils.js';
import { initBuilderPane } from './builder.js';
import { initSchedulerPane } from './scheduler.js';
import { initManager } from './manager.js';
import { initQuickPlaylists } from './quick_playlists.js';

document.addEventListener('DOMContentLoaded', () => {

    initModals();

    const userSel = document.getElementById('user-select');
    const themeToggle = document.getElementById('theme-toggle-cb');
    const body = document.body;

    const mixedTabBtn = document.getElementById('mixed-tab-btn');
    const schedulerTabBtn = document.getElementById('scheduler-tab-btn');
    const managerTabBtn = document.getElementById('manager-tab-btn');

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
        localStorage.setItem('mixerbeeGlobalState', JSON.stringify({
            userId: userSel.value,
        }));
    }

    function loadGlobalState() {
        const stateJSON = localStorage.getItem('mixerbeeGlobalState');
        if (!stateJSON) return null;
        try {
            return JSON.parse(stateJSON)?.userId || null;
        } catch (e) { console.error("Failed to load global state:", e); return null; }
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
            initManager(); // Refresh data every time the tab is opened
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

    userSel.addEventListener('input', saveGlobalState);

    // Initial Load sequence
    const savedUserId = loadGlobalState();
    const savedTheme = localStorage.getItem('mixerbeeTheme');
    applyTheme(savedTheme || 'dark');

    Promise.all([
      fetch('api/users').then(r => r.json()),
      fetch('api/default_user').then(r => r.json()),
      fetch('api/shows').then(r => r.json()),
      fetch('api/movie_genres').then(r => r.json()),
      fetch('api/movie_libraries').then(r => r.json()),
      fetch('api/music/artists').then(r => r.json()),
      fetch('api/music/genres').then(r => r.json()),
    ])
      .then(([users, defUser, seriesData, movieGenreData, libraryData, artistData, musicGenreData]) => {
        users.forEach(u => userSel.appendChild(Object.assign(document.createElement('option'), { value: u.id, textContent: u.name })));
        userSel.value = (savedUserId && users.some(u => u.id === savedUserId)) ? savedUserId : defUser.id;
        saveGlobalState();
        
        const allData = { seriesData, movieGenreData, libraryData, artistData, musicGenreData };

        initBuilderPane(userSel, allData);
        initQuickPlaylists(userSel, movieGenreData, musicGenreData);
        initSchedulerPane();

        switchTab('mixed');

        if (typeof feather !== 'undefined') {
            feather.replace();
        }
      })
      .catch((err) => {
        console.error("Initialization Error:", err);
        toast('Init error', false);
      });
});
