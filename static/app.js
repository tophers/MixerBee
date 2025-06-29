// static/app.js
import { toast, post } from './utils.js';
import { initTvPane } from './tv.js';
import { initMoviesPane } from './movies.js';
import { initModal } from './modal.js';
import { initMixedPane } from './mixed.js';
import { initSchedulerPane } from './scheduler.js';

document.addEventListener('DOMContentLoaded', () => {

    /* ── handles to GLOBAL elements ── */
    const userSel = document.getElementById('user-select');
    const globalPlaylistName = document.getElementById('global-playlist-name');
    const mainActionBar = document.getElementById('action-bar');
    const themeToggleBtn = document.getElementById('theme-toggle-btn');
    const body = document.body;

    const tvTabBtn = document.getElementById('tv-tab-btn');
    const moviesTabBtn = document.getElementById('movies-tab-btn');
    const mixedTabBtn = document.getElementById('mixed-tab-btn');
    const schedulerTabBtn = document.getElementById('scheduler-tab-btn');
    const tvPane = document.getElementById('tv-pane');
    const moviesPane = document.getElementById('movies-pane');
    const mixedPane = document.getElementById('mixed-pane');
    const schedulerPane = document.getElementById('scheduler-pane');

    /* ── Theme Management ── */
    const applyTheme = (theme) => {
        body.dataset.theme = theme;
        localStorage.setItem('mixerbeeTheme', theme);
        if (theme === 'light') {
            themeToggleBtn.textContent = 'Dark Mode';
            themeToggleBtn.title = 'Switch to Dark Theme';
        } else {
            themeToggleBtn.textContent = 'Light Mode';
            themeToggleBtn.title = 'Switch to Light Theme';
        }
    };

    const toggleTheme = () => {
        const currentTheme = body.dataset.theme || 'dark';
        const newTheme = currentTheme === 'dark' ? 'light' : 'dark';
        applyTheme(newTheme);
    };

    themeToggleBtn.addEventListener('click', toggleTheme);

    /* ── GLOBAL State Persistence ── */
    function saveGlobalState() {
        localStorage.setItem('mixerbeeGlobalState', JSON.stringify({
            userId: userSel.value,
            playlistName: globalPlaylistName.value,
        }));
    }

    function loadGlobalState() {
        const stateJSON = localStorage.getItem('mixerbeeGlobalState');
        if (!stateJSON) return;
        try {
            const state = JSON.parse(stateJSON);
            if (!state) return;
            globalPlaylistName.value = state.playlistName || 'MixerBee Playlist';
            return state.userId;
        } catch (e) { console.error("Failed to load global state:", e); return null; }
    }

    function switchTab(activeTab) {
        const createTvBtn = document.getElementById('create-tv-mix-btn');
        const createMovieBtn = document.getElementById('create-movie-playlist-btn');
        const generateMixedBtn = document.getElementById('generate-mixed-playlist-btn');

        [tvTabBtn, moviesTabBtn, mixedTabBtn, schedulerTabBtn].forEach(b => b.classList.remove('active'));
        [tvPane, moviesPane, mixedPane, schedulerPane].forEach(p => p.classList.remove('active'));
        [createTvBtn, createMovieBtn, generateMixedBtn].forEach(b => b.classList.add('hidden'));

        if (activeTab === 'tv') {
            tvTabBtn.classList.add('active');
            tvPane.classList.add('active');
            createTvBtn.classList.remove('hidden');
        } else if (activeTab === 'movies') {
            moviesTabBtn.classList.add('active');
            moviesPane.classList.add('active');
            createMovieBtn.classList.remove('hidden');
        } else if (activeTab === 'mixed') {
            mixedTabBtn.classList.add('active');
            mixedPane.classList.add('active');
            generateMixedBtn.classList.remove('hidden');
        } else if (activeTab === 'scheduler') {
            schedulerTabBtn.classList.add('active');
            schedulerPane.classList.add('active');
        }

        tvPane.style.display = (activeTab === 'tv') ? 'block' : 'none';
        moviesPane.style.display = (activeTab === 'movies') ? 'block' : 'none';
        mixedPane.style.display = (activeTab === 'mixed') ? 'block' : 'none';
        schedulerPane.style.display = (activeTab === 'scheduler') ? 'block' : 'none';
    }

    tvTabBtn.addEventListener('click', () => switchTab('tv'));
    moviesTabBtn.addEventListener('click', () => switchTab('movies'));
    mixedTabBtn.addEventListener('click', () => switchTab('mixed'));
    schedulerTabBtn.addEventListener('click', () => switchTab('scheduler'));

    userSel.addEventListener('input', saveGlobalState);
    globalPlaylistName.addEventListener('input', saveGlobalState);

    // Initial Load sequence
    const savedUserId = loadGlobalState();
    const savedTheme = localStorage.getItem('mixerbeeTheme');
    applyTheme(savedTheme || 'dark'); // Apply theme

    Promise.all([
      fetch('api/users').then(r => r.json()),
      fetch('api/default_user').then(r => r.json()),
      fetch('api/shows').then(r => r.json()),
      fetch('api/movie_genres').then(r => r.json())
    ])
      .then(([users, defUser, shows, genres]) => {
        users.forEach(u => userSel.appendChild(Object.assign(document.createElement('option'), { value: u.id, textContent: u.name })));
        if (savedUserId && users.some(u => u.id === savedUserId)) {
            userSel.value = savedUserId;
        } else {
            userSel.value = defUser.id;
        }
        saveGlobalState();

        initTvPane(document.getElementById('show-box'), shows, userSel);
        initMoviesPane(userSel, genres);
        initModal(userSel);
        initMixedPane(userSel, shows, genres);
        initSchedulerPane();
      })
      .catch((err) => {
        console.error("Initialization Error:", err);
        toast('Init error', false);
      });
});
