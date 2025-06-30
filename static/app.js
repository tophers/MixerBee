// static/app.js
import { toast, post, initModals } from './utils.js'; // Import initModals
import { initModal } from './modal.js';
import { initMixedPane } from './mixed.js';
import { initSchedulerPane } from './scheduler.js';

document.addEventListener('DOMContentLoaded', () => {

    initModals();

    const userSel = document.getElementById('user-select');
    const themeToggleBtn = document.getElementById('theme-toggle-btn');
    const body = document.body;

    const mixedTabBtn = document.getElementById('mixed-tab-btn');
    const schedulerTabBtn = document.getElementById('scheduler-tab-btn');
    const mixedPane = document.getElementById('mixed-pane');
    const schedulerPane = document.getElementById('scheduler-pane');
    const mainActionBar = document.getElementById('action-bar');

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

    function saveGlobalState() {
        localStorage.setItem('mixerbeeGlobalState', JSON.stringify({
            userId: userSel.value,
        }));
    }

    function loadGlobalState() {
        const stateJSON = localStorage.getItem('mixerbeeGlobalState');
        if (!stateJSON) return null;
        try {
            const state = JSON.parse(stateJSON);
            return state?.userId || null;
        } catch (e) { console.error("Failed to load global state:", e); return null; }
    }

    function switchTab(activeTab) {
        [mixedTabBtn, schedulerTabBtn].forEach(b => b.classList.remove('active'));
        [mixedPane, schedulerPane].forEach(p => p.classList.remove('active'));

        mainActionBar.style.display = 'none';

        if (activeTab === 'mixed') {
            mixedTabBtn.classList.add('active');
            mixedPane.classList.add('active');
            mainActionBar.style.display = 'flex';
        } else if (activeTab === 'scheduler') {
            schedulerTabBtn.classList.add('active');
            schedulerPane.classList.add('active');
        }

        mixedPane.style.display = (activeTab === 'mixed') ? 'block' : 'none';
        schedulerPane.style.display = (activeTab === 'scheduler') ? 'block' : 'none';
        
        // Re-run Feather to render any new icons on the active tab
        if (typeof feather !== 'undefined') {
            feather.replace();
        }
    }

    mixedTabBtn.addEventListener('click', () => switchTab('mixed'));
    schedulerTabBtn.addEventListener('click', () => switchTab('scheduler'));

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
      fetch('api/movie_libraries').then(r => r.json()) // Fetch movie libraries
    ])
      .then(([users, defUser, shows, genres, movieLibraries]) => {
        users.forEach(u => userSel.appendChild(Object.assign(document.createElement('option'), { value: u.id, textContent: u.name })));
        if (savedUserId && users.some(u => u.id === savedUserId)) {
            userSel.value = savedUserId;
        } else {
            userSel.value = defUser.id;
        }
        saveGlobalState();

        initModal(userSel);
        initMixedPane(userSel, shows, genres, movieLibraries); // Pass libraries to the mixed pane
        initSchedulerPane();

        // Start on the main builder tab
        switchTab('mixed');
        
        // Final icon replacement call after everything is initialized
        if (typeof feather !== 'undefined') {
            feather.replace();
        }
      })
      .catch((err) => {
        console.error("Initialization Error:", err);
        toast('Init error', false);
      });
});
