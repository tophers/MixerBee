// static/js/managerStore.js

import { api } from './apiClient.js';
import { toast, useApi } from './utils.js';
import { confirmModal } from './modals.js';

const PAGE_SIZE_KEY = 'mixerbee:managerPageSize';
export const PAGE_SIZES = [25, 50, 100, 0];   // 0 = show all
const DEFAULT_PAGE_SIZE = 50;

function storedPageSize() {
    try {
        const n = parseInt(localStorage.getItem(PAGE_SIZE_KEY), 10);
        if (PAGE_SIZES.includes(n)) return n;
    } catch (e) { }
    return DEFAULT_PAGE_SIZE;
}

export const managerStore = {
    items: [],
    filtered: [],
    searchQuery: '',
    sortColumn: 'Name',
    sortDirection: 'asc',
    viewFilter: 'All',
    isLoading: false,
    selectedIds: [],
    _lastSelectedId: null,

    // Pagination is purely client-side: filter -> search -> sort -> slice.
    page: 1,
    pageSize: DEFAULT_PAGE_SIZE,
    pageSizes: PAGE_SIZES,
    paged: [],
    counts: { All: 0, Playlist: 0, Collection: 0, MixerBee: 0 },

    get libraryIq() { return Alpine.store('ai')?.libraryIq || { total: 0, enriched: 0, percentage: 0 }; },
    set libraryIq(_) {},
    get enrichmentStatus() { return Alpine.store('ai')?.enrichmentStatus || { status: 'idle', total_items: 0, processed_items: 0, succeeded_items: 0, failed_items: 0, remaining_items: 0, queue_depth: 0, last_message: '', elapsed_seconds: 0 }; },
    set enrichmentStatus(_) {},

    contentsModal: { isOpen: false, parentItem: null, title: '', items: [], isLoading: false, hasChanges: false },
    overlapModal: { isOpen: false, isLoading: false, data: null },

    loadIq() { return Alpine.store('ai')?.loadIq(); },
    pollEnrichmentStatus() { return Alpine.store('ai')?.pollEnrichmentStatus(); },
    startEnrichment() { return Alpine.store('ai')?.startEnrichment(); },
    stopEnrichment() { return Alpine.store('ai')?.stopEnrichment(); },
    runSemanticRefresh(btnEl) { return Alpine.store('ai')?.runSemanticRefresh(btnEl); },

    async load() {
        const uid = Alpine.store('settings').activeUserId;
        if (!uid) return;
        this.isLoading = true;
        this.selectedIds = [];
        this.pageSize = storedPageSize();
        try {
            // Silent: the table shows its own loading rows, and a load is not worth a toast.
            const [res, runsRes] = await Promise.all([
                useApi(api.get(`api/manageable_items?user_id=${uid}`), null, true, false),
                useApi(api.get('api/build_runs?limit=500'), null, true, false)
            ]);
            if (res.status === 'error') throw new Error(res.error?.detail || 'load failed');
            // Latest successful build per output (runs arrive newest first).
            const builtBy = new Map();
            for (const run of (runsRes?.data?.runs || [])) {
                if (run.output_id && run.outcome !== 'error' && !builtBy.has(run.output_id)) {
                    builtBy.set(run.output_id, run.finished_at || run.started_at);
                }
            }
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
                    ServerUrl: item.ServerUrl || '',
                    BuiltByMixerBee: builtBy.has(item.Id || item.id),
                    LastBuiltAt: builtBy.get(item.Id || item.id) || ''
                }));
                this.applyFilters({ resetPage: false });
            }
        } catch (e) { 
            toast("Failed to load manager items.", false); 
        } finally { 
            this.isLoading = false; 
        }
    },

    applyFilters({ resetPage = true } = {}) {
        let list = Array.isArray(this.items) ? [...this.items] : [];
        if (this.searchQuery) {
            const q = this.searchQuery.toLowerCase().trim();
            list = list.filter(i => i.Name.toLowerCase().includes(q));
        }
        // Pill counts reflect the search, so they say where the matches are.
        this.counts = {
            All: list.length,
            Playlist: list.filter(i => i.DisplayType === 'Playlist').length,
            Collection: list.filter(i => i.DisplayType === 'Collection').length,
            MixerBee: list.filter(i => i.BuiltByMixerBee).length
        };
        if (this.viewFilter === 'MixerBee') list = list.filter(i => i.BuiltByMixerBee);
        else if (this.viewFilter !== 'All') list = list.filter(i => i.DisplayType === this.viewFilter);

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
        if (resetPage) this.page = 1;
        this.updatePage();
    },

    // -- pagination -------------------------------------------------------------

    pageCount() {
        if (!this.pageSize) return 1;
        return Math.max(1, Math.ceil((this.filtered || []).length / this.pageSize));
    },

    updatePage() {
        const list = this.filtered || [];
        this.page = Math.min(Math.max(1, this.page), this.pageCount());
        this.paged = this.pageSize ? list.slice((this.page - 1) * this.pageSize, this.page * this.pageSize) : list;
        this._lastSelectedId = null;
    },

    goToPage(n) {
        this.page = n;
        this.updatePage();
        document.getElementById('manager-pane')?.scrollIntoView({ block: 'start', behavior: 'smooth' });
    },

    setPageSize(size) {
        this.pageSize = Number(size) || 0;
        try { localStorage.setItem(PAGE_SIZE_KEY, String(this.pageSize)); } catch (e) { }
        this.page = 1;
        this.updatePage();
    },

    rangeLabel() {
        const total = (this.filtered || []).length;
        if (!total) return '';
        if (!this.pageSize || total <= this.pageSize) return `${total} ${total === 1 ? 'list' : 'lists'}`;
        const start = (this.page - 1) * this.pageSize + 1;
        return `Showing ${start}–${start + this.paged.length - 1} of ${total}`;
    },

    // Page buttons with gaps: 1 … 4 5 6 … 12
    pageNumbers() {
        const total = this.pageCount();
        if (total <= 7) return Array.from({ length: total }, (_, i) => i + 1);
        const pages = new Set([1, total, this.page - 1, this.page, this.page + 1]);
        const sorted = [...pages].filter(n => n >= 1 && n <= total).sort((a, b) => a - b);
        const out = [];
        sorted.forEach((n, i) => {
            if (i && n - sorted[i - 1] > 1) out.push('…' + n);
            out.push(n);
        });
        return out;
    },

    toggleSort(col) {
        if (this.sortColumn === col) this.sortDirection = this.sortDirection === 'asc' ? 'desc' : 'asc';
        else { this.sortColumn = col; this.sortDirection = 'asc'; }
        this.applyFilters();
    },

    // Multi-selection
    // Shift-click selects (or clears) the whole range since the last clicked row.
    toggleSelect(id, event = null) {
        // Ranges stay within the visible page.
        const ids = (this.paged || []).map(i => i.Id);
        const anchor = this._lastSelectedId;
        if (event?.shiftKey && anchor && anchor !== id && ids.includes(anchor)) {
            const [from, to] = [ids.indexOf(anchor), ids.indexOf(id)].sort((a, b) => a - b);
            const range = ids.slice(from, to + 1);
            const selecting = !this.selectedIds.includes(id);
            this.selectedIds = selecting
                ? [...new Set([...this.selectedIds, ...range])]
                : this.selectedIds.filter(x => !range.includes(x));
        } else if (this.selectedIds.includes(id)) {
            this.selectedIds = this.selectedIds.filter(x => x !== id);
        } else {
            this.selectedIds.push(id);
        }
        this._lastSelectedId = id;
    },

    formatBuiltAt(iso) {
        return iso ? Alpine.store('scheduler').formatRelative(iso) : '';
    },

    // Header checkbox: selects or clears the current page only (Gmail pattern).
    togglePageSelection() {
        const pageIds = (this.paged || []).map(i => i.Id);
        if (this.isPageSelected()) {
            const drop = new Set(pageIds);
            this.selectedIds = this.selectedIds.filter(id => !drop.has(id));
        } else {
            this.selectedIds = [...new Set([...this.selectedIds, ...pageIds])];
        }
    },

    isPageSelected() {
        const page = this.paged || [];
        return page.length > 0 && page.every(i => this.selectedIds.includes(i.Id));
    },

    isPagePartlySelected() {
        const page = this.paged || [];
        return !this.isPageSelected() && page.some(i => this.selectedIds.includes(i.Id));
    },

    isAllSelected() {
        const list = this.filtered || [];
        return list.length > 0 && this.selectedIds.length === list.length;
    },

    selectAllMatching() {
        this.selectedIds = (this.filtered || []).map(i => i.Id);
    },

    clearSelection() {
        this.selectedIds = [];
        this._lastSelectedId = null;
    },

    // Selected rows that are not on the current page, so the bulk bar can say so.
    selectedOffPage() {
        const onPage = new Set((this.paged || []).map(i => i.Id));
        return this.selectedIds.filter(id => !onPage.has(id)).length;
    },

    // The "select all N matching" banner only matters when there is more than one page.
    showSelectAllBanner() {
        return this.pageCount() > 1 && this.isPageSelected();
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
    },

    historyModal: {
        isOpen: false,
        isLoading: false,
        runs: [],
        selectedRun: null,
        compareRunId: '',
        diffResult: null,
        isComparing: false,
        replayName: '',
        missingItems: [],
        isReplaying: false
    },

    async openHistoryModal() {
        this.historyModal.isOpen = true;
        this.historyModal.selectedRun = null;
        this.historyModal.diffResult = null;
        this.historyModal.compareRunId = '';
        this.historyModal.missingItems = [];
        await this.loadBuildRuns();
    },

    async loadBuildRuns() {
        this.historyModal.isLoading = true;
        try {
            const res = await useApi(api.get('api/build_runs'), null, true, false);
            if (res && res.data) {
                this.historyModal.runs = Array.isArray(res.data) ? res.data : (res.data.runs || []);
            }
        } catch (e) {
            console.error('Failed to load build runs:', e);
            toast('Failed to load build history', false);
        } finally {
            this.historyModal.isLoading = false;
        }
    },

    async selectBuildRun(runId) {
        if (!runId) {
            this.historyModal.selectedRun = null;
            return;
        }
        this.historyModal.isLoading = true;
        this.historyModal.diffResult = null;
        this.historyModal.compareRunId = '';
        this.historyModal.missingItems = [];
        try {
            const res = await useApi(api.get(`api/build_runs/${runId}`), null, true, false);
            if (res && res.data) {
                this.historyModal.selectedRun = res.data.run || res.data;
                const summary = this.historyModal.selectedRun.summary || '';
                const m = summary.match(/Created playlist '([^']+)'/);
                const baseName = m ? m[1] : (this.historyModal.selectedRun.preset_id || 'Mix');
                const dateStr = new Date().toISOString().slice(0, 10);
                this.historyModal.replayName = `${baseName} — replay ${dateStr}`;
            }
        } catch (e) {
            console.error('Failed to load build run details:', e);
            toast('Failed to load run details', false);
        } finally {
            this.historyModal.isLoading = false;
        }
    },

    async compareBuildRun(compareId) {
        if (!this.historyModal.selectedRun || !compareId) {
            this.historyModal.diffResult = null;
            return;
        }
        this.historyModal.isComparing = true;
        try {
            const res = await useApi(api.get(`api/build_runs/${this.historyModal.selectedRun.id}/diff/${compareId}`), null, true, false);
            if (res && res.data) {
                this.historyModal.diffResult = res.data.diff;
            }
        } catch (e) {
            console.error('Failed to diff runs:', e);
            toast('Comparison failed', false);
        } finally {
            this.historyModal.isComparing = false;
        }
    },

    async replayBuildRun(btnEl) {
        const run = this.historyModal.selectedRun;
        if (!run) return;
        const uid = Alpine.store('settings').activeUserId;
        this.historyModal.isReplaying = true;
        try {
            const payload = {
                playlist_name: this.historyModal.replayName || undefined,
                user_id: uid,
                dry_run: false
            };
            const res = await useApi(api.post(`api/build_runs/${run.id}/replay`, payload), btnEl);
            if (res && (res.status === 'ok' || res.data?.status === 'ok')) {
                const data = res.data || res;
                toast(`Playlist created: ${data.playlist_name || 'Replay'}`, true);
                if (data.missing_items?.length > 0) {
                    toast(`Note: ${data.missing_items.length} missing items omitted.`, false);
                }
                this.historyModal.isOpen = false;
                await this.load();
            }
        } catch (e) {
            toast(e.message || 'Replay failed', false);
        } finally {
            this.historyModal.isReplaying = false;
        }
    }
};

