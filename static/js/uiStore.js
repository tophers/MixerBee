// static/js/uiStore.js

const TAB_STORAGE_KEY = 'mixerbee:lastTab';
const TABS = ['mixed', 'assist', 'scheduler', 'manager'];

export const uiStore = {
    currentTab: 'mixed',
    showAiBuilder: false,

    // Reopens the tab the user last had, once the workspace is ready to load it.
    restoreTab() {
        let saved = null;
        try { saved = localStorage.getItem(TAB_STORAGE_KEY); } catch (e) { }
        if (saved && TABS.includes(saved) && saved !== this.currentTab) this.setTab(saved);
    },
    
    setTab(tab) {
        // A stale click on a hidden tab must not reopen it. The Assist tab is only
        // reachable while generative AI is available for this account.
        if (tab === 'assist' && !Alpine.store('settings')?.generative_ai_available) {
            this.currentTab = 'mixed';
            return;
        }
        this.currentTab = tab;
        try { localStorage.setItem(TAB_STORAGE_KEY, tab); } catch (e) { }
        if (tab === 'scheduler') Alpine.store('scheduler').loadSchedule();
        else if (tab === 'manager') Alpine.store('manager').load();
        else if (tab === 'assist') Alpine.store('assist').loadStatus();
    }
};