// static/js/mixerStore.js

import { api } from './apiClient.js';
import { toast, debounce, generateUUID } from './utils.js';
import { ensureBlockState, createNewBlock, createEchoBlock } from './blockFactory.js';
import { confirmModal, smartBuildModal, smartPlaylistModal, previewModal, resetWatchModal } from './modals.js';
import { SMART_BUILD_TYPES, BLOCK_TYPES } from './definitions.js';

export const mixerStore = {
    blocks: [],
    library: {
        seriesData: [], movieGenreData: [], libraryData: [], artistData: [], musicGenreData: [], studioData: []
    },

    buildMode: 'create',
    createAsCollection: false,
    existingPlaylistId: '',
    userPlaylists: [],
    autosaveKey: 'mixerbee_autosave',

    _previewDebouncers: {},

    init() {
        try {
            const saved = localStorage.getItem(this.autosaveKey);
            if (saved) {
                const parsed = JSON.parse(saved);
                const loadedBlocks = parsed.blocks || [];
                loadedBlocks.forEach(b => this.ensureBlockState(b));
                this.blocks = loadedBlocks;
            }
        } catch (e) { console.error("Autosave restore failed:", e); }

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
            localStorage.setItem(this.autosaveKey, JSON.stringify({ blocks: this.blocks }));
        } else {
            localStorage.removeItem(this.autosaveKey);
        }
    },

    syncOrderFromDom(containerEl) {
        const orderedUids = Array.from(containerEl.querySelectorAll('.block-wrapper')).map(node => node.dataset.uid);
        const blockMap = new Map(this.blocks.map(b => [b._uid, b]));
        this.blocks = orderedUids.map(uid => blockMap.get(uid)).filter(Boolean);
        this.persistToLocalStorage();
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
            const res = await api.get(`api/episode_lookup?series_id=${series.id}&season=${showData.season}&episode=${showData.episode}`, true, false);
            if (res && res.name) {
                showData.previewTitle = res.name;
                if (res.season !== undefined) showData.season = res.season;
                if (res.episode !== undefined) showData.episode = res.episode;
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
            const res = await api.get(`api/shows/${series.id}/first_unwatched?user_id=${uid}`, true, false);
            if (res && res.Id) {
                showData.season = res.ParentIndexNumber;
                showData.episode = res.IndexNumber;
                showData.previewTitle = res.Name || `S${res.ParentIndexNumber}E${res.IndexNumber}`;
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
            const res = await api.post(`api/shows/${series.id}/unplayed`, payload);
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
                    api.get(`api/people?name=${encodeURIComponent(query)}`, true, false),
                    api.get(`api/studios?name=${encodeURIComponent(query)}`, true, false)
                ]);
                const results = [];
                if (Array.isArray(people)) people.forEach(p => results.push({ type: 'person', data: p, text: `${p.Name} (${p.Role || 'Person'})` }));
                if (Array.isArray(studios)) studios.forEach(s => results.push({ type: 'studio', data: s, text: `${s.Name} (Studio)` }));
                return results;
            }
            if (type === 'media') {
                 const res = await api.get(`api/media/search?query=${encodeURIComponent(query)}`, true, false);
                 return Array.isArray(res) ? res.map(m => ({ type: 'media', data: m, text: `${m.Name} (${m.Year || '?'})` })) : [];
            }
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
                    const itemsData = await api.post('api/builder/preview', { user_id, blocks: [liveBlock] }, null, true, false);
                    if (itemsData && itemsData.status !== 'error') {
                        liveBlock._previewItems = itemsData.data || [];
                        liveBlock._previewCount = liveBlock._previewItems.length;
                    } else {
                        liveBlock._previewItems = [];
                        liveBlock._previewCount = 0;
                    }
                } catch (e) {
                    liveBlock._previewCount = 0;
                    liveBlock._previewItems = [];
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
            const res = await api.get(`api/users/${uid}/playlists`, true);
            if (Array.isArray(res)) this.userPlaylists = res;
        } catch (e) { console.error("Failed to load user playlists", e); }
    },

    async loadBlocks(blocksData = [], append = false) {
        const overlay = document.getElementById('loading-overlay');
        if (overlay) overlay.classList.remove('hidden');

        try {
            if (!Array.isArray(blocksData)) blocksData = [];
            blocksData.forEach(b => this.ensureBlockState(b));
            
            const uid = Alpine.store('settings').activeUserId;
            const promises = [];

            blocksData.forEach(block => {
                const isTv = block.type === BLOCK_TYPES.TV || (block.type === BLOCK_TYPES.VIBE && block.vibe_type === BLOCK_TYPES.TV) || block.type === BLOCK_TYPES.CURATED;
                if (isTv && uid) {
                    block.shows.forEach(show => {
                        if (show.unwatched) {
                            const series = this.library.seriesData.find(s => s.name === show.name || s.id === show.id);
                            if (series) {
                                const p = api.get(`api/shows/${series.id}/first_unwatched?user_id=${uid}`, true)
                                    .then(ep => { 
                                        if (ep && ep.Id) {
                                            show.season = ep.ParentIndexNumber;
                                            show.episode = ep.IndexNumber;
                                            show.previewTitle = ep.Name || '';
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
                     const p = api.post('api/builder/preview', { user_id: uid, blocks: [block] }, null, true, false)
                        .then(res => {
                            if(res.status === 'ok') {
                                block._previewItems = res.data;
                                block._previewCount = res.data.length;
                            }
                        });
                     promises.push(p);
                } else {
                     promises.push(this.updatePreviewCount(block));
                }
            });

            await Promise.all(promises);
            this.blocks = append ? [...this.blocks, ...blocksData] : [...blocksData];

        } catch (e) {
            console.error("[MixerBee] loadBlocks failed:", e);
            toast("Load failed.", false);
        } finally {
            if (overlay) overlay.classList.add('hidden');
        }
    },

    addBlock(type) {
        const block = createNewBlock(type, this.library.libraryData);
        if (block) {
            this.blocks = [...this.blocks, block];
            this.updatePreviewCount(block);
        }
    },

    duplicateBlock(index) {
        const copy = JSON.parse(JSON.stringify(this.blocks[index]));
        copy._uid = generateUUID();
        if (copy.shows) copy.shows.forEach(s => s._uid = generateUUID());
        
        const newBlocks = [...this.blocks];
        newBlocks.splice(index + 1, 0, copy);
        this.blocks = newBlocks;
    },

    deleteBlock(index) {
        this.blocks = this.blocks.filter((_, i) => i !== index);
    },

    async clearAllBlocks() {
        try {
            await confirmModal.show({ title: 'Clear All?', text: 'Remove all blocks?', confirmText: 'Clear' });
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

    getPreparedBlocks(blocksOverride = null) {
        const rawBlocks = blocksOverride || this.blocks;
        return JSON.parse(JSON.stringify(rawBlocks)).map(block => {
            if (!block.isSnapshot && block._previewItems && block._previewItems.length > 0) {
                if (!block.filters) block.filters = {};
                block.filters.ids = block._previewItems.map(item => item.Id || item.id);
            }
            return block;
        });
    },

    async previewPlaylist(btnEl, blocksOverride = null) {
        try {
            if (blocksOverride && blocksOverride.length === 1) {
                const cachedBlock = blocksOverride[0];
                if (cachedBlock._previewItems && cachedBlock._previewItems.length > 0) {
                    return await previewModal.show({
                        items: cachedBlock._previewItems,
                        title: `${cachedBlock.title || 'Block'} Preview`,
                        parentBlockUid: cachedBlock._uid 
                    });
                }
            }

            const targetBlocks = this.getPreparedBlocks(blocksOverride);
            if (targetBlocks.length === 0) return toast('No content to preview.', false);

            const uid = Alpine.store('settings').activeUserId;
            const res = await api.post('api/builder/preview', { user_id: uid, blocks: targetBlocks }, btnEl, true);

            if (res.status === 'ok') {
                await previewModal.show({
                    items: res.data,
                    title: 'Full Playlist Preview',
                    parentBlockUid: null
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

        if (this.buildMode === 'add') {
            if (!this.existingPlaylistId) return toast("Select playlist.", false);
            await api.post(`api/playlists/${this.existingPlaylistId}/add-items`, { user_id: uid, blocks: preparedBlocks }, btnEl);
        } else {
            if (this.createAsCollection && (preparedBlocks.length !== 1 || (preparedBlocks[0].type !== BLOCK_TYPES.MOVIE && preparedBlocks[0].vibe_type !== BLOCK_TYPES.MOVIE))) {
                return toast('Requires one Movie block.', false);
            }
            try {
                const { playlistName } = await smartPlaylistModal.show({
                    title: this.createAsCollection ? 'Name Collection' : 'Name Playlist',
                    description: 'Provide a name.',
                    countInput: false,
                    defaultName: this.createAsCollection ? 'My Collection' : 'My Mix',
                });
                await api.post('api/create_mixed_playlist', { user_id: uid, playlist_name: playlistName, blocks: preparedBlocks, create_as_collection: this.createAsCollection }, btnEl);
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

            await api.post('api/create_mixed_playlist', {
                user_id: uid,
                playlist_name: playlistName,
                item_ids: itemIds,
                create_as_collection: false
            }, btnEl);

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

    async executeQuickBuild(type, { title, description, defaultName, showCount = true, defaultCount = 10, extraParams = {} }) {
        const uid = Alpine.store('settings').activeUserId;
        try {
            const { playlistName, count } = await smartPlaylistModal.show({ title, description, defaultName, countInput: showCount, defaultCount });
            const options = { ...extraParams };
            if (showCount) options.count = count;
            await api.post('api/quick_builds', { user_id: uid, playlist_name: playlistName, quick_build_type: type, options });
        } catch (err) { }
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