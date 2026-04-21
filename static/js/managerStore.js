// static/js/managerStore.js

import { post, toast } from './utils.js';
import { confirmModal } from './modals.js';

export const managerStore = {
    items: [],
    filtered: [],
    searchQuery: '',
    sortColumn: 'Name',
    sortDirection: 'asc',
    isLoading: false,

    contentsModal: {
        isOpen: false,
        parentItem: null,
        title: '',
        items: [],
        isLoading: false
    },

    async load() {
        const uid = document.getElementById('user-select')?.value;
        if (!uid) return;
        this.isLoading = true;
        try {
            const res = await fetch(`api/manageable_items?user_id=${uid}`);
            if (res.ok) {
                const data = await res.json();
                const rawList = Array.isArray(data) ? data : (data.Items || []);
                this.items = rawList.map(item => ({
                    ...item,
                    Name: item.Name || item.name || 'Unknown',
                    Id: item.Id || item.id,
                    Type: item.Type || item.type || 'Playlist',
                    ChildCount: item.ChildCount !== undefined ? item.ChildCount : (item.child_count || 0)
                }));
                this.applyFilters();
            }
        } catch (e) { console.error("Manager load failed:", e); }
        finally { this.isLoading = false; }
    },

    applyFilters() {
        let list = Array.isArray(this.items) ? [...this.items] : [];
        if (this.searchQuery) {
            const q = this.searchQuery.toLowerCase().trim();
            list = list.filter(i => i.Name.toLowerCase().includes(q));
        }
        
        const col = this.sortColumn;
        const dir = this.sortDirection === 'asc' ? 1 : -1;

        list.sort((a, b) => {
            const aVal = (a[col] ?? '').toString();
            const bVal = (b[col] ?? '').toString();
            
            return aVal.localeCompare(bVal, undefined, { 
                numeric: true, 
                sensitivity: 'accent' 
            }) * dir;
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
        const uid = document.getElementById('user-select')?.value;
        this.contentsModal.parentItem = item;
        this.contentsModal.title = item.Name;
        this.contentsModal.isOpen = true;
        this.contentsModal.isLoading = true;
        this.contentsModal.items = [];
        try {
            const res = await fetch(`api/items/${item.Id}/children?user_id=${uid}`);
            if (res.ok) {
                const data = await res.json();
                this.contentsModal.items = Array.isArray(data) ? data : (data.Items || []);
            }
        } catch (e) { toast("Load failed", false); }
        finally { this.contentsModal.isLoading = false; }
    },

    async removeItem(childItem) {
        const parent = this.contentsModal.parentItem;
        const uid = document.getElementById('user-select')?.value;
        if (!parent || !childItem) return;

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
                toast("Item removed", true);
                await this.viewContents(parent);
                await this.load();
            }
        } catch (e) { }
    },

    async convertItem(item) {
        const uid = document.getElementById('user-select')?.value;
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
            if (res.status === 'ok') { toast(`Converted!`, true); await this.load(); }
        } catch (e) { }
    },

    async deleteItem(item) {
        const uid = document.getElementById('user-select')?.value;
        try {
            await confirmModal.show({
                title: 'Delete Entire List?',
                text: `Delete "${item.Name}"? This cannot be undone.`,
                confirmText: 'Delete',
                isDanger: true
            });
            const res = await post(`api/delete_item`, { item_id: item.Id, user_id: uid });
            if (res.status === 'ok') { toast("Deleted", true); await this.load(); }
        } catch (e) { }
    }
};