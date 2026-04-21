/* static/js/mixerStore.js */

import { post, toast, debounce } from './utils.js';
import { confirmModal, smartBuildModal, smartPlaylistModal, previewModal, presetModal, importPresetModal, resetWatchModal } from './modals.js';
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
    presets: {},
    availablePresets: [],
    currentPresetName: '',

    buildMode: 'create',
    createAsCollection: false,
    existingPlaylistId: '',
    userPlaylists: [],

    aiPrompt: '',
    isAiGenerating: false,
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
        } catch (e) {
            console.error("Autosave restore failed:", e);
        }

        Alpine.watch(() => JSON.stringify(this.blocks), () => this.persistToLocalStorage());
    },

    ensureBlockState(block) {
        if (!block) return;
        if (!block._uid) block._uid = crypto.randomUUID();

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
            block.filters.ids = block.filters.ids ?? [];

            block._limitMode = block._limitMode ?? (block.filters.duration_minutes ? 'duration' : 'count');
            block._limitDurationUnit = block._limitDurationUnit ?? 60;
            if (block._limitDurationRaw === undefined) {
                block._limitDurationRaw = block.filters.duration_minutes ? Math.round(block.filters.duration_minutes / 60) : 3;
            }
        }

        if (block.type === 'music') {
            if (!block.music) block.music = { mode: 'album' };
            if (!block.music.filters) block.music.filters = { sort_by: 'Random', limit: 25, genres: [], genre_match: 'any' };
        }

        if (block.type === 'tv' || (block.type === 'vibe' && block.vibe_type === 'tv')) {
            if (!block.shows) block.shows = [];
            block.shows.forEach(s => {
                if (!s._uid) s._uid = crypto.randomUUID();
                s.previewTitle = s.previewTitle ?? '';
                s._loadingTitle = false;
            });
        }
    },

    persistToLocalStorage() {
        if (this.blocks.length > 0) {
            localStorage.setItem(this.autosaveKey, JSON.stringify({ blocks: this.blocks }));
        } else {
            localStorage.removeItem(this.autosaveKey);
        }
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
            const res = await fetch(`api/episode_lookup?series_id=${series.id}&season=${showData.season}&episode=${showData.episode}`);
            if (res.ok) {
                const data = await res.json();
                showData.previewTitle = data.name || `S${showData.season}E${showData.episode}`;
            } else {
                showData.previewTitle = 'Episode not found';
            }
        } catch (e) {
            showData.previewTitle = '';
        } finally {
            showData._loadingTitle = false;
        }
    },

    async syncNextUnwatched(showData) {
        const series = this.library.seriesData.find(s => s.name === showData.name || s.id === showData.id);
        const uid = document.getElementById('user-select')?.value;
        if (!series || !uid) return;

        showData._loadingTitle = true;
        try {
            const res = await fetch(`api/shows/${series.id}/first_unwatched?user_id=${uid}`);
            if (res.ok) {
                const ep = await res.json();
                showData.season = ep.ParentIndexNumber;
                showData.episode = ep.IndexNumber;
                showData.previewTitle = ep.Name || `S${ep.ParentIndexNumber}E${ep.IndexNumber}`;
            }
        } catch (e) {
        } finally {
            showData._loadingTitle = false;
        }
    },

    async promptResetWatch(showData) {
        const series = this.library.seriesData.find(s => s.name === showData.name || s.id === showData.id);
        if (!series) return toast("Select a show.", false);
        try {
            const decision = await resetWatchModal.show({ showName: series.name, season: showData.season });
            const payload = {
                user_id: document.getElementById('user-select').value,
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
                const [pReq, sReq] = await Promise.all([
                    fetch(`api/people?name=${encodeURIComponent(query)}`),
                    fetch(`api/studios?name=${encodeURIComponent(query)}`)
                ]);
                const people = await pReq.json();
                const studios = await sReq.json();
                const results = [];
                people.forEach(p => results.push({ type: 'person', data: p, text: `${p.Name} (${p.Role || 'Person'})` }));
                studios.forEach(s => results.push({ type: 'studio', data: s, text: `${s.Name} (Studio)` }));
                return results;
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

    async updatePreviewCount(block) {
        if (!block) return;
        if (block.type === 'tv' && !block.vibe_type) return;

        if (!this._previewDebouncers[block._uid]) {
            this._previewDebouncers[block._uid] = debounce(async (targetUid) => {
                const user_id = document.getElementById('user-select')?.value;
                if (!user_id) return;

                const liveBlock = this.blocks.find(b => b._uid === targetUid);
                if (!liveBlock) return;

                liveBlock._previewLoading = true;

                const isMovie = (liveBlock.type === 'movie' || liveBlock.vibe_type === 'movie');
                const isMusic = liveBlock.type === 'music';

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
                }
            }, 800);
        }

        this._previewDebouncers[block._uid](block._uid);
    },

    async refreshPresets() {
        try {
            const res = await fetch('api/presets');
            if (res.ok) {
                this.presets = await res.json();
                this.availablePresets = Object.keys(this.presets);
            }
        } catch (e) { }
    },

    async refreshUserPlaylists() {
        const uid = document.getElementById('user-select')?.value;
        if (!uid) return;
        try {
            this.userPlaylists = await (await fetch(`api/users/${uid}/playlists`)).json();
        } catch (e) { }
    },

    async savePreset() {
        try {
            const name = await presetModal.show(this.availablePresets);
            const res = await post('api/presets', { name, data: this.blocks });
            if (res.status === 'ok') {
                await this.refreshPresets();
                this.currentPresetName = name;
                toast(`Preset "${name}" saved!`, true);
            }
        } catch (err) { }
    },

    async updateCurrentPreset() {
        if (!this.currentPresetName) return;
        const res = await post('api/presets', { name: this.currentPresetName, data: this.blocks });
        if (res.status === 'ok') {
            this.presets[this.currentPresetName] = JSON.parse(JSON.stringify(this.blocks));
            toast(`Preset updated!`, true);
        }
    },

    async deletePreset() {
        if (!this.currentPresetName) return;
        try {
            await confirmModal.show({ title: 'Delete?', text: `Delete "${this.currentPresetName}"?`, confirmText: 'Delete' });
            const res = await post(`api/presets/${this.currentPresetName}`, {}, null, 'DELETE');
            if (res.status === 'ok') {
                await this.refreshPresets();
                this.currentPresetName = '';
                await this.loadBlocks([]);
            }
        } catch (err) { }
    },

    async importPreset() {
        try {
            const { name, data } = await importPresetModal.show();
            if (this.presets[name]) {
                await confirmModal.show({ title: 'Overwrite?', text: `Preset exists. Overwrite?`, confirmText: 'Overwrite' });
            }
            const res = await post('api/presets', { name, data });
            if (res.status === 'ok') {
                await this.refreshPresets();
                this.currentPresetName = name;
                await this.loadBlocks(data);
                toast(`Imported!`, true);
            }
        } catch (err) { }
    },

    exportPreset() {
        if (!this.currentPresetName) return;
        try {
            const payload = JSON.stringify({ name: this.currentPresetName, data: this.presets[this.currentPresetName] });
            const bytes = new TextEncoder().encode(payload);
            const binString = Array.from(bytes, (byte) => String.fromCharCode(byte)).join("");
            const code = btoa(binString);

            navigator.clipboard.writeText(`MixerBee Preset: "${this.currentPresetName}"\n---\n${code}`).then(() => toast('Copied!', true));
        } catch (e) {
            console.error("Export failed:", e);
            toast("Failed to encode preset data.", false);
        }
    },

    async loadBlocks(blocksData = []) {
        console.log("[MixerBee] loadBlocks called with:", blocksData);
        const overlay = document.getElementById('loading-overlay');
        if (overlay) overlay.classList.remove('hidden');

        try {
            if (!Array.isArray(blocksData)) {
                console.error("[MixerBee] loadBlocks received non-array data:", blocksData);
                blocksData = [];
            }

            blocksData.forEach(b => this.ensureBlockState(b));
            const uid = document.getElementById('user-select')?.value;
            const promises = [];

            blocksData.forEach(block => {
                const isTv = block.type === 'tv' || (block.type === 'vibe' && block.vibe_type === 'tv');
                if (isTv && uid) {
                    block.shows.forEach(show => {
                        if (show.unwatched) {
                            const series = this.library.seriesData.find(s => s.name === show.name || s.id === show.id);
                            if (series) {
                                const p = fetch(`api/shows/${series.id}/first_unwatched?user_id=${uid}`)
                                    .then(r => r.ok ? r.json() : null)
                                    .then(ep => { if (ep) {
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
            this.blocks.splice(0, this.blocks.length, ...blocksData);

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
            const def = { name: '', season: 1, episode: 1, unwatched: true, previewTitle: '', _uid: crypto.randomUUID() };
            block = { type: 'tv', shows: [def], mode: 'count', count: 3, interleave: true };
        } else if (type === 'movie') {
            block = { type: 'movie', filters: { watched_status: 'all', sort_by: 'Random', parent_ids: this.library.libraryData.map(l => l.Id), year_from: 1920, year_to: new Date().getFullYear() } };
        } else if (type === 'music') {
            block = { type: 'music', music: { mode: 'album', filters: { sort_by: 'Random', limit: 25, genres: [], genre_match: 'any' } } };
        }

        if (block) {
            block._uid = crypto.randomUUID();
            this.ensureBlockState(block);
            this.blocks.push(block);
            this.updatePreviewCount(block);
        }
    },

    duplicateBlock(index) {
        const copy = JSON.parse(JSON.stringify(this.blocks[index]));
        copy._uid = crypto.randomUUID();
        if (copy.shows) copy.shows.forEach(s => s._uid = crypto.randomUUID());
        this.blocks.splice(index + 1, 0, copy);
    },

    deleteBlock(index) {
        this.blocks.splice(index, 1);
    },

    async clearAllBlocks() {
        try {
            await confirmModal.show({ title: 'Clear All?', text: 'Remove all blocks?', confirmText: 'Clear' });
            this.blocks.splice(0, this.blocks.length);
            this.currentPresetName = '';
        } catch (e) { }
    },

    addShowRow(blockIndex) {
        const def = { name: '', season: 1, episode: 1, unwatched: true, previewTitle: '', _uid: crypto.randomUUID() };
        this.blocks[blockIndex].shows.push(def);
    },

    deleteShowRow(blockIndex, rowIndex) {
        this.blocks[blockIndex].shows.splice(rowIndex, 1);
    },

    async generateWithAi() {
        if (!this.aiPrompt.trim()) return toast('Prompt required.', false);
        this.isAiGenerating = true;
        console.log("[MixerBee] generateWithAi prompt:", this.aiPrompt);
        try {
            const res = await post('api/create_from_text', { prompt: this.aiPrompt });
            console.log("[MixerBee] AI Response received:", res);
            
            if (res.status === 'ok' && Array.isArray(res.blocks)) {
                res.blocks.forEach((b, i) => {
                    const blockSnapshot = JSON.parse(JSON.stringify(b));
                    console.log(`[MixerBee] Block ${i} structure:`, blockSnapshot);
                });
                await this.loadBlocks(res.blocks);
            } else {
                console.warn("[MixerBee] AI succeeded but returned no valid blocks array.");
            }
        } catch (e) {
            console.error("[MixerBee] generateWithAi failed:", e);
        } finally {
            this.isAiGenerating = false;
        }
    },

    clearAiPrompt() { this.aiPrompt = ''; },

    async previewPlaylist(btnEl, blocksOverride = null) {
        try {
            if (blocksOverride && blocksOverride.length === 1) {
                const cachedBlock = blocksOverride[0];
                if (cachedBlock._previewItems && cachedBlock._previewItems.length > 0) {
                    console.log("[MixerBee] Showing cached results in modal.");
                    return await previewModal.show(cachedBlock._previewItems);
                }
            }

            const targetBlocks = blocksOverride || this.blocks;
            if (targetBlocks.length === 0) return toast('No content to preview.', false);

            const uid = document.getElementById('user-select')?.value;
            const res = await post('api/builder/preview', { user_id: uid, blocks: targetBlocks }, btnEl);
            if (res.status === 'ok') {
                await previewModal.show(res.data);
            }
        } catch (err) {
            if (err.message !== 'Modal cancelled by user.') {
                console.error("[MixerBee] Preview modal error:", err);
            }
        }
    },

    async buildPlaylist(btnEl) {
        if (this.blocks.length === 0) return toast('Add a block.', false);
        const uid = document.getElementById('user-select')?.value;
        if (this.buildMode === 'add') {
            if (!this.existingPlaylistId) return toast("Select playlist.", false);
            await post(`api/playlists/${this.existingPlaylistId}/add-items`, { user_id: uid, blocks: this.blocks }, btnEl);
        } else {
            if (this.createAsCollection && (this.blocks.length !== 1 || (this.blocks[0].type !== 'movie' && this.blocks[0].vibe_type !== 'movie'))) {
                return toast('Requires one Movie block.', false);
            }
            try {
                const { playlistName } = await smartPlaylistModal.show({
                    title: this.createAsCollection ? 'Name Collection' : 'Name Playlist',
                    description: 'Provide a name.',
                    countInput: false,
                    defaultName: this.createAsCollection ? 'My Collection' : 'My Mix',
                });
                await post('api/create_mixed_playlist', { user_id: uid, playlist_name: playlistName, blocks: this.blocks, create_as_collection: this.createAsCollection }, btnEl);
            } catch (err) { }
        }
    },

    async showSmartBuildMenu() {
        try {
            const type = await smartBuildModal.show(SMART_BUILD_TYPES);
            await this.handleSmartBuildSelection(type);
        } catch (e) { }
    },

    async handleSmartBuildSelection(type) {
        const config = {
            recently_added: { title: 'Recently Added', description: 'New media.', defaultName: 'Recently Added', defaultCount: 25 },
            next_up: { title: 'Next Up', description: 'In-progress shows.', defaultName: 'Next Up' },
            pilot_sampler: { title: 'Pilot Sampler', description: 'Random pilots.', defaultName: 'Pilot Sampler' },
            from_the_vault: { title: 'From the Vault', description: 'Forgotten favorites.', defaultName: 'Forgotten favorites.', defaultCount: 20 },
        };
        if (config[type]) await this.executeQuickBuild(type, config[type]);
        else if (type === 'genre_roulette' || type === 'genre_sampler') {
            const data = type === 'genre_roulette' ? this.library.movieGenreData : this.library.musicGenreData;
            if (!data?.length) return toast("Empty.", false);
            const randomGenre = data[Math.floor(Math.random() * data.length)];
            await this.executeQuickBuild(type, { title: `Roulette: ${randomGenre.Name}`, description: `Random ${randomGenre.Name}.`, defaultName: `Mix: ${randomGenre.Name}`, defaultCount: 10, extraParams: { genre: randomGenre.Name } });
        } else await this.fetchThenExecuteQuickBuild(type);
    },

    async executeQuickBuild(type, { title, description, defaultName, showCount = true, defaultCount = 10, extraParams = {} }) {
        const uid = document.getElementById('user-select')?.value;
        try {
            const { playlistName, count } = await smartPlaylistModal.show({ title, description, defaultName, countInput: showCount, defaultCount });
            const options = { ...extraParams };
            if (showCount) options.count = count;
            await post('api/quick_builds', { user_id: uid, playlist_name: playlistName, quick_build_type: type, options });
        } catch (err) { }
    },

    async fetchThenExecuteQuickBuild(type) {
        const endpoint = type === 'artist_spotlight' ? 'api/music/random_artist' : 'api/music/random_album';
        const overlay = document.getElementById('loading-overlay');
        overlay?.classList.remove('hidden');
        try {
            const res = await (await fetch(endpoint)).json();
            overlay?.classList.add('hidden');
            if (type === 'artist_spotlight') {
                await this.executeQuickBuild(type, { title: `Artist: ${res.Name}`, description: `Tracks by ${res.Name}.`, defaultName: `Spotlight: ${res.Name}`, defaultCount: 15, extraParams: { artist_id: res.Id } });
            } else {
                await this.executeQuickBuild(type, { title: `Album: ${res.Name}`, description: `By ${res.ArtistItems?.[0]?.Name || 'Unknown'}.`, defaultName: `Album: ${res.Name}`, showCount: false, extraParams: { album_id: res.Id } });
            }
        } catch (e) { overlay?.classList.add('hidden'); toast("Failed.", false); }
    }
};