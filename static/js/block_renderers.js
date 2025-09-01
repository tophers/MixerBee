// static/js/block_renderers.js

import { debounce } from './utils.js';
import { createTvShowRow } from './components.js';

export function getTvBlockSummary(blockData) {
    const showCount = blockData.shows?.length || 0;
    let modeText = (blockData.mode === 'count') ? 'By Episode Count' : 'By End Episode';

    if (blockData.mode === 'count') {
        modeText += ` (${blockData.count || 1})`;
    }
    return `${showCount} Show${showCount !== 1 ? 's' : ''} • ${modeText}`;
}

export async function updateAllBlockPreviews() {
    const userSelect = document.getElementById('user-select');
    if (!userSelect.value) return;

    const previewPromises = [];

    document.querySelectorAll('.mixed-block[data-block-index]').forEach(blockEl => {
        const blockIndex = parseInt(blockEl.dataset.blockIndex, 10);
        const blockData = window.appState.builderState.blocks[blockIndex];
        if (!blockData) return;

        if (blockData.type === 'tv') {
            (blockData.shows || []).forEach((show, rowIndex) => {
                const previewEl = blockEl.querySelector(`.show-row[data-row-index="${rowIndex}"] .tv-block-preview`);
                const series = window.appState.seriesData.find(s => s.name === show.name);
                if (previewEl && series && !show.unwatched) {
                    previewEl.textContent = '...';
                    const promise = fetch(`api/episode_lookup?series_id=${series.id}&season=${show.season}&episode=${show.episode}`)
                        .then(r => r.ok ? r.json() : Promise.reject(''))
                        .then(data => { previewEl.textContent = `→ ${data.name}`; })
                        .catch(() => { previewEl.textContent = 'Episode not found'; });
                    previewPromises.push(promise);
                } else if (previewEl && show.unwatched) {
                     previewEl.textContent = '→ Next unwatched';
                } else if (previewEl) {
                    previewEl.textContent = '';
                }
            });
        }

        if (blockData.type === 'movie' || (blockData.type === 'music' && blockData.music?.mode === 'genre')) {
            const previewCountSpan = blockEl.querySelector('.preview-count-span');
            if (previewCountSpan) previewCountSpan.textContent = '...';

            const endpoint = blockData.type === 'movie' ? 'api/movies/preview_count' : 'api/music/preview_count';
            const filters = blockData.type === 'movie' ? blockData.filters : blockData.music.filters;

            const promise = fetch(endpoint, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ user_id: userSelect.value, filters })
            })
            .then(r => r.ok ? r.json() : Promise.reject(''))
            .then(data => {
                if(previewCountSpan) previewCountSpan.textContent = `${data.count} items match`;
            })
            .catch(() => {
                if(previewCountSpan) previewCountSpan.textContent = 'Error!';
            });
            previewPromises.push(promise);
        }
    });

    await Promise.all(previewPromises);
}

export function renderTvBlock({ blockData, index }) {
    const template = document.getElementById('template-tv-block');
    const blockElement = template.content.cloneNode(true).firstElementChild;
    blockElement.dataset.blockIndex = index;

    const showsContainer = blockElement.querySelector('.tv-block-shows');
    const summarySpan = blockElement.querySelector('.tv-block-preview-summary');
    const modeSelect = blockElement.querySelector('.tv-block-mode-select');
    const countContainer = blockElement.querySelector('.tv-block-count-container');
    const countInput = blockElement.querySelector('.tv-block-count');
    const rangeContainer = blockElement.querySelector('.tv-block-range-container');
    const endSeasonInput = blockElement.querySelector('.tv-block-end-season');
    const endEpisodeInput = blockElement.querySelector('.tv-block-end-episode');
    const interleaveCb = blockElement.querySelector('.tv-block-interleave');

    summarySpan.textContent = getTvBlockSummary(blockData);
    modeSelect.value = blockData.mode || 'count';
    countInput.value = blockData.count || 1;
    endSeasonInput.value = blockData.end_season || 1;
    endEpisodeInput.value = blockData.end_episode || 1;
    interleaveCb.checked = blockData.interleave !== false;

    const isCountMode = (blockData.mode || 'count') === 'count';
    countContainer.classList.toggle('hidden', !isCountMode);
    rangeContainer.classList.toggle('hidden', isCountMode);

    (blockData.shows || []).forEach((showData, rowIndex) => {
        const newRow = createTvShowRow({ rowData: showData, rowIndex });
        showsContainer.appendChild(newRow);
    });

    new Sortable(showsContainer, {
        animation: 150,
        handle: '.drag-handle',
        ghostClass: 'sortable-ghost',
        onEnd: (evt) => {
            if (evt.oldIndex === evt.newIndex) return;

            const blockData = window.appState.builderState.blocks[index];
            if (!blockData || !blockData.shows) return;

            const [movedItem] = blockData.shows.splice(evt.oldIndex, 1);
            blockData.shows.splice(evt.newIndex, 0, movedItem);

            showsContainer.dispatchEvent(new CustomEvent('state-changed', { bubbles: true }));
        }
    });

    return blockElement;
}

export function renderMovieBlock({ blockData, index }) {
    const template = document.getElementById('template-movie-block');
    const blockElement = template.content.cloneNode(true).firstElementChild;
    blockElement.dataset.blockIndex = index;
    const blockId = `block-${Date.now() + index}`;
    blockElement.querySelectorAll('input[name="limit-mode"]').forEach(radio => radio.name = `limit-mode-${blockId}`);

    const genreDetails = blockElement.querySelector('.movie-block-genre-input').closest('details');
    const personDetails = blockElement.querySelector('.movie-block-person-input').closest('details');
    const otherDetails = blockElement.querySelector('.movie-block-watched').closest('details');
    if (genreDetails) genreDetails.dataset.section = 'genres';
    if (personDetails) personDetails.dataset.section = 'people';
    if (otherDetails) otherDetails.dataset.section = 'other';

    const filters = blockData.filters || {};

    const previewCountContainer = blockElement.querySelector('.movie-block-preview-count');
    previewCountContainer.innerHTML = `<span class="preview-count-span">...</span>`;

    const libraryGrid = blockElement.querySelector('.movie-block-libraries');
    const genreTokenContainer = blockElement.querySelector('.movie-block-genre-tokens');
    const personTokenContainer = blockElement.querySelector('.movie-block-person-tokens');
    const watchedBtn = blockElement.querySelector('.movie-block-watched');
    const sortBtn = blockElement.querySelector('.movie-block-sort-by');
    const minYearInput = blockElement.querySelector('.movie-block-year-from');
    const maxYearInput = blockElement.querySelector('.movie-block-year-to');
    const yearDisplay = blockElement.querySelector('.range-slider-display');
    const sliderProgress = blockElement.querySelector('.range-slider-progress');
    const countRadio = blockElement.querySelector('input[value="count"]');
    const durationRadio = blockElement.querySelector('input[value="duration"]');
    const limitValueInput = blockElement.querySelector('.movie-block-limit-value');
    const limitUnitSpan = blockElement.querySelector('.limit-unit');

    appState.libraryData.forEach(lib => {
        const label = document.createElement('label');
        const isChecked = filters.parent_ids ? filters.parent_ids.includes(lib.Id) : true;
        label.innerHTML = `<input type="checkbox" class="movie-block-library-cb" value="${lib.Id}" ${isChecked ? 'checked' : ''}> ${lib.Name}`;
        libraryGrid.appendChild(label);
    });

    const genreStateIcons = { 'any': '⊕', 'all': '✓', 'exclude': '⊖' };
    (filters.genres_any || []).forEach((g, i) => genreTokenContainer.innerHTML += `<span class="token token-genre" data-token-type="genres_any" data-token-index="${i}" data-state="any"><span class="token-state" title="Click to cycle state">${genreStateIcons.any}</span>${g}<button type="button" class="token-remove">×</button></span>`);
    (filters.genres_all || []).forEach((g, i) => genreTokenContainer.innerHTML += `<span class="token token-genre" data-token-type="genres_all" data-token-index="${i}" data-state="all"><span class="token-state" title="Click to cycle state">${genreStateIcons.all}</span>${g}<button type="button" class="token-remove">×</button></span>`);
    (filters.genres_exclude || []).forEach((g, i) => genreTokenContainer.innerHTML += `<span class="token token-genre" data-token-type="genres_exclude" data-token-index="${i}" data-state="exclude"><span class="token-state" title="Click to cycle state">${genreStateIcons.exclude}</span>${g}<button type="button" class="token-remove">×</button></span>`);

    const personStateIcons = { 'include': '⊕', 'exclude': '⊖' };
    (filters.people || []).forEach((p, i) => personTokenContainer.innerHTML += `<span class="token token-person" data-token-type="people" data-token-index="${i}" data-state="include"><span class="token-state" title="Click to cycle state">${personStateIcons.include}</span>${p.Name} (${p.Role || 'Person'})<button type="button" class="token-remove">×</button></span>`);
    (filters.exclude_people || []).forEach((p, i) => personTokenContainer.innerHTML += `<span class="token token-person" data-token-type="exclude_people" data-token-index="${i}" data-state="exclude"><span class="token-state" title="Click to cycle state">${personStateIcons.exclude}</span>${p.Name} (${p.Role || 'Person'})<button type="button" class="token-remove">×</button></span>`);
    (filters.studios || []).forEach((s, i) => personTokenContainer.innerHTML += `<span class="token token-studio" data-token-type="studios" data-token-index="${i}" data-state="include"><span class="token-state" title="Click to cycle state">${personStateIcons.include}</span>${s} (Studio)<button type="button" class="token-remove">×</button></span>`);
    (filters.exclude_studios || []).forEach((s, i) => personTokenContainer.innerHTML += `<span class="token token-studio" data-token-type="exclude_studios" data-token-index="${i}" data-state="exclude"><span class="token-state" title="Click to cycle state">${personStateIcons.exclude}</span>${s} (Studio)<button type="button" class="token-remove">×</button></span>`);

    const setupToggleButton = (btn, stateConfig, state) => {
        const config = stateConfig[state];
        btn.dataset.state = state;
        btn.innerHTML = `<i data-feather="${config.icon}"></i> ${config.text}`;
    };
    setupToggleButton(watchedBtn, { 'all': { icon: 'eye', text: 'All' }, 'unplayed': { icon: 'eye-off', text: 'Unplayed' }, 'played': { icon: 'check-circle', text: 'Played' } }, filters.watched_status || 'all');
    setupToggleButton(sortBtn, { 'Random': { icon: 'shuffle', text: 'Sort: Random' }, 'PremiereDate': { icon: 'calendar', text: 'Sort: Release' }, 'DateCreated': { icon: 'plus', text: 'Sort: Added' }, 'SortName': { icon: 'chevrons-down', text: 'Sort: Name' } }, filters.sort_by || 'Random');

    const currentYear = new Date().getFullYear();
    minYearInput.max = currentYear;
    maxYearInput.max = currentYear;
    minYearInput.value = filters.year_from || 1920;
    maxYearInput.value = filters.year_to || currentYear;
    const updateYearSlider = () => {
        const minVal = parseInt(minYearInput.value, 10);
        const maxVal = parseInt(maxYearInput.value, 10);
        if(maxVal < minVal) { minYearInput.value = maxVal; }
        const minPercent = ((minYearInput.value - minYearInput.min) / (minYearInput.max - minYearInput.min)) * 100;
        const maxPercent = ((maxYearInput.value - maxYearInput.min) / (maxYearInput.max - minYearInput.min)) * 100;
        sliderProgress.style.left = `${minPercent}%`;
        sliderProgress.style.width = `${maxPercent - minPercent}%`;
        yearDisplay.textContent = `${minYearInput.value} - ${maxYearInput.value}`;
    };
    updateYearSlider();

    if (filters.duration_minutes) {
        durationRadio.checked = true;
        limitValueInput.value = Math.round(filters.duration_minutes / 60) || 3;
        limitUnitSpan.innerHTML = `<select class="movie-block-limit-duration-units"><option value="60">Hours</option><option value="1">Minutes</option></select>`;
    } else {
        countRadio.checked = true;
        limitValueInput.value = filters.limit || 5;
        limitUnitSpan.innerHTML = 'movies';
    }

    return blockElement;
}

export function renderMusicBlock({ blockData, index }) {
    const template = document.getElementById('template-music-block');
    const blockElement = template.content.cloneNode(true).firstElementChild;
    blockElement.dataset.blockIndex = index;
    const blockId = `block-${Date.now() + index}`;

    const musicData = blockData.music || {};
    const filters = musicData.filters || {};

    const previewCountContainer = blockElement.querySelector('.music-block-preview-count');
    previewCountContainer.innerHTML = `<span class="preview-count-span">...</span>`;

    const modeSelect = blockElement.querySelector('.music-block-mode');
    const artistContainer = blockElement.querySelector('.music-artist-container');
    const genreContainer = blockElement.querySelector('.music-genre-container');
    const artistSelect = blockElement.querySelector('.music-block-artist');
    const albumSelect = blockElement.querySelector('.music-block-album');
    const countInput = blockElement.querySelector('.music-block-count');
    const albumLabel = blockElement.querySelector('.music-block-album-label');
    const countLabel = blockElement.querySelector('.music-block-count-label');
    const genreGrid = blockElement.querySelector('.music-block-genre-grid');
    const genreMatchToggle = blockElement.querySelector('.genre-match-toggle');

    modeSelect.value = musicData.mode || 'album';

    artistSelect.innerHTML = '<option value="">-- Select Artist --</option>';
    appState.artistData.forEach(artist => artistSelect.add(new Option(artist.Name, artist.Id)));
    if (musicData.artistId) {
        artistSelect.value = musicData.artistId;
    }
    countInput.value = musicData.count || 10;

    if (appState.musicGenreData?.length > 0) {
        appState.musicGenreData.forEach(g => {
            const label = document.createElement('label');
            const cb = Object.assign(document.createElement('input'), { type: 'checkbox', className: 'music-block-genre-cb', value: g.Name, checked: filters.genres?.includes(g.Name) });
            label.append(cb, ` ${g.Name}`);
            genreGrid.appendChild(label);
        });
        genreMatchToggle.innerHTML = '';
        ['any', 'all', 'none'].forEach(val => {
            const label = document.createElement('label');
            const radio = Object.assign(document.createElement('input'), { type: 'radio', name: `music-block-genre-match-${blockId}`, value: val, checked: (filters.genre_match || 'any') === val });
            let labelText = val === 'any' ? 'Match Any' : val === 'all' ? 'Match All' : 'Exclude These';
            label.append(radio, ` ${labelText}`);
            genreMatchToggle.appendChild(label);
        });
    } else {
        genreGrid.innerHTML = '<p class="placeholder-text-small">No music genres found.</p>';
    }

    if (musicData.artistId && musicData.albumId) {
        fetch(`api/music/artists/${musicData.artistId}/albums`).then(r => r.json()).then(albums => {
            albumSelect.innerHTML = '<option value="">-- Select Album --</option>';
            albums.forEach(album => albumSelect.add(new Option(album.Name, album.Id)));
            albumSelect.value = musicData.albumId;
        });
    }

    const mode = musicData.mode || 'album';
    artistContainer.classList.toggle('hidden', mode === 'genre');
    genreContainer.classList.toggle('hidden', mode !== 'genre');
    albumLabel.classList.toggle('hidden', mode !== 'album');
    countLabel.classList.toggle('hidden', !mode.startsWith('artist_'));

    return blockElement;
}