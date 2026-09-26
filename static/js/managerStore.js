// static/js/managerStore.js

import { api } from './apiClient.js';
import { toast, useApi } from './utils.js';
import { confirmModal } from './modals.js';

export const managerStore = {
    items: [],
    filtered: [],
    searchQuery: '',
    sortColumn: 'Name',
    sortDirection: 'asc',
    viewFilter: 'All',
    isLoading: false,
    selectedIds: [],

    libraryIq: { total: 0, enriched: 0, percentage: 0 },
    contentsModal: { isOpen: false, parentItem: null, title: '', items: [], isLoading: false, hasChanges: false },
    overlapModal: { isOpen: false, isLoading: false, data: null },

    enrichmentStatus: {
        status: 'idle',
        total_items: 0,
        processed_items: 0,
        succeeded_items: 0,
        failed_items: 0,
        remaining_items: 0,
        queue_depth: 0,
        last_message: '',
        elapsed_seconds: 0
    },
    enrichmentPollTimer: null,

    async loadIq() {
        try {
            const res = await useApi(api.get('api/library/iq'), null, true, false);
            if (res.data) {
                this.libraryIq.total = res.data.total || 0;
                this.libraryIq.enriched = res.data.enriched || 0;
                this.libraryIq.percentage = res.data.total > 0 ? Math.round((res.data.enriched / res.data.total) * 100) : 0;
            }
        } catch (e) { console.error("Failed to load Library IQ", e); }
    },

    async pollEnrichmentStatus() {
        try {
            const res = await useApi(api.get('api/library/enrichment/status'), null, true, false);
            if (res.data) {
                Object.assign(this.enrichmentStatus, res.data);
                if (res.data.status === 'running' || res.data.status === 'stopping') {
                    if (!this.enrichmentPollTimer) {
                        this.enrichmentPollTimer = setTimeout(() => {
                            this.enrichmentPollTimer = null;
                            this.pollEnrichmentStatus();
                        }, 1500);
                    }
                } else {
                    if (this.enrichmentPollTimer) {
                        clearTimeout(this.enrichmentPollTimer);
                        this.enrichmentPollTimer = null;
                    }
                    this.loadIq();
                }
            }
        } catch (e) {
            console.error("Enrichment status poll failed", e);
        }
    },

    async startEnrichment() {
        try {
            const res = await useApi(api.post('api/library/enrichment/start', { batch_size: 10 }));
            if (res.status === 'ok') {
                toast("AI enrichment started in background.");
                this.pollEnrichmentStatus();
            }
        } catch (e) {
            toast(e.message || "Failed to start enrichment", false);
        }
    },

    async stopEnrichment() {
        try {
            const res = await useApi(api.post('api/library/enrichment/stop'));
            if (res.status === 'ok') {
                toast("Stopping AI enrichment...");
                this.pollEnrichmentStatus();
            }
        } catch (e) {
            toast("Failed to stop enrichment", false);
        }
    },

    async runSemanticRefresh(btnEl) {
        try {
            const res = await useApi(api.post('api/library/semantic_refresh'), btnEl);
            if (res.status === 'ok' || res.data?.status === 'ok') {
                const data = res.data || res;
                toast(`Index refreshed: ${data.added} added, ${data.refreshed} updated, ${data.removed} removed.`);
                this.loadIq();
                this.pollEnrichmentStatus();
            }
        } catch (e) {
            toast("Semantic refresh failed", false);
        }
    },

    async load() {
        const uid = Alpine.store('settings').activeUserId;
        if (!uid) return;
        this.isLoading = true;
        this.selectedIds = [];
        this.loadIq();
        this.pollEnrichmentStatus();
        try {
            const res = await useApi(api.get(`api/manageable_items?user_id=${uid}`));
            if (res.data) {
                const rawList = Array.isArray(res.data) ? res.data : (res.data.Items || []);
                this.items = rawList.map(item => ({
                    ...item,
                    Name: item.Name || item.name || 'Unknown',
                    Id: item.Id || item.id,
                    Type: item.Type || item.type || 'Playlist',
                    DisplayType: item.DisplayType || (item.Type === 'BoxSet' ? 'Collection' : item.Type),
                    ChildCount: item.ChildCount !== undefined ? item.ChildCount : (item.child_count || 0),
                    FormattedRuntime: item.FormattedRuntime || '',
                    ServerUrl: item.ServerUrl || ''
                }));
                this.applyFilters();
            }
        } catch (e) { 
            toast("Failed to load manager items.", false); 
        } finally { 
            this.isLoading = false; 
        }
    },

    applyFilters() {
        let list = Array.isArray(this.items) ? [...this.items] : [];
        if (this.viewFilter !== 'All') list = list.filter(i => i.DisplayType === this.viewFilter);
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
                primaryDiff = parseInt(aVal || 0, 10) - parseInt(bVal || 0, 10);
            } else {
                primaryDiff = (aVal ?? '').toString().localeCompare((bVal ?? '').toString(), undefined, { numeric: true, sensitivity: 'accent' });
            }

            if (primaryDiff !== 0) return primaryDiff * dir;
            if (col !== 'Name') return (a.Name ?? '').toString().localeCompare((b.Name ?? '').toString(), undefined, { numeric: true, sensitivity: 'accent' }) * dir;
            return 0;
        });

        this.filtered = list;
        // Prune selected IDs that are no longer in filtered view
        const validIds = new Set(list.map(i => i.Id));
        this.selectedIds = this.selectedIds.filter(id => validIds.has(id));
    },

    toggleSort(col) {
        if (this.sortColumn === col) this.sortDirection = this.sortDirection === 'asc' ? 'desc' : 'asc';
        else { this.sortColumn = col; this.sortDirection = 'asc'; }
        this.applyFilters();
    },

    // Multi-selection
    toggleSelect(id) {
        if (this.selectedIds.includes(id)) {
            this.selectedIds = this.selectedIds.filter(x => x !== id);
        } else {
            this.selectedIds.push(id);
        }
    },

    selectAll() {
        if (this.isAllSelected()) {
            this.selectedIds = [];
        } else {
            this.selectedIds = (this.filtered || []).map(i => i.Id);
        }
    },

    isAllSelected() {
        return (this.filtered || []).length > 0 && this.selectedIds.length === this.filtered.length;
    },

    async bulkDeleteSelected() {
        const uid = Alpine.store('settings').activeUserId;
        if (!uid || this.selectedIds.length === 0) return;

        try {
            await confirmModal.show({
                title: 'Bulk Delete Items?',
                text: `Permanently delete all ${this.selectedIds.length} selected playlists/collections? This cannot be undone.`,
                confirmText: `Delete ${this.selectedIds.length} Items`,
                isDanger: true
            });

            const res = await useApi(api.post('api/bulk_delete_items', {
                user_id: uid,
                item_ids: this.selectedIds
            }));

            if (res.status === 'ok' || res.data?.status === 'ok') {
                const data = res.data || res;
                toast(`Deleted ${data.deleted_count} items (${data.failed_count} failed).`);
                this.selectedIds = [];
                await this.load();
            }
        } catch (e) {
            // Cancelled or failed
        }
    },

    async checkOverlaps() {
        const uid = Alpine.store('settings').activeUserId;
        if (!uid) return;
        this.overlapModal.isOpen = true;
        this.overlapModal.isLoading = true;
        this.overlapModal.data = null;

        try {
            const targetIds = this.selectedIds.length > 0 ? this.selectedIds : null;
            const res = await useApi(api.post('api/library/overlap_report', {
                user_id: uid,
                item_ids: targetIds
            }));

            if (res.data) {
                this.overlapModal.data = res.data;
            }
        } catch (e) {
            toast("Failed to generate overlap report", false);
        } finally {
            this.overlapModal.isLoading = false;
        }
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
            const res = await useApi(api.get(`api/items/${item.Id}/children?user_id=${uid}`));
            if (res.data) this.contentsModal.items = Array.isArray(res.data) ? res.data : (res.data.Items || []);
        } catch (e) { 
            toast("Load failed", false); 
        } finally { 
            this.contentsModal.isLoading = false; 
        }
    },

    async saveContentOrder(btnEl) {
        const parent = this.contentsModal.parentItem;
        const uid = Alpine.store('settings').activeUserId;
        if (!parent || !uid) return;

        const itemNodes = document.querySelectorAll('.modal-window.wide ul.no-list li[data-id]');
        const itemIds = Array.from(itemNodes).map(node => node.getAttribute('data-id'));

        try {
            const res = await useApi(api.post(`api/items/${parent.Id}/reorder`, { user_id: uid, item_ids: itemIds }), btnEl);
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
            const res = await useApi(api.post(`api/${endpointType}/${parent.Id}/items/remove`, { user_id: uid, item_id_to_remove: childItem.Id || childItem.id }));
            
            if (res.status === 'ok') {
                await this.viewContents(parent);
                await this.load();
            }
        } catch (e) { }
    },

    async convertItem(item) {
        const uid = Alpine.store('settings').activeUserId;
        const canManageCollections = Alpine.store('settings').can_manage_collections;
        const targetType = item.Type === 'Playlist' ? 'Collection' : 'Playlist';
        if (targetType === 'Collection' && !canManageCollections) {
            return toast('This media account cannot create collections.', false);
        }
        const deleteOriginal = targetType === 'Collection' || canManageCollections;
        try {
            await confirmModal.show({
                title: deleteOriginal ? `Convert to ${targetType}?` : 'Copy to Playlist?',
                text: deleteOriginal
                    ? `Swap "${item.Name}" to a ${targetType}? Original will be deleted.`
                    : `Create a personal playlist from "${item.Name}"? The collection will remain unchanged.`,
                confirmText: deleteOriginal ? 'Convert' : 'Copy'
            });
            const res = await useApi(api.post(`api/convert_item`, { item_id: item.Id, user_id: uid, target_type: targetType, new_name: item.Name, delete_original: deleteOriginal }));
            if (res.status === 'ok') await this.load();
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
            const res = await useApi(api.post(`api/delete_item`, { item_id: item.Id, user_id: uid }));
            if (res.status === 'ok') await this.load();
        } catch (e) { }
    }
};
