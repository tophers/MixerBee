/* static/js/mixerStore.js */

import { post, toast, debounce, generateUUID } from './utils.js';
import { confirmModal, smartBuildModal, smartPlaylistModal, previewModal, resetWatchModal, aiTweaksModal } from './modals.js';
import { SMART_BUILD_TYPES } from './definitions.js';

export const mixerStore = {
    blocks: [],
    library: {
        seriesData: [],
        movieGenreData: [],
        libraryData: [],
        artistData: [],
        musicGenreData: [],
        studioData: [],
    },

    buildMode: 'create',
    createAsCollection: false,
    existingPlaylistId: '',
    userPlaylists: [],

    aiPrompt: '',
    isAiGenerating: false,
    autosaveKey: 'mixerbee_autosave',

    aiTweaks: {
        threshold: 0.65,
        limit: 25,
        strictness: 'genre_verified',
        temperature: 0.2,
        target_size: 10,
        only_unwatched: false,
        system_prompt: ''
    },

    moodPool: [],
    activeMoods: [],
    samplePrompt: '',
    isMoodLoading: false,

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
        } catch (e) {
            console.error("Autosave restore failed:", e);
        }

         Alpine.watch(() => Alpine.store('settings').activeUserId, (uid) => {
            if (uid && this.moodPool.length === 0 && !this.isMoodLoading) {
                this.fetchMoodDiscovery();
            }
        });

        const sStore = Alpine.store('settings');
        if (sStore && sStore.activeUserId) {
            this.fetchMoodDiscovery();
        }

        Alpine.watch(() => JSON.stringify(this.blocks), () => this.persistToLocalStorage());
    },

    ensureBlockState(block) {
        if (!block) return;
        if (!block._uid) block._uid = generateUUID();

        if (block._previewCount === undefined) block._previewCount = 0;
        if (block._previewItems === undefined) block._previewItems = [];
        if (block._previewLoading === undefined) block._previewLoading = false;

        const isStandardMovie = block.type === 'movie';
        const isVibeMovie = (block.type === 'vibe' && block.vibe_type === 'movie');

        if (isStandardMovie || isVibeMovie) {
            if (!block.filters) block.filters = {};

            if (isStandardMovie && (!block.filters.parent_ids || block.filters.parent_ids.length === 0)) {
                block.filters.parent_ids = this.library.libraryData.map(l => l.Id);
            }

            block.filters.genres_any = block.filters.genres_any ?? [];
            block.filters.genres_all = block.filters.genres_all ?? [];
            block.filters.genres_exclude = block.filters.genres_exclude ?? [];
            block.filters.people = block.filters.people ?? [];
            block.filters.people_all = block.filters.people_all ?? [];
            block.filters.exclude_people = block.filters.exclude_people ?? [];
            block.filters.studios = block.filters.studios ?? [];
            block.filters.exclude_studios = block.filters.exclude_studios ?? [];
            block.filters.watched_status = block.filters.watched_status ?? 'all';
            block.filters.sort_by = block.filters.sort_by ?? 'Random';
            block.filters.year_from = block.filters.year_from ?? 1900;
            block.filters.year_to = block.filters.year_to ?? new Date().getFullYear() + 2;
            block.filters.release_within_days = block.filters.release_within_days ?? 0;
            block.filters.ids = block.filters.ids ?? [];

            block._limitMode = block._limitMode ?? (block.filters.duration_minutes ? 'duration' : 'count');
            block._limitDurationUnit = block._limitDurationUnit ?? 60;
            if (block._limitDurationRaw === undefined) {
                block._limitDurationRaw = block.filters.duration_minutes ? Math.round(block.filters.duration_minutes / 60) : 3;
            }
        }

        if (block.type === 'music') {
            if (!block.music) block.music = { mode: 'album', count: 10 };
            if (!block.music.filters) block.music.filters = { sort_by: 'Random', limit: 25, genres: [], genre_match: 'any' };
        }

        if (block.type === 'mirror') {
            if (!block.filters) block.filters = {};

            if (block.seedId && (!block.filters.seeds_positive || block.filters.seeds_positive.length === 0)) {
                block.filters.seeds_positive = [{ Id: block.seedId, Name: block.seedName }];
                delete block.seedId;
                delete block.seedName;
            }

            block.filters.seeds_positive = block.filters.seeds_positive ?? [];
            block.filters.seeds_negative = block.filters.seeds_negative ?? [];
            block.filters.mixed_echo = block.filters.mixed_echo ?? false;
            block.filters.include_seeds = block.filters.include_seeds ?? false;
            block.limit = block.limit ?? 10;
            block.threshold = block.threshold ?? 0.65;
        }

        if (block.type === 'tv' || (block.type === 'vibe' && block.vibe_type === 'tv')) {
            if (!block.shows) block.shows = [];
            block.shows.forEach(s => {
                if (!s._uid) s._uid = generateUUID();

                if (!s.name && s.id) {
                    const seriesMatch = this.library.seriesData.find(ls => String(ls.id) === String(s.id));
                    if (seriesMatch) s.name = seriesMatch.name;
                }

                if (s.season === undefined) s.season = 1;
                if (s.episode === undefined) s.episode = 1;

                s.previewTitle = s.previewTitle ?? '';
                s._loadingTitle = false;
            });
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
        // Collect UIDs from the actual DOM elements in their new visual order
        const orderedUids = Array.from(containerEl.querySelectorAll('.block-wrapper')).map(node => node.dataset.uid);
        
        // Map current block objects by their UID for fast lookup
        const blockMap = new Map(this.blocks.map(b => [b._uid, b]));
        
        // Create new array based on visual DOM sequence
        const newBlocks = orderedUids.map(uid => blockMap.get(uid)).filter(Boolean);
        
        // Critical: Update the store reference to trigger reactivity/persistence
        this.blocks = newBlocks;
        this.persistToLocalStorage();
    },

    syncPreviewOrder(containerEl) {
        const previewStore = Alpine.store('modals').preview;
        const orderedIds = Array.from(containerEl.querySelectorAll('li[data-id]')).map(node => node.dataset.id);
        const itemMap = new Map(previewStore.items.map(item => [String(item.Id || item.id), item]));
        
        const newItems = orderedIds.map(id => itemMap.get(id)).filter(Boolean);
        previewStore.items = newItems;
    },

    getTvBlockSummary(block) {
        if (!block || (block.type !== 'tv' && block.type !== 'vibe') || !block.shows) return '';
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

        if (!names.length) return 'Empty selection';
        return names.join(', ');
    },

    async fetchEpisodeTitle(showData) {
        const series = this.library.seriesData.find(s => s.name === showData.name || s.id === showData.id);
        if (!series || !showData.season || !showData.episode) return;

        showData._loadingTitle = true;
        try {
            const res = await post(`api/episode_lookup?series_id=${series.id}&season=${showData.season}&episode=${showData.episode}`, null, null, 'GET', true);
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
            const res = await post(`api/shows/${series.id}/first_unwatched?user_id=${uid}`, null, null, 'GET', true);
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
            const res = await post(`api/shows/${series.id}/unplayed`, payload);
            if (res.status === 'ok') {
                showData.unwatched = true;
                await this.syncNextUnwatched(showData);
            }
        } catch (e) {}
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
                    post(`api/people?name=${encodeURIComponent(query)}`, null, null, 'GET', true, false),
                    post(`api/studios?name=${encodeURIComponent(query)}`, null, null, 'GET', true, false)
                ]);
                const results = [];
                if (Array.isArray(people)) {
                    people.forEach(p => results.push({ type: 'person', data: p, text: `${p.Name} (${p.Role || 'Person'})` }));
                }
                if (Array.isArray(studios)) {
                     studios.forEach(s => results.push({ type: 'studio', data: s, text: `${s.Name} (Studio)` }));
                }
                return results;
            }
            if (type === 'media') {
                 const res = await post(`api/media/search?query=${encodeURIComponent(query)}`, null, null, 'GET', true, false);
                 if (Array.isArray(res)) {
                     return res.map(m => ({ type: 'media', data: m, text: `${m.Name} (${m.Year || '?'})` }));
                 }
                 return [];
            }
        } catch (e) { return []; }
    },

    addToken(block, type, itemData, role = 'Person') {
        const f = block.filters;
        if (type === 'genre') {
            if (!f.genres_any.includes(itemData.Name)) f.genres_any.push(itemData.Name);
        } else if (type === 'person') {
            const person = { ...itemData, Role: role };
            if (!f.people.some(p => p.Id === person.Id && p.Role === role) &&
                !f.people_all.some(p => p.Id === person.Id && p.Role === role)) {
                f.people.push(person);
            }
        } else if (type === 'studio') {
            if (!f.studios.includes(itemData.Name)) f.studios.push(itemData.Name);
        }
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
        if (key.startsWith('genres_')) {
            const map = { genres_any: 'genres_all', genres_all: 'genres_exclude', genres_exclude: 'genres_any' };
            nextKey = map[key];
        } else if (key.includes('people')) {
            const map = { people: 'people_all', people_all: 'exclude_people', exclude_people: 'people' };
            nextKey = map[key];
        } else if (key.includes('studios')) {
            const map = { studios: 'exclude_studios', exclude_studios: 'studios' };
            nextKey = map[key];
        }

        if (nextKey) {
            block.filters[nextKey].push(clonedItem);
        }
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
        
        // Handle standard TV blocks locally based on show count * episodes per show
        if (block.type === 'tv' && !block.vibe_type) {
            const showCount = (block.shows || []).filter(s => s.name || s.id).length;
            const epsPerShow = parseInt(block.count || 0);
            block._previewCount = showCount * epsPerShow;
            // Force Alpine to notice the change by triggering a shallow update
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
                    const itemsData = await post('api/builder/preview', {
                        user_id,
                        blocks: [liveBlock]
                    }, null, 'POST', true, false);

                    if (itemsData && itemsData.status !== 'error') {
                        liveBlock._previewItems = itemsData.data || [];
                        liveBlock._previewCount = liveBlock._previewItems.length;
                    } else {
                        liveBlock._previewItems = [];
                        liveBlock._previewCount = 0;
                    }

                } catch (e) {
                    console.error("[MixerBee] Preview update failed:", e);
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
            const res = await post(`api/users/${uid}/playlists`, null, null, 'GET', true);
            if (Array.isArray(res)) {
                this.userPlaylists = res;
            }
        } catch (e) { }
    },

    async loadBlocks(blocksData = [], append = false) {
        const overlay = document.getElementById('loading-overlay');
        if (overlay) overlay.classList.remove('hidden');

        try {
            if (!Array.isArray(blocksData)) {
                console.error("[MixerBee] loadBlocks received non-array data:", blocksData);
                blocksData = [];
            }

            blocksData.forEach(b => this.ensureBlockState(b));
            const uid = Alpine.store('settings').activeUserId;
            const promises = [];

            blocksData.forEach(block => {
                const isTv = block.type === 'tv' || (block.type === 'vibe' && block.vibe_type === 'tv');
                if (isTv && uid) {
                    block.shows.forEach(show => {
                        if (show.unwatched) {
                            const series = this.library.seriesData.find(s => s.name === show.name || s.id === show.id);
                            if (series) {
                                const p = post(`api/shows/${series.id}/first_unwatched?user_id=${uid}`, null, null, 'GET', true)
                                    .then(ep => { if (ep && ep.Id) {
                                        show.season = ep.ParentIndexNumber;
                                        show.episode = ep.IndexNumber;
                                        show.previewTitle = ep.Name || '';
                                    } });
                                promises.push(p);
                            }
                        } else if ((show.name || show.id) && show.season && show.episode) {
                            promises.push(this.fetchEpisodeTitle(show));
                        }
                    });
                }
                promises.push(this.updatePreviewCount(block));
            });

            await Promise.all(promises);
            
            if (append) {
                this.blocks = [...this.blocks, ...blocksData];
            } else {
                this.blocks = [...blocksData];
            }

        } catch (e) {
            console.error("[MixerBee] loadBlocks failed:", e);
            toast("Load failed.", false);
        } finally {
            if (overlay) overlay.classList.add('hidden');
        }
    },

    addBlock(type) {
        let block;
        if (type === 'tv') {
            const def = { name: '', season: 1, episode: 1, unwatched: true, previewTitle: '', _uid: generateUUID() };
            block = { type: 'tv', shows: [def], mode: 'count', count: 3, interleave: true };
        } else if (type === 'movie') {
            block = { type: 'movie', filters: { watched_status: 'all', sort_by: 'Random', parent_ids: this.library.libraryData.map(l => l.Id), year_from: 1920, year_to: new Date().getFullYear(), release_within_days: 0 } };
        } else if (type === 'music') {
            block = { type: 'music', music: { mode: 'album', count: 10, filters: { sort_by: 'Random', limit: 25, genres: [], genre_match: 'any' } } };
        } else if (type === 'mirror') {
            block = { type: 'mirror', filters: { seeds_positive: [], seeds_negative: [], mixed_echo: false, include_seeds: false }, limit: 10, threshold: 0.65 };
        }

        if (block) {
            block._uid = generateUUID();
            this.ensureBlockState(block);
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
        const def = { name: '', season: 1, episode: 1, unwatched: true, previewTitle: '', _uid: generateUUID() };
        this.blocks[blockIndex].shows.push(def);
        this.updatePreviewCount(this.blocks[blockIndex]);
    },

    deleteShowRow(blockIndex, rowIndex) {
        const block = this.blocks[blockIndex];
        block.shows.splice(rowIndex, 1);
        this.updatePreviewCount(block);
    },

    async generateWithAi() {
        if (!this.aiPrompt.trim()) return toast('Prompt required.', false);
        this.isAiGenerating = true;
        try {
            const res = await post('api/create_from_text', {
                prompt: this.aiPrompt,
                tweaks: this.aiTweaks
            });
            if (res.status === 'ok' && Array.isArray(res.blocks)) {
                if (res.blocks.length === 0) {
                    const failMsg = res.log?.[0] || "No items matched your library.";
                    toast(`${failMsg} Try Relaxing Relevancy in AI Tweaks.`, false, {
                        actionText: "Tweaks",
                        actionCallback: () => aiTweaksModal.show()
                    });
                } else {
                    await this.loadBlocks(res.blocks, true);
                }
            }
        } catch (e) {
            console.error("[MixerBee] generateWithAi failed:", e);
        } finally {
            this.isAiGenerating = false;
        }
    },

    async quickSwitchModel(modelName) {
        const sStore = Alpine.store('settings');
        if (sStore.ollama_model === modelName) return;

        try {
            const res = await post('api/settings/model', { ollama_model: modelName }, null, 'POST', true, false);
            if (res.status === 'ok') {
                sStore.ollama_model = modelName;
                toast(`AI Model switched to ${modelName}`, true);
            }
        } catch (e) {
            toast('Failed to switch AI model.', false);
        }
    },

    clearAiPrompt() { this.aiPrompt = ''; },

    async fetchMoodDiscovery() {
        if (this.isMoodLoading) return;
        this.isMoodLoading = true;
        try {
            const res = await post('api/library/mood_discovery', null, null, 'GET', true, false);
            if (res && res.tags && res.tags.length > 0) {
                this.moodPool = res.tags;
                this.refreshMoodSlots();
                this.refreshSamplePrompt();
            } else {
                console.warn("[MixerBee] Mood Discovery: API returned no tags.");
            }
        } catch (e) {
            console.error("[MixerBee] Mood Discovery: Network or server error:", e);
        } finally {
            this.isMoodLoading = false;
        }
    },

    refreshMoodSlots() {
        if (this.moodPool.length === 0) {
            return;
        }
        
        const shuffled = [...this.moodPool].sort(() => 0.5 - Math.random());
        const count = Math.min(shuffled.length, 3);
        
        this.activeMoods = shuffled.slice(0, count);
    },

    refreshSamplePrompt() {
        if (this.moodPool.length === 0) return;
        
        const count = Math.min(this.moodPool.length, 2);
        const tags = [...this.moodPool].sort(() => 0.5 - Math.random()).slice(0, count);
        

        const structures = count > 1 ? [
            `A mix of ${tags[0]} and ${tags[1]} movies with some hints of ${tags[0]}`,
            `${tags[0].charAt(0).toUpperCase() + tags[0].slice(1)} cinema with a touch of ${tags[1]}`,
            `Highly ${tags[0]} shows, followed by something ${tags[1]}`,
            `A ${tags[0]} marathon`,
            `A block of ${tags[0]} and ${tags[1]} movies.`,
            `Explore ${tags[0]} vibes blended with ${tags[1]}`,
            `A deep dive into ${tags[0]} themes and ${tags[1]} atmosphere`,
            `Curate a ${tags[0]} and ${tags[1]} experience`,
            `Show me ${tags[0]} movies, but make them ${tags[1]}`,
            `The best of ${tags[0]} paired with ${tags[1]}`
        ] : [
            `A ${tags[0]} marathon`,
            `${tags[0].charAt(0).toUpperCase() + tags[0].slice(1)} vibes only`,
            `Pure ${tags[0]} cinema`,
            `The ultimate ${tags[0]} collection`
        ];
        
        this.samplePrompt = structures[Math.floor(Math.random() * structures.length)];
    }, 

    useSamplePrompt() {
        this.aiPrompt = this.samplePrompt;
        this.refreshSamplePrompt();
    },

    appendMood(index) {
        const mood = this.activeMoods[index];
        if (!mood) return;

        const current = this.aiPrompt.trim();
        if (!current) {
            this.aiPrompt = mood.charAt(0).toUpperCase() + mood.slice(1);
        } else {
            const lastChar = current.slice(-1);
            const separator = (lastChar === ',' || lastChar === '.') ? ' ' : ', ';
            this.aiPrompt = current + separator + mood;
        }

        const usedTags = new Set(this.activeMoods);
        const available = this.moodPool.filter(t => !usedTags.has(t));
        
        if (available.length > 0) {
            const newTag = available[Math.floor(Math.random() * available.length)];
            const updated = [...this.activeMoods];
            updated[index] = newTag;
            this.activeMoods = updated;
        }
    },

    getPreparedBlocks(blocksOverride = null) {
        const rawBlocks = blocksOverride || this.blocks;
        // Deep clone the blocks to ensure the payload is clean
        return JSON.parse(JSON.stringify(rawBlocks)).map(block => {
            // Inject cached preview IDs if they exist to "lock" the randomized results for the build
            if (block._previewItems && block._previewItems.length > 0) {
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
                        title: `${cachedBlock.title || 'Block'} Preview`
                    });
                }
            }

            const targetBlocks = this.getPreparedBlocks(blocksOverride);
            if (targetBlocks.length === 0) return toast('No content to preview.', false);

            const uid = Alpine.store('settings').activeUserId;
            const res = await post('api/builder/preview', { user_id: uid, blocks: targetBlocks }, btnEl, 'POST', true);

            if (res.status === 'ok') {
                await previewModal.show({
                    items: res.data,
                    title: 'Full Playlist Preview'
                });
            }
        } catch (err) {
            if (err.message !== 'Modal cancelled by user.') {
                console.error("[MixerBee] Preview modal error:", err);
            }
        }
    },

    async buildPlaylist(btnEl) {
        if (this.blocks.length === 0) return toast('Add a block.', false);
        const uid = Alpine.store('settings').activeUserId;

        const preparedBlocks = this.getPreparedBlocks();

        if (this.buildMode === 'add') {
            if (!this.existingPlaylistId) return toast("Select playlist.", false);
            await post(`api/playlists/${this.existingPlaylistId}/add-items`, { user_id: uid, blocks: preparedBlocks }, btnEl);
        } else {
            if (this.createAsCollection && (preparedBlocks.length !== 1 || (preparedBlocks[0].type !== 'movie' && preparedBlocks[0].vibe_type !== 'movie'))) {
                return toast('Requires one Movie block.', false);
            }
            try {
                const { playlistName } = await smartPlaylistModal.show({
                    title: this.createAsCollection ? 'Name Collection' : 'Name Playlist',
                    description: 'Provide a name.',
                    countInput: false,
                    defaultName: this.createAsCollection ? 'My Collection' : 'My Mix',
                });
                await post('api/create_mixed_playlist', { user_id: uid, playlist_name: playlistName, blocks: preparedBlocks, create_as_collection: this.createAsCollection }, btnEl);
            } catch (err) { }
        }
    },

    async buildFromPreview(btnEl) {
        const previewItems = Alpine.store('modals').preview.items;
        if (!previewItems || previewItems.length === 0) return;

        const uid = Alpine.store('settings').activeUserId;
        const itemIds = previewItems.map(i => i.Id || i.id);

        try {
            const { playlistName } = await smartPlaylistModal.show({
                title: 'Name Custom Order',
                description: 'Build playlist from this preview order.',
                countInput: false,
                defaultName: 'Custom Preview Mix'
            });

            await post('api/create_mixed_playlist', {
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
            await post('api/quick_builds', { user_id: uid, playlist_name: playlistName, quick_build_type: type, options });
        } catch (err) { }
    }
};