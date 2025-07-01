// static/app.js
import { toast, post, initModals } from './utils.js';
import { initMixedPane } from './mixed.js';
import { initSchedulerPane } from './scheduler.js';
import { initManager } from './manager.js';

document.addEventListener('DOMContentLoaded', () => {

    initModals();

    const userSel = document.getElementById('user-select');
    const themeToggleBtn = document.getElementById('theme-toggle-btn');
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
      fetch('api/movie_libraries').then(r => r.json())
    ])
      .then(([users, defUser, shows, genres, movieLibraries]) => {
        users.forEach(u => userSel.appendChild(Object.assign(document.createElement('option'), { value: u.id, textContent: u.name })));
        if (savedUserId && users.some(u => u.id === savedUserId)) {
            userSel.value = savedUserId;
        } else {
            userSel.value = defUser.id;
        }
        saveGlobalState();

        initMixedPane(userSel, shows, genres, movieLibraries);
        initSchedulerPane();
        // Manager is initialized when tab is clicked
        
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
