// static/js/blockFactory.js

import { generateUUID } from './utils.js';
import { BLOCK_TYPES, WATCH_STATUS } from './definitions.js';

export function ensureBlockState(block, library) {
    if (!block) return;
    if (!block._uid) block._uid = generateUUID();
    if (!block.block_id) block.block_id = generateUUID();

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

/**
 * Whitelist serialization of a block definition, omitting UI transient flags
 * (_previewItems, _loading, _expanded, _uid, etc.).
 */
export function serializeBlockDefinition(block) {
    if (!block) return null;
    const base = {
        block_id: block.block_id || block._uid || generateUUID(),
        type: block.type
    };

    if (block.type === BLOCK_TYPES.TV) {
        return {
            ...base,
            mode: block.mode || 'count',
            count: block.count ?? 3,
            interleave: block.interleave ?? true,
            shows: (block.shows || []).map(s => ({
                id: s.id,
                name: s.name,
                season: s.season ?? 1,
                episode: s.episode ?? 1,
                unwatched: s.unwatched ?? true,
                count: s.count ?? 1
            }))
        };
    }

    if (block.type === BLOCK_TYPES.MOVIE) {
        const f = block.filters || {};
        return {
            ...base,
            isSnapshot: !!block.isSnapshot,
            filters: {
                parent_ids: f.parent_ids || [],
                genres_any: f.genres_any || [],
                genres_all: f.genres_all || [],
                genres_exclude: f.genres_exclude || [],
                people: f.people || [],
                people_all: f.people_all || [],
                exclude_people: f.exclude_people || [],
                studios: f.studios || [],
                exclude_studios: f.exclude_studios || [],
                watched_status: f.watched_status || WATCH_STATUS.ALL,
                sort_by: f.sort_by || 'Random',
                year_from: f.year_from ?? 1900,
                year_to: f.year_to ?? (new Date().getFullYear() + 2),
                release_within_days: f.release_within_days ?? 0,
                count: f.count,
                duration_minutes: f.duration_minutes,
                min_runtime_minutes: f.min_runtime_minutes,
                max_runtime_minutes: f.max_runtime_minutes,
                min_community_rating: f.min_community_rating,
                favorites_only: f.favorites_only,
                allowed_content_ratings: f.allowed_content_ratings,
                audio_languages: f.audio_languages,
                subtitle_languages: f.subtitle_languages,
                ids: f.ids || []
            }
        };
    }

    if (block.type === BLOCK_TYPES.MUSIC) {
        return {
            ...base,
            music: {
                mode: block.music?.mode || 'album',
                count: block.music?.count ?? 10,
                filters: block.music?.filters ? { ...block.music.filters } : { sort_by: 'Random', limit: 25, genres: [], genre_match: 'any' }
            }
        };
    }

    if (block.type === BLOCK_TYPES.MIRROR) {
        const f = block.filters || {};
        return {
            ...base,
            limit: block.limit ?? 10,
            threshold: block.threshold ?? 0.65,
            filters: {
                seeds_positive: f.seeds_positive || [],
                seeds_negative: f.seeds_negative || [],
                mixed_echo: !!f.mixed_echo,
                include_seeds: !!f.include_seeds,
                ids: f.ids || []
            }
        };
    }

    if (block.type === BLOCK_TYPES.CURATED) {
        return {
            ...base,
            playback_order: block.playback_order || 'movies_first',
            tv_interleave: !!block.tv_interleave,
            movies: (block.movies || []).map(m => ({ id: m.id || m.Id, name: m.name || m.Name })),
            shows: (block.shows || []).map(s => ({
                id: s.id,
                name: s.name,
                season: s.season ?? 1,
                episode: s.episode ?? 1,
                count: s.count ?? 1,
                unwatched: s.unwatched ?? true
            })),
            filters: { ids: block.filters?.ids || [] }
        };
    }

    if (block.type === BLOCK_TYPES.VIBE) {
        return {
            ...base,
            vibe_type: block.vibe_type || BLOCK_TYPES.MOVIE,
            prompt: block.prompt || '',
            count: block.count ?? 10,
            filters: block.filters ? { ...block.filters } : {}
        };
    }

    // Default fallback
    return { ...base };
}

/**
 * Serialize full mix definition including version and top-level mix_options.
 */
export function serializeMixDefinition(mixState) {
    if (!mixState) return { schema_version: 1, blocks: [], mix_options: {} };
    return {
        schema_version: 1,
        blocks: (mixState.blocks || []).map(serializeBlockDefinition).filter(Boolean),
        mix_options: mixState.mix_options ? JSON.parse(JSON.stringify(mixState.mix_options)) : {}
    };
}