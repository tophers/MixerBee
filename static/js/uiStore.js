// static/js/uiStore.js

export const uiStore = {
    currentTab: 'mixed',
    showAiBuilder: false,
    
    setTab(tab) {
        this.currentTab = tab;
        if (tab === 'scheduler') Alpine.store('scheduler').loadSchedule();
        else if (tab === 'manager') Alpine.store('manager').load();
    }
};