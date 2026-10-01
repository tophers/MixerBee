// static/js/mixerStore.js

import { api } from './apiClient.js';
import { toast, debounce, generateUUID, useApi } from './utils.js';
import { ensureBlockState, createNewBlock, createEchoBlock, serializeBlockDefinition, serializeMixDefinition, defaultMixOptions, normalizeMixOptions } from './blockFactory.js';
import { confirmModal, smartBuildModal, smartPlaylistModal, previewModal, resetWatchModal, recipeLibraryModal, saveRecipeModal, musicQuickBuildModal } from './modals.js';
import { SMART_BUILD_TYPES, BLOCK_TYPES } from './definitions.js';

export const mixerStore = {
    blocks: [],
    mix_options: defaultMixOptions(),
    library: {
        seriesData: [], movieGenreData: [], libraryData: [], artistData: [], musicGenreData: [], studioData: []
    },

    buildMode: 'create',
    createAsCollection: false,
    playlistName: '',
    existingPlaylistId: '',
    userPlaylists: [],
    autosaveKey: 'mixerbee_autosave',

    past: [],
    future: [],
    savedBaseline: null,
    _historySuspended: false,
    _previewDebouncers: {},

    get canUndo() {
        return (this.past || []).length > 0;
    },
    set canUndo(_) {},
    get canRedo() {
        return (this.future || []).length > 0;
    },
    set canRedo(_) {},

    hasActiveRules() {
        const o = this.mix_options;
        if (!o) return false;
        if (o.freshness && (o.freshness.last_successful_builds > 0 || o.freshness.watched_within_days > 0)) return true;
        if (o.duplicate_policy && (o.duplicate_policy.cross_block_policy !== 'suppress' || o.duplicate_policy.max_movies_per_franchise > 0)) return true;
        if (o.sequencing && o.sequencing.mode && o.sequencing.mode !== 'sequential') return true;
        if (o.runtime_budget && o.runtime_budget.mode && o.runtime_budget.mode !== 'off' && o.runtime_budget.target_minutes > 0) return true;
        return false;
    },

    captureDraft() {
        return serializeMixDefinition({ blocks: this.blocks, mix_options: this.mix_options });
    },

    beginEdit(label = '') {
        if (this._historySuspended) return;
        const currentDraft = this.captureDraft();
        this.past.push(currentDraft);
        if (this.past.length > 50) this.past.shift();
        this.future = [];
    },

    undo() {
        if (!this.canUndo) return;
        const current = this.captureDraft();
        this.future.push(current);
        const previous = this.past.pop();
        this.restoreDraft(previous);
        toast('Undo', false);
    },

    redo() {
        if (!this.canRedo) return;
        const current = this.captureDraft();
        this.past.push(current);
        const next = this.future.pop();
        this.restoreDraft(next);
        toast('Redo', false);
    },

    restoreDraft(draft) {
        if (!draft) return;
        this._historySuspended = true;
        try {
            const blocks = JSON.parse(JSON.stringify(draft.blocks || []));
            blocks.forEach(b => this.ensureBlockState(b));
            this.blocks = blocks;
            if (draft.mix_options) {
                this.mix_options = normalizeMixOptions(draft.mix_options);
            }
            this.persistToLocalStorage();
        } finally {
            this._historySuspended = false;
        }
    },

    markSaved(definition = null) {
        this.savedBaseline = JSON.stringify(definition || this.captureDraft());
    },

    isDirty() {
        if (!this.savedBaseline) return this.blocks.length > 0;
        return JSON.stringify(this.captureDraft()) !== this.savedBaseline;
    },

    revertToSaved() {
        if (!this.savedBaseline) return;
        this.beginEdit('Revert to saved');
        try {
            const baseline = JSON.parse(this.savedBaseline);
            this.restoreDraft(baseline);
            toast('Reverted to saved preset.', true);
        } catch (e) {
            console.error('Revert failed:', e);
        }
    },

    init(connectionId) {
        if (!connectionId) return;
        this.autosaveKey = `mixerbee_autosave:${connectionId}`;
        try {
            const saved = localStorage.getItem(this.autosaveKey);
            if (saved) {
                const parsed = JSON.parse(saved);
                const loadedBlocks = parsed.blocks || [];
                loadedBlocks.forEach(b => this.ensureBlockState(b));
                this.blocks = loadedBlocks;
                this.mix_options = normalizeMixOptions(parsed.mix_options);
            }
        } catch (e) { console.error("Autosave restore failed:", e); }

        this.markSaved();

        window.addEventListener('keydown', (e) => {
            const isModifier = e.ctrlKey || e.metaKey;
            if (!isModifier) return;
            const tag = document.activeElement?.tagName;
            if (['INPUT', 'TEXTAREA', 'SELECT'].includes(tag)) return;

            if (e.key === 'z' && !e.shiftKey) {
                e.preventDefault();
                this.undo();
            } else if ((e.key === 'z' && e.shiftKey) || e.key === 'y') {
                e.preventDefault();
                this.redo();
            }
        });

        Alpine.watch(() => JSON.stringify(this.blocks), () => this.persistToLocalStorage());
    },

    ensureBlockState(block) {
        ensureBlockState(block, this.library);
        
        // Setup internal properties if not initialized by blockFactory
        if (block.type === BLOCK_TYPES.TV || block.type === BLOCK_TYPES.CURATED || (block.type === BLOCK_TYPES.VIBE && block.vibe_type === BLOCK_TYPES.TV)) {
            this.updatePreviewCount(block);
        }
    },

    persistToLocalStorage() {
        if (this.blocks.length > 0) {
            localStorage.setItem(this.autosaveKey, JSON.stringify({
                schema_version: 1,
                blocks: this.blocks,
                mix_options: this.mix_options
            }));
        } else {
            localStorage.removeItem(this.autosaveKey);
        }
    },

    syncOrderFromDom(containerEl) {
        this.beginEdit('Reorder Blocks');
        const orderedUids = Array.from(containerEl.querySelectorAll('.block-wrapper')).map(node => node.dataset.uid);
        const blockMap = new Map(this.blocks.map(b => [b._uid, b]));
        this.blocks = orderedUids.map(uid => blockMap.get(uid)).filter(Boolean);
        this.persistToLocalStorage();
    },

    removePreviewItem(item) {
        const previewStore = Alpine.store('modals').preview;
        // Reassign rather than splice: a block's cached preview can share this array.
        previewStore.items = previewStore.items.filter(i => i !== item);
        previewStore.removedCount = (previewStore.removedCount || 0) + 1;
    },

    syncPreviewOrder(containerEl) {
        const previewStore = Alpine.store('modals').preview;
        const orderedIds = Array.from(containerEl.querySelectorAll('li[data-id]')).map(node => node.dataset.id);
        const itemMap = new Map(previewStore.items.map(item => [String(item.Id || item.id), item]));
        previewStore.items = orderedIds.map(id => itemMap.get(id)).filter(Boolean);
    },

    getTvBlockSummary(block) {
        if (!block || (block.type !== BLOCK_TYPES.TV && block.type !== BLOCK_TYPES.VIBE) || !block.shows) return '';
        let modeText = (block.mode === 'count') ? `${block.count || 1} eps per show` : 'to specific end episode';
        return modeText + (block.interleave ? ' • Interleaved' : ' • Sequential');
    },

    getTvShowList(block) {
        if (!block?.shows?.length) return 'No shows selected';
        const names = block.shows.map(s => {
            if (s.name) return s.name;
            if (s.id) {
                const libMatch = this.library.seriesData.find(ls => ls.id === s.id);
                return libMatch ? libMatch.name : 'Show ID: ' + s.id;
            }
            return 'Unknown';
        }).filter(n => n !== '');
        return names.length ? names.join(', ') : 'Empty selection';
    },

    async fetchEpisodeTitle(showData) {
        const series = this.library.seriesData.find(s => s.name === showData.name || s.id === showData.id);
        if (!series || !showData.season || !showData.episode) return;

        showData._loadingTitle = true;
        try {
            const res = await useApi(api.get(`api/episode_lookup?series_id=${series.id}&season=${showData.season}&episode=${showData.episode}`), null, true, false);
            if (res && res.data?.name) {
                showData.previewTitle = res.data.name;
                if (res.data.season !== undefined) showData.season = res.data.season;
                if (res.data.episode !== undefined) showData.episode = res.data.episode;
            } else {
                showData.previewTitle = `S${showData.season}E${showData.episode}`;
            }
        } catch (e) {
            showData.previewTitle = '';
        } finally {
            showData._loadingTitle = false;
        }
    },

    async syncNextUnwatched(showData) {
        const series = this.library.seriesData.find(s => s.name === showData.name || s.id === showData.id);
        const uid = Alpine.store('settings').activeUserId;
        if (!series || !uid) return;

        showData._loadingTitle = true;
        try {
            const res = await useApi(api.get(`api/shows/${series.id}/first_unwatched?user_id=${uid}`), null, true, false);
            if (res && res.data?.Id) {
                showData.season = res.data.ParentIndexNumber;
                showData.episode = res.data.IndexNumber;
                showData.previewTitle = res.data.Name || `S${res.data.ParentIndexNumber}E${res.data.IndexNumber}`;
            }
        } catch (e) {
        } finally {
            showData._loadingTitle = false;
        }
    },

    async promptResetWatch(showData) {
        const series = this.library.seriesData.find(s => s.name === showData.name || s.id === showData.id);
        const uid = Alpine.store('settings').activeUserId;
        if (!series || !uid) return toast("Select a show.", false);
        
        try {
            const decision = await resetWatchModal.show({ showName: series.name, season: showData.season });
            const payload = {
                user_id: uid,
                season_number: decision.scope === 'season' ? showData.season : null
            };
            const res = await useApi(api.post(`api/shows/${series.id}/unplayed`, payload));
            if (res.status === 'ok') {
                showData.unwatched = true;
                await this.syncNextUnwatched(showData);
            }
        } catch (e) { console.error(e); }
    },

    async fetchSuggestions(type, query) {
        if (!query || query.length < 2) return [];
        try {
            if (type === 'genre') {
                return (this.library.movieGenreData || [])
                    .filter(g => g.Name.toLowerCase().includes(query.toLowerCase()))
                    .map(g => ({ type: 'genre', data: g, text: g.Name }));
            }
            if (type === 'person') {
                const [people, studios] = await Promise.all([
                    useApi(api.get(`api/people?name=${encodeURIComponent(query)}`), null, true, false),
                    useApi(api.get(`api/studios?name=${encodeURIComponent(query)}`), null, true, false)
                ]);
                const results = [];
                if (Array.isArray(people.data)) people.data.forEach(p => results.push({ type: 'person', data: p, text: `${p.Name} (${p.Role || 'Person'})` }));
                if (Array.isArray(studios.data)) studios.data.forEach(s => results.push({ type: 'studio', data: s, text: `${s.Name} (Studio)` }));
                return results;
            }
            if (type === 'media') {
                 return await this.fetchMediaSuggestions(query);
            }
        } catch (e) { return []; }
    },

    async fetchMediaSuggestions(query) {
        if (!query || query.length < 2) return [];
        try {
            const res = await useApi(api.get(`api/media/search?query=${encodeURIComponent(query)}`), null, true, false);
            return Array.isArray(res?.data) ? res.data : [];
        } catch (e) { return []; }
    },

    async fetchItemChildren(itemId) {
        if (!itemId) return [];
        const uid = Alpine.store('settings').activeUserId;
        try {
            const res = await useApi(api.get(`api/items/${itemId}/children?user_id=${uid}`), null, true, false);
            return Array.isArray(res?.data) ? res.data : [];
        } catch (e) { return []; }
    },

    async loadArtistAlbums(artistId) {
        if (!artistId) return [];
        try {
            const res = await useApi(api.get(`api/music/artists/${artistId}/albums`), null, true, false);
            return Array.isArray(res?.data) ? res.data : [];
        } catch (e) { return []; }
    },

    addToken(block, type, itemData, role = 'Person') {
        const f = block.filters;
        if (type === 'genre' && !f.genres_any.includes(itemData.Name)) f.genres_any.push(itemData.Name);
        else if (type === 'person') {
            const person = { ...itemData, Role: role };
            if (!f.people.some(p => p.Id === person.Id && p.Role === role) &&
                !f.people_all.some(p => p.Id === person.Id && p.Role === role)) {
                f.people.push(person);
            }
        } else if (type === 'studio' && !f.studios.includes(itemData.Name)) f.studios.push(itemData.Name);
        
        this.updatePreviewCount(block);
    },

    removeToken(block, key, index) {
        if (block.filters[key]) {
            block.filters[key].splice(index, 1);
            this.updatePreviewCount(block);
        }
    },

    cycleTokenState(block, key, item) {
        if (!block || !item) return;
        const sourceArray = block.filters[key];
        const index = sourceArray.indexOf(item);
        if (index === -1) return;

        const clonedItem = JSON.parse(JSON.stringify(item));
        clonedItem.Id = clonedItem.Id || clonedItem.id;
        sourceArray.splice(index, 1);

        let nextKey;
        if (key.startsWith('genres_')) nextKey = { genres_any: 'genres_all', genres_all: 'genres_exclude', genres_exclude: 'genres_any' }[key];
        else if (key.includes('people')) nextKey = { people: 'people_all', people_all: 'exclude_people', exclude_people: 'people' }[key];
        else if (key.includes('studios')) nextKey = { studios: 'exclude_studios', exclude_studios: 'studios' }[key];

        if (nextKey) block.filters[nextKey].push(clonedItem);
        this.updatePreviewCount(block);
    },

    cycleEchoToken(block, key, item) {
        if (!block || !item) return;
        const sourceArray = block.filters[key];
        const index = sourceArray.indexOf(item);
        if (index === -1) return;

        const clonedItem = JSON.parse(JSON.stringify(item));
        sourceArray.splice(index, 1);

        const nextKey = (key === 'seeds_positive') ? 'seeds_negative' : 'seeds_positive';
        block.filters[nextKey].push(clonedItem);
        this.updatePreviewCount(block);
    },

    async updatePreviewCount(block) {
        if (!block) return;
        
        if (block.isSnapshot && block.filters?.ids?.length > 0) {
            block._previewCount = block.filters.ids.length;
            this.blocks = [...this.blocks];
            return;
        }

        if (block.type === BLOCK_TYPES.TV && !block.vibe_type) {
            const showCount = (block.shows || []).filter(s => s.name || s.id).length;
            const epsPerShow = parseInt(block.count || 0);
            block._previewCount = showCount * epsPerShow;
            this.blocks = [...this.blocks];
            return;
        }

        if (!this._previewDebouncers[block._uid]) {
            this._previewDebouncers[block._uid] = debounce(async (targetUid) => {
                const user_id = Alpine.store('settings').activeUserId;
                if (!user_id) return;

                const liveBlock = this.blocks.find(b => b._uid === targetUid);
                if (!liveBlock) return;

                liveBlock._previewLoading = true;
                try {
                    const res = await useApi(api.post('api/builder/preview', { user_id, blocks: [liveBlock] }), null, true, false);
                    if (res && res.status !== 'error') {
                        liveBlock._previewItems = res.data?.data || [];
                        liveBlock._previewCount = liveBlock._previewItems.length;
                        liveBlock._previewDuration = res.data?.total_duration_formatted || '';
                        liveBlock._previewTicks = res.data?.total_duration_ticks || 0;
                    } else {
                        liveBlock._previewItems = [];
                        liveBlock._previewCount = 0;
                        liveBlock._previewDuration = '';
                        liveBlock._previewTicks = 0;
                    }
                } catch (e) {
                    liveBlock._previewCount = 0;
                    liveBlock._previewItems = [];
                    liveBlock._previewDuration = '';
                    liveBlock._previewTicks = 0;
                } finally {
                    liveBlock._previewLoading = false;
                    this.blocks = [...this.blocks];
                }
            }, 800);
        }

        this._previewDebouncers[block._uid](block._uid);
    },

    async refreshUserPlaylists() {
        const uid = Alpine.store('settings').activeUserId;
        if (!uid) return;
        try {
            const res = await useApi(api.get(`api/users/${uid}/playlists`));
            if (Array.isArray(res.data)) this.userPlaylists = res.data;
        } catch (e) { console.error("Failed to load user playlists", e); }
    },

    async loadBlocks(blocksData = [], append = false, mixOptions = null) {
        const overlay = document.getElementById('loading-overlay');
        if (overlay) overlay.classList.remove('hidden');

        try {
            if (!Array.isArray(blocksData)) blocksData = [];
            blocksData.forEach(b => this.ensureBlockState(b));

            if (mixOptions) {
                this.mix_options = normalizeMixOptions(mixOptions);
            }
            
            const uid = Alpine.store('settings').activeUserId;
            const promises = [];

            blocksData.forEach(block => {
                const isTv = block.type === BLOCK_TYPES.TV || (block.type === BLOCK_TYPES.VIBE && block.vibe_type === BLOCK_TYPES.TV) || block.type === BLOCK_TYPES.CURATED;
                if (isTv && uid) {
                    block.shows.forEach(show => {
                        if (show.unwatched) {
                            const series = this.library.seriesData.find(s => s.name === show.name || s.id === show.id);
                            if (series) {
                                const p = useApi(api.get(`api/shows/${series.id}/first_unwatched?user_id=${uid}`))
                                    .then(res => { 
                                        if (res.data && res.data.Id) {
                                            show.season = res.data.ParentIndexNumber;
                                            show.episode = res.data.IndexNumber;
                                            show.previewTitle = res.data.Name || '';
                                        } 
                                    });
                                promises.push(p);
                            }
                        } else if ((show.name || show.id) && show.season && show.episode) {
                            promises.push(this.fetchEpisodeTitle(show));
                        }
                    });
                }
                
                if (block.isSnapshot && block.filters?.ids?.length > 0) {
                     const p = useApi(api.post('api/builder/preview', { user_id: uid, blocks: [block], mix_options: this.mix_options }), null, true, false)
                        .then(res => {
                            if(res.status === 'ok') {
                                block._previewItems = res.data.data;
                                block._previewCount = res.data.data.length;
                            }
                        });
                     promises.push(p);
                } else {
                     promises.push(this.updatePreviewCount(block));
                }
            });

            await Promise.all(promises);
            this.blocks = append ? [...this.blocks, ...blocksData] : [...blocksData];
            this.markSaved();

        } catch (e) {
            console.error("[MixerBee] loadBlocks failed:", e);
            toast("Load failed.", false);
        } finally {
            if (overlay) overlay.classList.add('hidden');
        }
    },

    addBlock(type) {
        this.beginEdit('Add block');
        const block = createNewBlock(type, this.library.libraryData);
        if (block) {
            this.blocks = [...this.blocks, block];
            this.updatePreviewCount(block);
        }
    },

    duplicateBlock(index) {
        this.beginEdit('Duplicate block');
        const copy = JSON.parse(JSON.stringify(this.blocks[index]));
        copy._uid = generateUUID();
        copy.block_id = generateUUID();
        if (copy.shows) copy.shows.forEach(s => s._uid = generateUUID());
        
        const newBlocks = [...this.blocks];
        newBlocks.splice(index + 1, 0, copy);
        this.blocks = newBlocks;
        this.updatePreviewCount(copy);
    },

    deleteBlock(index) {
        const removed = this.blocks[index];
        this.beginEdit('Delete block');
        this.blocks = this.blocks.filter((_, i) => i !== index);
        const label = removed?.title || 'Block';
        // Undo only while the delete is still the latest edit; otherwise it would revert something newer.
        const depthAfterDelete = this.past.length;
        toast(`Deleted "${label}".`, true, {
            actionText: 'Undo', actionIcon: 'undo',
            actionCallback: () => {
                if (this.past.length === depthAfterDelete) this.undo();
                else toast('Other edits happened since — use the Undo button to step back.', false);
            }
        });
    },

    resetMovieFilters(block) {
        if (!block || block.isSnapshot) return;
        this.beginEdit('Reset filters');
        const fresh = createNewBlock(BLOCK_TYPES.MOVIE, this.library.libraryData);
        block.filters = fresh.filters;
        block._limitMode = 'none';
        this.updatePreviewCount(block);
    },

    // Active movie constraints, listed as things to loosen when a block matches nothing.
    activeFilterHints(block) {
        const f = block?.filters || {};
        const hints = [];
        const count = (k) => (f[k] || []).length;
        if (count('genres_all') > 1) hints.push(`requiring all of ${count('genres_all')} genres`);
        if (count('people_all') > 1) hints.push(`requiring all of ${count('people_all')} people`);
        if (count('genres_any')) hints.push('genres');
        if (count('people') || count('studios')) hints.push('people/studios');
        if (f.watched_status && f.watched_status !== 'all') hints.push(f.watched_status === 'unplayed' ? 'unplayed only' : 'played only');
        if (f.favorites_only) hints.push('favorites only');
        if (f.min_community_rating) hints.push(`rating ${f.min_community_rating}+`);
        if (f.min_runtime_minutes || f.max_runtime_minutes) hints.push('runtime');
        if (count('allowed_content_ratings')) hints.push('content ratings');
        if (count('audio_languages')) hints.push('audio language');
        if (count('subtitle_languages')) hints.push('subtitle language');
        if (f.release_within_days > 0) hints.push('release window');
        else if (f.year_from > 1920 || (f.year_to && f.year_to < new Date().getFullYear())) hints.push('year range');
        const libs = (this.library.libraryData || []).length;
        if (libs && f.parent_ids?.length && f.parent_ids.length < libs) hints.push('libraries');
        return hints;
    },

    setAllBlocksOpen(open) {
        window.dispatchEvent(new CustomEvent('mixer-blocks-toggle', { detail: { open } }));
    },

    // Name used when building without typing one: the loaded preset's name, if any.
    defaultBuildName() {
        return Alpine.store('presets').currentName || (this.createAsCollection ? 'My Collection' : 'My Mix');
    },

    buildSummary() {
        const blocks = this.blocks || [];
        if (!blocks.length) return null;
        const loading = blocks.some(b => b._previewLoading);
        const items = blocks.reduce((sum, b) => sum + (Number(b._previewCount) || 0), 0);
        const ticks = blocks.reduce((sum, b) => sum + (Number(b._previewTicks) || 0), 0);
        const partial = blocks.some(b => !b._previewTicks && (Number(b._previewCount) || 0) > 0);
        let duration = '';
        if (ticks > 0) {
            const totalMin = Math.round(ticks / 600000000);
            const h = Math.floor(totalMin / 60), m = totalMin % 60;
            duration = (h ? `${h}h ${m}m` : `${m}m`) + (partial ? '+' : '');
        }
        return { items, duration, loading, blocks: blocks.length };
    },

    async clearAllBlocks() {
        try {
            await confirmModal.show({ title: 'Clear All?', text: 'Remove all blocks?', confirmText: 'Clear' });
            this.beginEdit('Clear all');
            this.blocks = [];
            Alpine.store('presets').currentName = '';
        } catch (e) { }
    },

    addShowRow(blockIndex) {
        const block = this.blocks[blockIndex];
        const def = { name: '', season: 1, episode: 1, count: 1, unwatched: true, previewTitle: '', _uid: generateUUID() };
        block.shows.push(def);
        this.updatePreviewCount(block);
    },

    deleteShowRow(blockIndex, rowIndex) {
        const block = this.blocks[blockIndex];
        block.shows.splice(rowIndex, 1);
        this.updatePreviewCount(block);
    },

    getPreparedBlocks(blocksOverride = null, lockInPreview = false) {
        const rawBlocks = blocksOverride || this.blocks;
        return JSON.parse(JSON.stringify(rawBlocks)).map(block => {
            if (lockInPreview && !block.isSnapshot && block._previewItems && block._previewItems.length > 0) {
                if (!block.filters) block.filters = {};
                block.filters.ids = block._previewItems.map(item => item.Id || item.id);
            }
            return block;
        });
    },

    async reselectBlock(blockUid) {
        const block = this.blocks.find(b => b._uid === blockUid);
        if (!block) return;
        this.beginEdit('Re-roll Block Candidates');
        block._previewItems = null;
        block._previewDuration = '';
        block._stale = false;
        if (!block.isSnapshot && block.filters && block.filters.ids) {
            delete block.filters.ids;
        }
        await this.updatePreviewCount(block);
        toast(`Re-rolled selection for "${block.title || 'Block'}"`);
    },

    async previewPlaylist(btnEl, blocksOverride = null) {
        try {
            if (blocksOverride && blocksOverride.length === 1) {
                const cachedBlock = blocksOverride[0];
                if (cachedBlock._previewItems && cachedBlock._previewItems.length > 0) {
                    return await previewModal.show({
                        items: cachedBlock._previewItems,
                        title: `${cachedBlock.title || 'Block'} Preview`,
                        parentBlockUid: cachedBlock._uid,
                        totalDuration: cachedBlock._previewDuration || ''
                    });
                }
            }

            const targetBlocks = this.getPreparedBlocks(blocksOverride);
            if (targetBlocks.length === 0) return toast('No content to preview.', false);

            const uid = Alpine.store('settings').activeUserId;
            const res = await useApi(api.post('api/builder/preview', {
                user_id: uid,
                blocks: targetBlocks,
                mix_options: this.mix_options
            }), btnEl, true);

            if (res.status === 'ok') {
                await previewModal.show({
                    items: res.data.data,
                    title: 'Full Playlist Preview',
                    parentBlockUid: null,
                    totalDuration: res.data.total_duration_formatted || ''
                });
            }
        } catch (err) {
            if (err.message !== 'Modal cancelled by user.') console.error("[MixerBee] Preview modal error:", err);
        }
    },

    async buildPlaylist(btnEl) {
        if (this.blocks.length === 0) return toast('Add a block.', false);
        const uid = Alpine.store('settings').activeUserId;
        const preparedBlocks = this.getPreparedBlocks();

        if (this.createAsCollection && !Alpine.store('settings').can_manage_collections) {
            this.createAsCollection = false;
            return toast('This media account cannot manage collections. Build a playlist instead.', false);
        }

        if (this.buildMode === 'add') {
            if (!this.existingPlaylistId) return toast("Select playlist.", false);
            await useApi(api.post(`api/playlists/${this.existingPlaylistId}/add-items`, {
                user_id: uid,
                blocks: preparedBlocks,
                mix_options: this.mix_options
            }), btnEl, false, true);
        } else {
            if (this.createAsCollection && (preparedBlocks.length !== 1 || (preparedBlocks[0].type !== BLOCK_TYPES.MOVIE && preparedBlocks[0].vibe_type !== BLOCK_TYPES.MOVIE))) {
                return toast('Requires one Movie block.', false);
            }
            try {
                // The inline name field (or the loaded preset's name) skips the naming dialog.
                const playlistName = this.playlistName.trim() || this.defaultBuildName();
                await useApi(api.post('api/create_mixed_playlist', {
                    user_id: uid,
                    playlist_name: playlistName,
                    blocks: preparedBlocks,
                    create_as_collection: this.createAsCollection,
                    mix_options: this.mix_options
                }), btnEl, false, true);
            } catch (err) { }
        }
    },

    async buildFromPreview(btnEl) {
        const previewStore = Alpine.store('modals').preview;
        const previewItems = previewStore.items;
        if (!previewItems || previewItems.length === 0) return;

        const uid = Alpine.store('settings').activeUserId;
        
        if (previewStore.parentBlockUid) {
            const block = this.blocks.find(b => b._uid === previewStore.parentBlockUid);
            if (block) {
                block._previewItems = [...previewItems];
                if (block.isSnapshot) {
                    if (!block.filters) block.filters = {};
                    block.filters.ids = previewItems.map(i => i.Id || i.id);
                }
            }
        }

        const itemIds = previewItems.map(i => i.Id || i.id);

        try {
            const { playlistName } = await smartPlaylistModal.show({
                title: 'Name Custom Order',
                description: 'Build playlist from this preview order.',
                countInput: false,
                defaultName: 'Custom Preview Mix'
            });

            await useApi(api.post('api/create_mixed_playlist', {
                user_id: uid,
                playlist_name: playlistName,
                item_ids: itemIds,
                create_as_collection: false,
                mix_options: this.mix_options
            }), btnEl, false, true);

            previewModal.close();
        } catch (e) { }
    },

    async showSmartBuildMenu() {
        try {
            const type = await smartBuildModal.show({ items: SMART_BUILD_TYPES });
            await this.handleSmartBuildSelection(type);
        } catch (e) { }
    },

    async handleSmartBuildSelection(type) {
        if (['artist_spotlight', 'genre_sampler', 'album_roulette'].includes(type)) {
            return await this.openMusicQuickBuild(type);
        }

        const config = {
            recently_added: { title: 'Recently Added', description: 'New media.', defaultName: 'Recently Added', defaultCount: 25 },
            next_up: { title: 'Next Up', description: 'In-progress shows.', defaultName: 'Next Up' },
            pilot_sampler: { title: 'Pilot Sampler', description: 'Random pilots.', defaultName: 'Pilot Sampler' },
            from_the_vault: { title: 'From the Vault', description: 'Favorite movies you haven\'t watched in a while.', defaultName: 'Forgotten favorites.', defaultCount: 20 },
            genre_roulette: { title: 'Genre Roulette', description: 'A movie marathon from a random genre.', defaultName: 'Genre Roulette', defaultCount: 10 },
            top_community_unwatched: { title: 'Top Community Rated', description: 'Highest community-rated movies you haven\'t seen.', defaultName: 'Community Favorites', defaultCount: 10 },
            top_critic_unwatched: { title: 'Top Critic Rated', description: 'Highest critic-rated movies you haven\'t seen.', defaultName: 'Critic Favorites', defaultCount: 10 },
        };

        if (config[type]) {
            if (type === 'genre_roulette') {
                const data = this.library.movieGenreData;
                if (!data?.length) return toast("Genre data not loaded.", false);
                const randomGenre = data[Math.floor(Math.random() * data.length)];
                await this.executeQuickBuild(type, {
                    title: `Roulette: ${randomGenre.Name}`,
                    description: `Random ${randomGenre.Name} movies.`,
                    defaultName: `Mix: ${randomGenre.Name}`,
                    defaultCount: 10,
                    extraParams: { genre: randomGenre.Name }
                });
            } else {
                await this.executeQuickBuild(type, config[type]);
            }
        }
    },

    async openMusicQuickBuild(type) {
        const uid = Alpine.store('settings').activeUserId;
        if (!uid) return toast("Active user required.", false);

        if (type === 'artist_spotlight') {
            const artists = this.library.artistData || [];
            if (artists.length === 0) return toast("No music artists found in library.", false);
            try {
                const result = await musicQuickBuildModal.show({
                    type: 'artist_spotlight',
                    title: 'Artist Spotlight',
                    playlistName: 'Artist Spotlight',
                    count: 25,
                    selectedArtistId: artists[0].Id || artists[0].id || ''
                });
                if (result) {
                    await this.submitMusicQuickBuild(type, result);
                }
            } catch (e) { }
        } else if (type === 'genre_sampler') {
            const genres = this.library.musicGenreData || [];
            if (genres.length === 0) return toast("No music genres found in library.", false);
            try {
                const result = await musicQuickBuildModal.show({
                    type: 'genre_sampler',
                    title: 'Music Genre Sampler',
                    playlistName: `Genre: ${genres[0].Name || genres[0].name}`,
                    count: 25,
                    selectedGenre: genres[0].Name || genres[0].name || ''
                });
                if (result) {
                    await this.submitMusicQuickBuild(type, result);
                }
            } catch (e) { }
        } else if (type === 'album_roulette') {
            try {
                const result = await musicQuickBuildModal.show({
                    type: 'album_roulette',
                    title: 'Album Roulette',
                    playlistName: 'Album Mix',
                    selectedAlbumId: '',
                    selectedAlbumName: '',
                    selectedArtistId: '',
                    albums: [],
                    loadingAlbums: false
                });
                if (result) {
                    await this.submitMusicQuickBuild(type, result);
                }
            } catch (e) { }
        }
    },

    async submitMusicQuickBuild(type, form) {
        const uid = Alpine.store('settings').activeUserId;
        const options = {};
        if (type === 'artist_spotlight') {
            if (!form.selectedArtistId) return toast("Select an artist.", false);
            options.artist_id = form.selectedArtistId;
            options.count = form.count || 25;
        } else if (type === 'genre_sampler') {
            if (!form.selectedGenre) return toast("Select a genre.", false);
            options.genre = form.selectedGenre;
            options.count = form.count || 25;
        } else if (type === 'album_roulette') {
            if (!form.selectedAlbumId) return toast("Choose an album first.", false);
            options.album_id = form.selectedAlbumId;
        }

        try {
            await useApi(api.post('api/quick_builds', {
                user_id: uid,
                playlist_name: form.playlistName || 'Music Mix',
                quick_build_type: type,
                options
            }));
        } catch (e) { }
    },

    async executeQuickBuild(type, { title, description, defaultName, showCount = true, defaultCount = 10, extraParams = {} }) {
        const uid = Alpine.store('settings').activeUserId;
        try {
            const { playlistName, count } = await smartPlaylistModal.show({ title, description, defaultName, countInput: showCount, defaultCount });
            const options = { ...extraParams };
            if (showCount) options.count = count;
            await useApi(api.post('api/quick_builds', { user_id: uid, playlist_name: playlistName, quick_build_type: type, options }));
        } catch (err) { }
    },

    async saveBlockAsRecipe(block) {
        if (!block) return;
        try {
            const data = await saveRecipeModal.show({
                name: block.title || (block.type.toUpperCase() + ' Recipe'),
                description: '',
                tags: '',
                is_favorite: false,
                blockToSave: block
            });
            if (!data || !data.name || !data.name.trim()) return;
            const serialized = serializeBlockDefinition(block);
            const tags = data.tags ? data.tags.split(',').map(t => t.trim()).filter(Boolean) : [];
            const payload = {
                name: data.name.trim(),
                description: data.description?.trim() || '',
                block_json: JSON.stringify(serialized),
                tags: tags,
                is_favorite: !!data.is_favorite
            };
            const res = await useApi(api.post('api/recipes', payload));
            if (res.status === 'ok') {
                toast(`Recipe "${data.name.trim()}" saved!`, true);
            }
        } catch (e) { }
    },

    async openRecipeLibrary() {
        try {
            const [recipesRes, startersRes] = await Promise.all([
                useApi(api.get('api/recipes'), null, true, false),
                useApi(api.get('api/recipes/starters'), null, true, false)
            ]);
            const recipes = Array.isArray(recipesRes?.data) ? recipesRes.data : [];
            const starters = Array.isArray(startersRes?.data) ? startersRes.data : [];

            const chosen = await recipeLibraryModal.show({
                recipes,
                starters,
                filterQuery: '',
                activeTab: 'saved'
            });

            if (chosen) {
                this.insertRecipe(chosen);
            }
        } catch (e) { }
    },

    insertRecipe(recipe) {
        if (!recipe || !recipe.block_json) return;
        this.beginEdit(`Insert Recipe: ${recipe.name}`);
        try {
            const blockDef = JSON.parse(recipe.block_json);
            blockDef._uid = generateUUID();
            blockDef.block_id = generateUUID();
            if (blockDef.shows) {
                blockDef.shows.forEach(s => s._uid = generateUUID());
            }
            this.ensureBlockState(blockDef);
            this.blocks.push(blockDef);
            this.updatePreviewCount(blockDef);
            toast(`Inserted "${recipe.name}"!`, true);
        } catch (e) {
            console.error("Failed to insert recipe:", e);
            toast("Could not insert recipe.", false);
        }
    },

    createEchoFromItem(item) {
        const block = createEchoBlock(item);
        this.blocks = [...this.blocks, block];
        this.updatePreviewCount(block);

        Alpine.store('ui').setTab('mixed');
        Alpine.store('modals').previewAction.close(null, true);
        Alpine.store('manager').contentsModal.isOpen = false;
        toast('Echo block created!', true);
    },

    snapshotFromPreview() {
        const previewStore = Alpine.store('modals').preview;
        const uid = previewStore.parentBlockUid;
        if (!uid) return;

        const block = this.blocks.find(b => b._uid === uid);
        if (block) {
            if (![BLOCK_TYPES.MOVIE, BLOCK_TYPES.MIRROR, BLOCK_TYPES.CURATED].includes(block.type)) {
                return toast('This block type does not support snapshotting.', false);
            }
            if (!block.filters) block.filters = {};
            block.filters.ids = previewStore.items.map(i => i.Id || i.id);
            block.isSnapshot = true;
            block._previewCount = block.filters.ids.length;
            block._previewItems = JSON.parse(JSON.stringify(previewStore.items));
            this.blocks = [...this.blocks];
            
            Alpine.store('modals').previewAction.close(null, true);
            toast('Order snapshotted to block!', true);
        }
    },

    unlockBlock(block) {
        if (!block) return;
        block.isSnapshot = false;
        if (block.filters) block.filters.ids = [];
        this.updatePreviewCount(block);
        this.blocks = [...this.blocks];
        toast('Block unlocked.', true);
    }
};
