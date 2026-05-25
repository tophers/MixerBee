// static/js/blockFactory.js

import { generateUUID } from './utils.js';
import { BLOCK_TYPES, WATCH_STATUS } from './definitions.js';

export function ensureBlockState(block, library) {
    if (!block) return;
    if (!block._uid) block._uid = generateUUID();

    if (block._previewCount === undefined) block._previewCount = 0;
    if (block._previewItems === undefined) block._previewItems = [];
    if (block._previewLoading === undefined) block._previewLoading = false;
    if (block.isSnapshot === undefined) block.isSnapshot = false;

    const isStandardMovie = block.type === BLOCK_TYPES.MOVIE;
    const isVibeMovie = (block.type === BLOCK_TYPES.VIBE && block.vibe_type === BLOCK_TYPES.MOVIE);

    if (isStandardMovie || isVibeMovie) {
        if (!block.filters) block.filters = {};

        if (isStandardMovie && (!block.filters.parent_ids || block.filters.parent_ids.length === 0)) {
            block.filters.parent_ids = (library?.libraryData || []).map(l => l.Id);
        }

        block.filters.genres_any = block.filters.genres_any ?? [];
        block.filters.genres_all = block.filters.genres_all ?? [];
        block.filters.genres_exclude = block.filters.genres_exclude ?? [];
        block.filters.people = block.filters.people ?? [];
        block.filters.people_all = block.filters.people_all ?? [];
        block.filters.exclude_people = block.filters.exclude_people ?? [];
        block.filters.studios = block.filters.studios ?? [];
        block.filters.exclude_studios = block.filters.exclude_studios ?? [];
        block.filters.watched_status = block.filters.watched_status ?? WATCH_STATUS.ALL;
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

    if (block.type === BLOCK_TYPES.MUSIC) {
        if (!block.music) block.music = { mode: 'album', count: 10 };
        if (!block.music.filters) block.music.filters = { sort_by: 'Random', limit: 25, genres: [], genre_match: 'any' };
    }

    if (block.type === BLOCK_TYPES.MIRROR) {
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
        block.filters.ids = block.filters.ids ?? [];
    }

    if (block.type === BLOCK_TYPES.TV || (block.type === BLOCK_TYPES.VIBE && block.vibe_type === BLOCK_TYPES.TV)) {
        if (!block.shows) block.shows = [];
        block.shows.forEach(s => {
            if (!s._uid) s._uid = generateUUID();

            if (!s.name && s.id) {
                const seriesMatch = (library?.seriesData || []).find(ls => String(ls.id) === String(s.id));
                if (seriesMatch) s.name = seriesMatch.name;
            }

            if (s.season === undefined) s.season = 1;
            if (s.episode === undefined) s.episode = 1;
            s.previewTitle = s.previewTitle ?? '';
            s._loadingTitle = false;
        });
    }

    if (block.type === BLOCK_TYPES.CURATED) {
        if (!block.movies) block.movies = [];
        if (!block.shows) block.shows = [];
        if (!block.playback_order) block.playback_order = 'movies_first';
        if (!block.tv_interleave) block.tv_interleave = false;
        if (!block.filters) block.filters = { ids: [] };

        block.shows.forEach(s => {
            if (!s._uid) s._uid = generateUUID();
            if (!s.name && s.id) {
                const seriesMatch = (library?.seriesData || []).find(ls => String(ls.id) === String(s.id));
                if (seriesMatch) s.name = seriesMatch.name;
            }
            if (s.season === undefined) s.season = 1;
            if (s.episode === undefined) s.episode = 1;
            if (s.count === undefined) s.count = 1;
            if (s.unwatched === undefined) s.unwatched = true;
            s.previewTitle = s.previewTitle ?? '';
            s._loadingTitle = false;
        });
    }
}

export function createNewBlock(type, libraryData) {
    let block;
    if (type === BLOCK_TYPES.TV) {
        const def = { name: '', season: 1, episode: 1, unwatched: true, previewTitle: '', _uid: generateUUID() };
        block = { type: BLOCK_TYPES.TV, shows: [def], mode: 'count', count: 3, interleave: true };
    } else if (type === BLOCK_TYPES.MOVIE) {
        block = { 
            type: BLOCK_TYPES.MOVIE, 
            filters: { 
                watched_status: WATCH_STATUS.ALL, 
                sort_by: 'Random', 
                parent_ids: (libraryData || []).map(l => l.Id), 
                year_from: 1920, 
                year_to: new Date().getFullYear(), 
                release_within_days: 0 
            } 
        };
    } else if (type === BLOCK_TYPES.MUSIC) {
        block = { type: BLOCK_TYPES.MUSIC, music: { mode: 'album', count: 10, filters: { sort_by: 'Random', limit: 25, genres: [], genre_match: 'any' } } };
    } else if (type === BLOCK_TYPES.MIRROR) {
        block = { type: BLOCK_TYPES.MIRROR, filters: { seeds_positive: [], seeds_negative: [], mixed_echo: false, include_seeds: false }, limit: 10, threshold: 0.65 };
    } else if (type === BLOCK_TYPES.CURATED) {
        block = { type: BLOCK_TYPES.CURATED, playback_order: 'movies_first', tv_interleave: false, movies: [], shows: [], filters: { ids: [] } };
    }

    if (block) {
        block._uid = generateUUID();
        ensureBlockState(block, { libraryData });
    }
    return block;
}

export function createEchoBlock(item) {
    const block = {
        type: BLOCK_TYPES.MIRROR,
        _uid: generateUUID(),
        filters: {
            seeds_positive: [{ Id: item.Id || item.id, Name: item.Name || item.name || item.previewTitle || 'Unknown' }],
            seeds_negative: [],
            mixed_echo: false,
            include_seeds: false
        },
        limit: 10,
        threshold: 0.65
    };
    ensureBlockState(block);
    return block;
}