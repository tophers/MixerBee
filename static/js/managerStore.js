// static/js/managerStore.js

import { post, toast } from './utils.js';
import { confirmModal } from './modals.js';

export const managerStore = {
    items: [],
    filtered: [],
    searchQuery: '',
    sortColumn: 'Name',
    sortDirection: 'asc',
    viewFilter: 'All',
    isLoading: false,

    libraryIq: {
        total: 0,
        enriched: 0,
        percentage: 0
    },

    contentsModal: {
        isOpen: false,
        parentItem: null,
        title: '',
        items: [],
        isLoading: false,
        hasChanges: false
    },

    async loadIq() {
        try {
            const res = await fetch(`api/library/iq?_cb=${Date.now()}`);
            if (res.ok) {
                const data = await res.json();
                this.libraryIq.total = data.total || 0;
                this.libraryIq.enriched = data.enriched || 0;
                this.libraryIq.percentage = data.total > 0 ? Math.round((data.enriched / data.total) * 100) : 0;
            }
        } catch (e) {
            console.error("Failed to load Library IQ:", e);
        }
    },

    async load() {
        const uid = Alpine.store('settings').activeUserId;
        if (!uid) return;
        this.isLoading = true;
        this.loadIq();
        try {
            const res = await fetch(`api/manageable_items?user_id=${uid}&_cb=${Date.now()}`);
            if (res.ok) {
                const data = await res.json();
                const rawList = Array.isArray(data) ? data : (data.Items || []);
                this.items = rawList.map(item => ({
                    ...item,
                    Name: item.Name || item.name || 'Unknown',
                    Id: item.Id || item.id,
                    Type: item.Type || item.type || 'Playlist',
                    DisplayType: item.DisplayType || (item.Type === 'BoxSet' ? 'Collection' : item.Type),
                    ChildCount: item.ChildCount !== undefined ? item.ChildCount : (item.child_count || 0)
                }));
                this.applyFilters();
            }
        } catch (e) { console.error("Manager load failed:", e); }
        finally { this.isLoading = false; }
    },

    applyFilters() {
        let list = Array.isArray(this.items) ? [...this.items] : [];

        if (this.viewFilter !== 'All') {
            list = list.filter(i => i.DisplayType === this.viewFilter);
        }

        if (this.searchQuery) {
            const q = this.searchQuery.toLowerCase().trim();
            list = list.filter(i => i.Name.toLowerCase().includes(q));
        }

        const col = this.sortColumn;
        const dir = this.sortDirection === 'asc' ? 1 : -1;

        list.sort((a, b) => {
            let aVal = a[col];
            let bVal = b[col];
            let primaryDiff = 0;

            if (col === 'ChildCount') {
                aVal = parseInt(aVal || 0, 10);
                bVal = parseInt(bVal || 0, 10);
                primaryDiff = aVal - bVal;
            } else {
                aVal = (aVal ?? '').toString();
                bVal = (bVal ?? '').toString();
                primaryDiff = aVal.localeCompare(bVal, undefined, {
                    numeric: true,
                    sensitivity: 'accent'
                });
            }

            if (primaryDiff !== 0) {
                return primaryDiff * dir;
            }

            if (col !== 'Name') {
                let aName = (a.Name ?? '').toString();
                let bName = (b.Name ?? '').toString();
                return aName.localeCompare(bName, undefined, { numeric: true, sensitivity: 'accent' }) * dir;
            }

            return 0;
        });

        this.filtered = list;
    },

    toggleSort(col) {
        if (this.sortColumn === col) {
            this.sortDirection = this.sortDirection === 'asc' ? 'desc' : 'asc';
        } else {
            this.sortColumn = col;
            this.sortDirection = 'asc';
        }
        this.applyFilters();
    },

    async viewContents(item) {
        const uid = Alpine.store('settings').activeUserId;
        this.contentsModal.parentItem = item;
        this.contentsModal.title = item.Name;
        this.contentsModal.isOpen = true;
        this.contentsModal.isLoading = true;
        this.contentsModal.hasChanges = false;
        this.contentsModal.items = [];
        try {
            const res = await fetch(`api/items/${item.Id}/children?user_id=${uid}&_cb=${Date.now()}`);
            if (res.ok) {
                const data = await res.json();
                this.contentsModal.items = Array.isArray(data) ? data : (data.Items || []);
            }
        } catch (e) { toast("Load failed", false); }
        finally { this.contentsModal.isLoading = false; }
    },

    async saveContentOrder(btnEl) {
        const parent = this.contentsModal.parentItem;
        const uid = Alpine.store('settings').activeUserId;
        if (!parent || !uid) return;

        const itemNodes = document.querySelectorAll('.modal-window.wide ul.no-list li[data-id]');
        const itemIds = Array.from(itemNodes).map(node => node.getAttribute('data-id'));

        try {
            const res = await post(`api/items/${parent.Id}/reorder`, {
                user_id: uid,
                item_ids: itemIds
            }, btnEl);

            if (res.status === 'ok') {
                this.contentsModal.hasChanges = false;
                await this.load();
            }
        } catch (e) {
            toast("Failed to update order", false);
        }
    },

    async removeItem(childItem) {
        const parent = this.contentsModal.parentItem;
        const uid = Alpine.store('settings').activeUserId;
        if (!parent || !childItem || !uid) return;

        try {
            await confirmModal.show({
                title: 'Remove from List?',
                text: `Remove "${childItem.Name || childItem.name}" from "${parent.Name}"?`,
                confirmText: 'Remove',
                isDanger: true
            });

            const isCollection = parent.Type === 'BoxSet' || parent.Type === 'Collection';
            const endpointType = isCollection ? 'collections' : 'playlists';

            const res = await post(`api/${endpointType}/${parent.Id}/items/remove`, {
                user_id: uid,
                item_id_to_remove: childItem.Id || childItem.id
            });

            if (res.status === 'ok') {
                await this.viewContents(parent);
                await this.load();
            }
        } catch (e) { }
    },

    async convertItem(item) {
        const uid = Alpine.store('settings').activeUserId;
        const targetType = item.Type === 'Playlist' ? 'Collection' : 'Playlist';
        try {
            await confirmModal.show({
                title: `Convert to ${targetType}?`,
                text: `Swap "${item.Name}" to a ${targetType}? Original will be deleted.`,
                confirmText: 'Convert'
            });
            const res = await post(`api/convert_item`, {
                item_id: item.Id, user_id: uid, target_type: targetType,
                new_name: item.Name, delete_original: true
            });
            if (res.status === 'ok') { await this.load(); }
        } catch (e) { }
    },

    async deleteItem(item) {
        const uid = Alpine.store('settings').activeUserId;
        try {
            await confirmModal.show({
                title: 'Delete Entire List?',
                text: `Delete "${item.Name}"? This cannot be undone.`,
                confirmText: 'Delete',
                isDanger: true
            });
            const res = await post(`api/delete_item`, { item_id: item.Id, user_id: uid });
            if (res.status === 'ok') { await this.load(); }
        } catch (e) { }
    }
};