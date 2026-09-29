// static/js/uiStore.js

export const uiStore = {
    currentTab: 'mixed',
    showAiBuilder: false,
    
    setTab(tab) {
        // A stale click on a hidden tab must not reopen it. The Assist tab is only
        // reachable while generative AI is available for this account.
        if (tab === 'assist' && !Alpine.store('settings')?.generative_ai_available) {
            this.currentTab = 'mixed';
            return;
        }
        this.currentTab = tab;
        if (tab === 'scheduler') Alpine.store('scheduler').loadSchedule();
        else if (tab === 'manager') Alpine.store('manager').load();
        else if (tab === 'assist') Alpine.store('assist').loadStatus();
    }
};