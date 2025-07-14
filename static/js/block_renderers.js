// static/js/block_renderers.js
import { debounce } from './utils.js';
import { createTvShowRow } from './components.js';
import { appState } from './app.js';

function createHeaderButton(iconName, className, title) {
    const btn = document.createElement('button');
    btn.type = 'button';
    btn.className = `icon-btn ${className}`;
    btn.title = title;
    btn.innerHTML = `<i data-feather="${iconName}"></i>`;
    return btn;
}

export function updateTvBlockSummary(blockElement) {
    const summarySpan = blockElement.querySelector('.tv-block-preview-summary');
    if (!summarySpan) return;

    const showRows = blockElement.querySelectorAll('.tv-block-show-row');
    const modeSelect = blockElement.querySelector('.tv-block-mode-select');

    const showCount = showRows.length;
    let modeText = modeSelect.options[modeSelect.selectedIndex].textContent;

    if (modeSelect.value === 'count') {
        const countInput = blockElement.querySelector('.tv-block-count');
        const episodeCount = countInput.value;
        modeText += ` (${episodeCount})`;
    }

    summarySpan.textContent = `${showCount} Show${showCount !== 1 ? 's' : ''} • ${modeText}`;
}

async function updateMusicBlockPreviewCount(blockElement, userSelectElement) {
    const countSpan = blockElement.querySelector('.music-block-preview-count');
    if (!countSpan) return;
    countSpan.textContent = '...';


    const genreMatchRadio = blockElement.querySelector(`input[name^="music-block-genre-match-"]:checked`);
   

    const filters = {
        genres: [...blockElement.querySelectorAll('.music-block-genre-cb:checked')].map(cb => cb.value),
        genre_match: genreMatchRadio ? genreMatchRadio.value : 'any',
        sort_by: blockElement.querySelector('.music-block-sort-by').value,
    };
    const requestBody = { user_id: userSelectElement.value, filters: filters };

    try {
        const response = await fetch('api/music/preview_count', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(requestBody)
        });
        if (!response.ok) throw new Error(`HTTP error! status: ${response.status}`);
        const data = await response.json();
        countSpan.textContent = `${data.count} songs match`;
    } catch (error) {
        console.error("Error fetching music preview count:", error);
        countSpan.textContent = 'Error!';
    }
}

// START: New exported function for the Music Block summary
export function updateMusicBlockSummary(blockElement) {
    const summarySpan = blockElement.querySelector('.music-block-preview-summary');
    if (!summarySpan) return;

    const modeSelect = blockElement.querySelector('.music-block-mode');
    const mode = modeSelect.value;
    const modeText = modeSelect.options[modeSelect.selectedIndex].textContent;
    let summary = modeText;

    if (mode === 'genre') {
        const limitInput = blockElement.querySelector('.music-block-limit');
        const genreCount = blockElement.querySelectorAll('.music-block-genre-cb:checked').length;
        if (genreCount > 0) {
            summary = `${genreCount} Genre${genreCount !== 1 ? 's' : ''} • ${limitInput.value} songs`;
        } else {
            summary = `All Genres • ${limitInput.value} songs`;
        }
    } else if (mode.startsWith('artist_')) {
        const artistSelect = blockElement.querySelector('.music-block-artist');
        const countInput = blockElement.querySelector('.music-block-count');
        if (artistSelect.value && artistSelect.options[artistSelect.selectedIndex]) {
            const artistName = artistSelect.options[artistSelect.selectedIndex].textContent;
            summary = `${artistName} • ${countInput.value} tracks`;
        }
    } else if (mode === 'album') {
        const artistSelect = blockElement.querySelector('.music-block-artist');
        const albumSelect = blockElement.querySelector('.music-block-album');
        if (albumSelect.value && albumSelect.options[albumSelect.selectedIndex]) {
            const albumName = albumSelect.options[albumSelect.selectedIndex].textContent;
            const artistName = artistSelect.options[artistSelect.selectedIndex].textContent;
            summary = `${albumName} by ${artistName}`;
        }
    }
    summarySpan.textContent = summary;
}
// END: New function

export function renderTvBlock({ data = null, userSelectElement, changeCallback }) {
    const initialRows = data?.shows || [{}];
    const isInterleaved = (data?.interleave !== false);

    const blockElement = document.createElement('details');
    blockElement.open = true;

    blockElement.className = 'mixed-block';
    blockElement.dataset.type = 'tv';

    const summary = document.createElement('summary');

    const header = document.createElement('div');
    header.className = 'mixed-block-header';
    const headerTitle = document.createElement('h3');
    headerTitle.innerHTML = `<i data-feather="tv"></i> TV Block`;

    const rightControlsContainer = document.createElement('div');
    rightControlsContainer.className = 'mixed-block-controls';

    const summarySpan = document.createElement('span');
    summarySpan.className = 'tv-block-preview-summary';

    const collapseIcon = document.createElement('span');
    collapseIcon.className = 'icon-btn collapse-toggle-btn';
    collapseIcon.innerHTML = `<i data-feather="chevron-up"></i>`;

    rightControlsContainer.append(
        summarySpan,
        createHeaderButton('copy', 'duplicate-block-btn', 'Duplicate Block'),
        createHeaderButton('x', 'danger delete-block-btn', 'Delete Block'),
        collapseIcon
    );

    const dragHandle = createHeaderButton('move', 'drag-handle', 'Drag to reorder');
    dragHandle.innerHTML = '<i data-feather="move"></i>';
    dragHandle.style.cursor = 'grab';

    header.append(dragHandle, headerTitle, rightControlsContainer);

    summary.appendChild(header);

    const body = document.createElement('div');
    body.className = 'mixed-block-body';

    const showsContainer = document.createElement('div');
    showsContainer.className = 'tv-block-shows';
    initialRows.forEach(rowData => {
        const newRow = createTvShowRow({ rowData, seriesData: appState.seriesData, userSelectElement, changeCallback });
        showsContainer.appendChild(newRow);
    });

    const addShowBtn = Object.assign(document.createElement('button'), { type: 'button', className: 'secondary add-show-row-btn' });
    addShowBtn.innerHTML = '<i data-feather="plus"></i> Add Show';
    const buttonGroup = document.createElement('div');
    buttonGroup.className = 'button-group';
    buttonGroup.appendChild(addShowBtn);

    const footer = document.createElement('div');
    footer.className = 'block-options-footer';

    const modeSelectLabel = document.createElement('label');
    const modeSelect = Object.assign(document.createElement('select'), { className: 'tv-block-mode-select' });
    modeSelect.innerHTML = `
        <option value="count">By Episode Count</option>
        <option value="range">By End Episode</option>
    `;
    modeSelectLabel.append('Mode:', modeSelect);

    const countContainer = document.createElement('div');
    countContainer.className = 'tv-block-count-container';
    const countLabel = document.createElement('label');
    const countInput = Object.assign(document.createElement('input'), { type: 'number', className: 'tv-block-count', value: data?.count || 1, min: 1 });
    countLabel.append('Episodes per show:', countInput);
    countContainer.appendChild(countLabel);

    const rangeContainer = document.createElement('div');
    rangeContainer.className = 'tv-block-range-container';
    rangeContainer.style.display = 'none';
    const endSeasonLabel = document.createElement('label');
    const endSeasonInput = Object.assign(document.createElement('input'), { type: 'number', className: 'tv-block-end-season', value: data?.end_season || 1, min: 1 });
    endSeasonLabel.append('End S:', endSeasonInput);
    const endEpisodeLabel = document.createElement('label');
    const endEpisodeInput = Object.assign(document.createElement('input'), { type: 'number', className: 'tv-block-end-episode', value: data?.end_episode || 1, min: 1 });
    endEpisodeLabel.append('End E:', endEpisodeInput);
    rangeContainer.append(endSeasonLabel, endEpisodeLabel);

    const interleaveLabel = document.createElement('label');
    interleaveLabel.className = 'interleave-label';
    const interleaveCb = Object.assign(document.createElement('input'), { type: 'checkbox', className: 'tv-block-interleave', checked: isInterleaved });
    interleaveLabel.append(interleaveCb, ' Interleave');

    modeSelect.addEventListener('change', () => {
        if (modeSelect.value === 'count') {
            countContainer.style.display = 'block';
            rangeContainer.style.display = 'none';
        } else {
            countContainer.style.display = 'none';
            rangeContainer.style.display = 'flex';
        }
        updateTvBlockSummary(blockElement);
        if (changeCallback) changeCallback();
    });

    [countInput, endSeasonInput, endEpisodeInput, interleaveCb].forEach(el => {
        el.addEventListener('input', () => {
            if (changeCallback) changeCallback();
        });
    });

    if (data?.end_season) {
        modeSelect.value = 'range';
    }
    modeSelect.dispatchEvent(new Event('change'));

    const optionsGrid = document.createElement('div');
    optionsGrid.className = 'block-options-grid';
    optionsGrid.append(modeSelectLabel, countContainer, rangeContainer, interleaveLabel);
    footer.appendChild(optionsGrid);


    body.append(showsContainer, buttonGroup, footer);

    blockElement.append(summary, body);

    updateTvBlockSummary(blockElement);

    return blockElement;
}

export function renderMovieBlock({ data = null, userSelectElement, changeCallback }) {
    const filters = data?.filters || {};
    const blockId = `block-${Date.now()}`;

    const blockElement = document.createElement('details');
    blockElement.open = true;

    blockElement.className = 'mixed-block';
    blockElement.dataset.type = 'movie';
    blockElement.dataset.id = blockId;

    const summary = document.createElement('summary');
    const header = document.createElement('div');
    header.className = 'mixed-block-header';

    const headerTitle = document.createElement('h3');
    headerTitle.innerHTML = `<i data-feather="film"></i> Movie Block`;

    const rightControlsContainer = document.createElement('div');
    rightControlsContainer.className = 'mixed-block-controls';

    const previewCountSpan = document.createElement('span');
    previewCountSpan.className = 'movie-block-preview-count';

    const collapseIcon = document.createElement('span');
    collapseIcon.className = 'icon-btn collapse-toggle-btn';
    collapseIcon.innerHTML = `<i data-feather="chevron-up"></i>`;

    rightControlsContainer.append(
        previewCountSpan,
        createHeaderButton('copy', 'duplicate-block-btn', 'Duplicate Block'),
        createHeaderButton('x', 'danger delete-block-btn', 'Delete Block'),
        collapseIcon
    );

    const dragHandle = createHeaderButton('move', 'drag-handle', 'Drag to reorder');
    dragHandle.style.cursor = 'grab';

    header.append(dragHandle, headerTitle, rightControlsContainer);

    summary.appendChild(header);

    const body = document.createElement('div');
    body.className = 'mixed-block-body';

    async function updateMovieBlockPreviewCount() {
        const countSpan = blockElement.querySelector('.movie-block-preview-count');
        if (!countSpan) return;
        countSpan.textContent = '...';
        const yearFrom = blockElement.querySelector('.movie-block-year-from').value;
        const yearTo = blockElement.querySelector('.movie-block-year-to').value;

        const genres_any = [];
        const genres_all = [];
        const genres_exclude = [];
        blockElement.querySelectorAll('.token-genre').forEach(token => {
            const state = token.dataset.state;
            const name = token.dataset.name;
            if (state === 'any') { genres_any.push(name); }
            else if (state === 'all') { genres_all.push(name); }
            else if (state === 'exclude') { genres_exclude.push(name); }
        });

        const people = [];
        const exclude_people = [];
        const studios = [];
        const exclude_studios = [];
        blockElement.querySelectorAll('.movie-block-person-tokens .token').forEach(token => {
            const state = token.dataset.state;
            if (token.dataset.type === 'person') {
                const personData = { Id: token.dataset.id, Name: token.dataset.name, Role: token.dataset.role };
                if (state === 'include') { people.push(personData); }
                else { exclude_people.push(personData); }
            } else if (token.dataset.type === 'studio') {
                const studioName = token.dataset.name;
                if (state === 'include') { studios.push(studioName); }
                else { exclude_studios.push(studioName); }
            }
        });

        const localFilters = {
            genres_any, genres_all, genres_exclude,
            people, exclude_people,
            studios, exclude_studios,
            watched_status: blockElement.querySelector('.movie-block-watched').dataset.state,
            year_from: yearFrom ? parseInt(yearFrom) : undefined,
            year_to: yearTo ? parseInt(yearTo) : undefined,
            sort_by: blockElement.querySelector('.movie-block-sort-by').dataset.state,
            parent_ids: [...blockElement.querySelectorAll('.movie-block-library-cb:checked')].map(cb => cb.value),
        };

        const limitModeRadio = blockElement.querySelector('input[name^="limit-mode-"]:checked');
        if (limitModeRadio) {
            const limitMode = limitModeRadio.value;
            const limitValue = parseInt(blockElement.querySelector('.movie-block-limit-value').value, 10);
            if (!isNaN(limitValue) && limitValue > 0) {
                if (limitMode === 'count') {
                    localFilters.limit = limitValue;
                } else if (limitMode === 'duration') {
                    const durationUnits = blockElement.querySelector('.movie-block-limit-duration-units');
                    if (durationUnits) {
                        const units = parseInt(durationUnits.value, 10);
                        if (!isNaN(units)) {
                            localFilters.duration_minutes = limitValue * units;
                        }
                    }
                }
            }
        }

        const requestBody = { user_id: userSelectElement.value, filters: localFilters };
        try {
            const response = await fetch('api/movies/preview_count', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(requestBody)
            });
            if (!response.ok) throw new Error(`HTTP error! status: ${response.status}`);
            const data = await response.json();
            countSpan.textContent = `${data.count} movies match`;
        } catch (error) {
            console.error("Error fetching movie preview count:", error);
            countSpan.textContent = 'Error!';
        }
    }

    const moviePreviewDebouncer = debounce(() => {
        updateMovieBlockPreviewCount();
        if (changeCallback) changeCallback();
    }, 500);

    const libraryFieldset = document.createElement('fieldset');
    libraryFieldset.className = 'filter-group';
    const libraryLegend = document.createElement('legend');
    libraryLegend.textContent = 'Libraries';
    const libraryGrid = document.createElement('div');
    libraryGrid.className = 'checkbox-grid';
    appState.libraryData.forEach(lib => {
        const label = document.createElement('label');
        const isChecked = filters.parent_ids ? filters.parent_ids.includes(lib.Id) : true;
        const cb = Object.assign(document.createElement('input'), { type: 'checkbox', className: 'movie-block-library-cb', value: lib.Id, checked: isChecked });
        label.append(cb, ` ${lib.Name}`);
        libraryGrid.appendChild(label);
    });
    libraryFieldset.append(libraryLegend, libraryGrid);

    const genreFieldset = document.createElement('fieldset');
    genreFieldset.className = 'filter-group';
    const genreLegend = document.createElement('legend');
    genreLegend.textContent = 'Genres';

    const genreDetails = document.createElement('details');
    const genreSummary = document.createElement('summary');
    genreSummary.textContent = 'Expand/Collapse Genre Filters';

    const genreTokenFieldWrapper = document.createElement('div');
    genreTokenFieldWrapper.className = 'token-field-wrapper';

    const genreInput = Object.assign(document.createElement('input'), {
        type: 'search',
        className: 'token-input movie-block-genre-input',
        placeholder: 'Search for a genre...'
    });

    const genreSuggestionsContainer = document.createElement('div');
    genreSuggestionsContainer.className = 'autocomplete-suggestions';

    const genreTokenContainer = document.createElement('div');
    genreTokenContainer.className = 'token-container movie-block-genre-tokens';

    genreTokenFieldWrapper.append(genreInput, genreSuggestionsContainer);
    genreDetails.append(genreSummary, genreTokenFieldWrapper, genreTokenContainer);
    genreFieldset.append(genreLegend, genreDetails);

    const peopleFieldset = document.createElement('fieldset');
    peopleFieldset.className = 'filter-group';
    const peopleLegend = document.createElement('legend');
    peopleLegend.textContent = 'People & Studios';
    const peopleDetails = document.createElement('details');
    const peopleSummary = document.createElement('summary');
    peopleSummary.textContent = 'Expand/Collapse Filters';

    const personTokenFieldWrapper = document.createElement('div');
    personTokenFieldWrapper.className = 'token-field-wrapper';

    const personInput = Object.assign(document.createElement('input'), {
        type: 'search',
        className: 'token-input movie-block-person-input',
        placeholder: 'Search for People or Studios...'
    });

    const personSuggestionsContainer = document.createElement('div');
    personSuggestionsContainer.className = 'autocomplete-suggestions';

    const peopleTokenContainer = document.createElement('div');
    peopleTokenContainer.className = 'token-container movie-block-person-tokens';

    personTokenFieldWrapper.append(personInput, personSuggestionsContainer);
    peopleDetails.append(peopleSummary, personTokenFieldWrapper, peopleTokenContainer);
    peopleFieldset.append(peopleLegend, peopleDetails);

    const otherFiltersFieldset = document.createElement('fieldset');
    otherFiltersFieldset.className = 'filter-group';
    const otherFiltersLegend = document.createElement('legend');
    otherFiltersLegend.textContent = 'Other Filters';
    const filterDetails = document.createElement('details');
    const filterSummary = document.createElement('summary');
    filterSummary.textContent = 'Expand/Collapse Other Filters';
    const otherFiltersGrid = document.createElement('div');
    otherFiltersGrid.className = 'movie-block-filter-grid';

    const watchedStateCycle = { 'all': 'unplayed', 'unplayed': 'played', 'played': 'all' };
    const watchedStateConfig = {
        'all': { icon: 'eye', text: 'All' },
        'unplayed': { icon: 'check-circle', text: 'Unplayed' },
        'played': { icon: 'slash', text: 'Played' }
    };

    const watchedBtn = document.createElement('button');
    watchedBtn.type = 'button';
    watchedBtn.className = 'filter-toggle-btn movie-block-watched';

    const setWatchedBtnState = (state) => {
        const validState = watchedStateConfig[state] ? state : 'all';
        watchedBtn.dataset.state = validState;
        const config = watchedStateConfig[validState];
        watchedBtn.innerHTML = `<i data-feather="${config.icon}"></i> ${config.text}`;
        if (window.featherReplace) window.featherReplace();
    };

    watchedBtn.onclick = () => {
        const nextState = watchedStateCycle[watchedBtn.dataset.state];
        setWatchedBtnState(nextState);
        moviePreviewDebouncer();
    };

    setWatchedBtnState(filters.watched_status || 'all');

    const yearSliderWrapper = document.createElement('div');
    yearSliderWrapper.className = 'range-slider-wrapper';
    yearSliderWrapper.style.gridColumn = 'span 2';

    const yearDisplay = document.createElement('div');
    yearDisplay.className = 'range-slider-display';

    const sliderContainer = document.createElement('div');
    sliderContainer.className = 'range-slider-container';

    const sliderTrack = document.createElement('div');
    sliderTrack.className = 'range-slider-track';

    const sliderProgress = document.createElement('div');
    sliderProgress.className = 'range-slider-progress';

    const minYearInput = Object.assign(document.createElement('input'), { type: 'range', className: 'movie-block-year-from', min: 1920, max: new Date().getFullYear(), value: filters.year_from || 1920 });
    const maxYearInput = Object.assign(document.createElement('input'), { type: 'range', className: 'movie-block-year-to', min: 1920, max: new Date().getFullYear(), value: filters.year_to || new Date().getFullYear() });

    const updateYearSlider = () => {
        const minVal = parseInt(minYearInput.value, 10);
        const maxVal = parseInt(maxYearInput.value, 10);

        if (maxVal < minVal) {
            minYearInput.value = maxVal;
            maxYearInput.value = minVal;
        }

        const minPercent = ((minYearInput.value - minYearInput.min) / (minYearInput.max - minYearInput.min)) * 100;
        const maxPercent = ((maxYearInput.value - maxYearInput.min) / (maxYearInput.max - maxYearInput.min)) * 100;

        sliderProgress.style.left = `${minPercent}%`;
        sliderProgress.style.width = `${maxPercent - minPercent}%`;
        yearDisplay.textContent = `${minYearInput.value} - ${maxYearInput.value}`;
    };

    minYearInput.addEventListener('input', updateYearSlider);
    maxYearInput.addEventListener('input', updateYearSlider);
    minYearInput.addEventListener('change', moviePreviewDebouncer);
    maxYearInput.addEventListener('change', moviePreviewDebouncer);

    sliderContainer.append(sliderTrack, sliderProgress, minYearInput, maxYearInput);
    yearSliderWrapper.append(yearDisplay, sliderContainer);
    updateYearSlider();

    const sortStateCycle = {
        'Random': 'PremiereDate',
        'PremiereDate': 'DateCreated',
        'DateCreated': 'SortName',
        'SortName': 'Random'
    };
    const sortStateConfig = {
        'Random': { icon: 'shuffle', text: 'Random' },
        'PremiereDate': { icon: 'calendar', text: 'Release' },
        'DateCreated': { icon: 'plus', text: 'Added' },
        'SortName': { icon: 'chevrons-down', text: 'Name' }
    };

    const sortBtn = document.createElement('button');
    sortBtn.type = 'button';
    sortBtn.className = 'filter-toggle-btn movie-block-sort-by';

    const setSortBtnState = (state) => {
        const validState = sortStateConfig[state] ? state : 'Random';
        sortBtn.dataset.state = validState;
        const config = sortStateConfig[validState];
        sortBtn.innerHTML = `<i data-feather="${config.icon}"></i> Sort: ${config.text}`;
        if (window.featherReplace) window.featherReplace();
    };

    sortBtn.onclick = () => {
        const nextState = sortStateCycle[sortBtn.dataset.state];
        setSortBtnState(nextState);
        moviePreviewDebouncer();
    };

    setSortBtnState(filters.sort_by || 'Random');

    const limitWrapper = document.createElement('div');
    limitWrapper.className = 'limit-by-wrapper';

    const countRadio = Object.assign(document.createElement('input'), { type: 'radio', name: `limit-mode-${blockId}`, value: 'count' });
    const countLabel = Object.assign(document.createElement('label'), { textContent: 'Count' });
    countLabel.prepend(countRadio);

    const durationRadio = Object.assign(document.createElement('input'), { type: 'radio', name: `limit-mode-${blockId}`, value: 'duration' });
    const durationLabel = Object.assign(document.createElement('label'), { textContent: 'Duration' });
    durationLabel.prepend(durationRadio);

    const sharedInput = Object.assign(document.createElement('input'), { type: 'number', className: 'movie-block-limit-value', min: 1 });
    const unitsContainer = document.createElement('span');
    unitsContainer.className = 'limit-unit';

    const toggleLimitMode = () => {
        if (countRadio.checked) {
            unitsContainer.textContent = 'movies';
            if (sharedInput.dataset.lastMode === 'duration') {
                sharedInput.value = 3;
            }
            sharedInput.dataset.lastMode = 'count';
        } else {
            if (!unitsContainer.querySelector('select')) {
                const durationUnits = Object.assign(document.createElement('select'), { className: 'movie-block-limit-duration-units' });
                durationUnits.innerHTML = `<option value="60">Hours</option><option value="1">Minutes</option>`;
                unitsContainer.innerHTML = '';
                unitsContainer.appendChild(durationUnits);
            }
            if (sharedInput.dataset.lastMode === 'count') {
                sharedInput.value = 3;
            }
            sharedInput.dataset.lastMode = 'duration';
        }
        moviePreviewDebouncer();
    };

    countRadio.addEventListener('change', toggleLimitMode);
    durationRadio.addEventListener('change', toggleLimitMode);

    if (filters.duration_minutes) {
        durationRadio.checked = true;
        sharedInput.value = Math.round(filters.duration_minutes / 60) || 3;
        sharedInput.dataset.lastMode = 'duration';
    } else {
        countRadio.checked = true;
        sharedInput.value = filters.limit || 3;
        sharedInput.dataset.lastMode = 'count';
    }

    const sharedInputGroup = document.createElement('div');
    sharedInputGroup.className = 'input-group';
    sharedInputGroup.append(sharedInput, unitsContainer);

    limitWrapper.append(countLabel, durationLabel, sharedInputGroup);
    toggleLimitMode();
   
    otherFiltersGrid.append(watchedBtn, sortBtn, yearSliderWrapper, limitWrapper);

    filterDetails.append(filterSummary, otherFiltersGrid);
    otherFiltersFieldset.append(otherFiltersLegend, filterDetails);
    body.append(libraryFieldset, genreFieldset, peopleFieldset, otherFiltersFieldset);

    blockElement.append(summary, body);

    const genreStateCycle = { 'any': 'all', 'all': 'exclude', 'exclude': 'any' };
    const genreStateIcons = { 'any': '⊕', 'all': '✓', 'exclude': '⊖' };

    const addGenreToken = (genreName, state = 'any') => {
        if (genreTokenContainer.querySelector(`.token[data-name="${genreName}"]`)) return;
        const token = document.createElement('span');
        token.className = 'token token-genre';
        token.dataset.name = genreName;
        token.dataset.state = state;
        const stateSpan = document.createElement('span');
        stateSpan.className = 'token-state';
        stateSpan.textContent = genreStateIcons[state];
        stateSpan.title = 'Click to cycle state (Any -> All -> Exclude)';
        const nameSpan = document.createElement('span');
        nameSpan.textContent = genreName;
        stateSpan.onclick = () => {
            const currentState = token.dataset.state;
            const nextState = genreStateCycle[currentState];
            token.dataset.state = nextState;
            stateSpan.textContent = genreStateIcons[nextState];
            moviePreviewDebouncer();
        };
        const removeBtn = document.createElement('button');
        removeBtn.type = 'button';
        removeBtn.className = 'token-remove';
        removeBtn.innerHTML = '×';
        removeBtn.onclick = () => {
            token.remove();
            moviePreviewDebouncer();
        };
        token.append(stateSpan, nameSpan, removeBtn);
        genreTokenContainer.appendChild(token);
    };

    genreInput.addEventListener('input', (e) => {
        const searchTerm = e.target.value.trim().toLowerCase();
        genreSuggestionsContainer.innerHTML = '';
        if (searchTerm.length < 2) return;
        const matchingGenres = appState.movieGenreData.map(g => g.Name).filter(name => name.toLowerCase().includes(searchTerm)).slice(0, 10);
        if (matchingGenres.length > 0) {
            const ul = document.createElement('ul');
            matchingGenres.forEach(genreName => {
                const li = document.createElement('li');
                li.textContent = genreName;
                li.onclick = () => {
                    addGenreToken(genreName);
                    genreInput.value = '';
                    genreSuggestionsContainer.innerHTML = '';
                    genreInput.focus();
                    moviePreviewDebouncer();
                };
                ul.appendChild(li);
            });
            genreSuggestionsContainer.appendChild(ul);
        }
    });

    genreInput.addEventListener('blur', () => { setTimeout(() => { genreSuggestionsContainer.innerHTML = ''; }, 150); });

    const personStateCycle = { 'include': 'exclude', 'exclude': 'include' };
    const personStateIcons = { 'include': '⊕', 'exclude': '⊖' };

    const addToken = (item, type, state = 'include') => {
        const tokenKey = `${type}-${type === 'person' ? item.Id : item.Name}`;
        if (peopleTokenContainer.querySelector(`.token[data-key="${tokenKey}"]`)) return;
        const token = document.createElement('span');
        token.className = `token token-${type}`;
        token.dataset.key = tokenKey;
        token.dataset.type = type;
        token.dataset.name = item.Name;
        token.dataset.state = state;
        const stateSpan = document.createElement('span');
        stateSpan.className = 'token-state';
        stateSpan.textContent = personStateIcons[state];
        stateSpan.title = 'Click to cycle state (Include/Exclude)';
        const nameSpan = document.createElement('span');
        if (type === 'person') {
            token.dataset.id = item.Id;
            token.dataset.role = item.Role || '';
            nameSpan.textContent = `${item.Name} (${item.Role || 'Person'})`;
        } else {
            nameSpan.textContent = `${item.Name} (Studio)`;
        }
        stateSpan.onclick = () => {
            const currentState = token.dataset.state;
            const nextState = personStateCycle[currentState];
            token.dataset.state = nextState;
            stateSpan.textContent = personStateIcons[nextState];
            moviePreviewDebouncer();
        };
        const removeBtn = document.createElement('button');
        removeBtn.type = 'button';
        removeBtn.className = 'token-remove';
        removeBtn.innerHTML = '×';
        removeBtn.onclick = () => {
            token.remove();
            moviePreviewDebouncer();
        };
        token.append(stateSpan, nameSpan, removeBtn);
        peopleTokenContainer.appendChild(token);
    };

    personInput.addEventListener('input', debounce(async (e) => {
        const searchTerm = e.target.value.trim();
        personSuggestionsContainer.innerHTML = '';
        if (searchTerm.length < 2) return;
        try {
            const [people, studios] = await Promise.all([
                fetch(`api/people?name=${encodeURIComponent(searchTerm)}`).then(res => res.json()),
                fetch(`api/studios?name=${encodeURIComponent(searchTerm)}`).then(res => res.json())
            ]);
            if (people.length > 0 || studios.length > 0) {
                const ul = document.createElement('ul');
                if (people.length > 0) {
                    ul.innerHTML += `<li class="suggestion-header">People</li>`;
                    people.forEach(person => {
                        const li = document.createElement('li');
                        li.textContent = `${person.Name} (${person.Role || 'Person'})`;
                        li.onclick = () => {
                            addToken(person, 'person');
                            personInput.value = '';
                            personSuggestionsContainer.innerHTML = '';
                            moviePreviewDebouncer();
                        };
                        ul.appendChild(li);
                    });
                }
                if (studios.length > 0) {
                    ul.innerHTML += `<li class="suggestion-header">Studios</li>`;
                    studios.forEach(studio => {
                        const li = document.createElement('li');
                        li.textContent = studio.Name;
                        li.onclick = () => {
                            addToken(studio, 'studio');
                            personInput.value = '';
                            personSuggestionsContainer.innerHTML = '';
                            moviePreviewDebouncer();
                        };
                        ul.appendChild(li);
                    });
                }
                personSuggestionsContainer.appendChild(ul);
            }
        } catch (error) { console.error("Error fetching people/studios:", error); }
    }, 300));

    personInput.addEventListener('blur', () => { setTimeout(() => { personSuggestionsContainer.innerHTML = ''; }, 150); });

    if (filters.genres_any) { filters.genres_any.forEach(g => addGenreToken(g, 'any')); }
    if (filters.genres_all) { filters.genres_all.forEach(g => addGenreToken(g, 'all')); }
    if (filters.genres_exclude) { filters.genres_exclude.forEach(g => addGenreToken(g, 'exclude')); }
    if (filters.people) { filters.people.forEach(p => addToken(p, 'person', 'include')); }
    if (filters.exclude_people) { filters.exclude_people.forEach(p => addToken(p, 'person', 'exclude')); }
    if (filters.studios) { filters.studios.forEach(s => addToken({ Name: s }, 'studio', 'include')); }
    if (filters.exclude_studios) { filters.exclude_studios.forEach(s => addToken({ Name: s }, 'studio', 'exclude')); }

    blockElement.addEventListener('input', moviePreviewDebouncer);
    updateMovieBlockPreviewCount();

    return blockElement;
}

export function renderMusicBlock({ data = null, userSelectElement, changeCallback }) {
    const musicData = data?.music || {};
    const filters = musicData.filters || {};
    const blockId = `block-${Date.now()}`;

    const blockElement = document.createElement('details');
    blockElement.open = true;

    blockElement.className = 'mixed-block';
    blockElement.dataset.type = 'music';
    blockElement.dataset.id = blockId;

    const summary = document.createElement('summary');

    const header = document.createElement('div');
    header.className = 'mixed-block-header';
    const headerTitle = document.createElement('h3');
    headerTitle.innerHTML = `<i data-feather="music"></i> Music Block`;

    const rightControlsContainer = document.createElement('div');
    rightControlsContainer.className = 'mixed-block-controls';

    const previewCountSpan = document.createElement('span');
    previewCountSpan.className = 'music-block-preview-count';
    const summarySpan = document.createElement('span');
    summarySpan.className = 'music-block-preview-summary';

    const collapseIcon = document.createElement('span');
    collapseIcon.className = 'icon-btn collapse-toggle-btn';
    collapseIcon.innerHTML = `<i data-feather="chevron-up"></i>`;

    rightControlsContainer.append(
        previewCountSpan,
        summarySpan,
        createHeaderButton('copy', 'duplicate-block-btn', 'Duplicate Block'),
        createHeaderButton('x', 'danger delete-block-btn', 'Delete Block'),
        collapseIcon
    );
    const dragHandle = createHeaderButton('move', 'drag-handle', 'Drag to reorder');
    dragHandle.style.cursor = 'grab';

    header.append(dragHandle, headerTitle, rightControlsContainer);
    summary.appendChild(header);

    const body = document.createElement('div');
    body.className = 'mixed-block-body';

    const modeLabel = document.createElement('label');
    const modeSelect = Object.assign(document.createElement('select'), { className: 'music-block-mode' });
    modeSelect.innerHTML = `<option value="album">Add by Album</option><option value="artist_top">Add by Artist (Top Tracks)</option><option value="artist_random">Add by Artist (Random)</option><option value="genre">Add by Genre</option>`;
    modeSelect.value = musicData.mode || 'album';
    modeLabel.append('Mode:', modeSelect);

    const artistContainer = document.createElement('div');
    artistContainer.className = 'music-artist-container';
    const artistGrid = document.createElement('div');
    artistGrid.className = 'music-block-filter-grid';
    const artistLabel = document.createElement('label');
    const artistSearchInput = Object.assign(document.createElement('input'), { type: 'search', className: 'artist-search-input', placeholder: 'Filter artists...' });
    const artistSelect = Object.assign(document.createElement('select'), { className: 'music-block-artist' });
    artistSelect.innerHTML = '<option value="">-- Select Artist --</option>';
    appState.artistData.forEach(artist => artistSelect.add(new Option(artist.Name, artist.Id)));
    if (musicData.artistId) artistSelect.value = musicData.artistId;
    artistLabel.append('Artist:', artistSearchInput, artistSelect);
    const albumLabel = document.createElement('label');
    const albumSelect = Object.assign(document.createElement('select'), { className: 'music-block-album' });
    albumLabel.append('Album:', albumSelect);
    const countLabel = document.createElement('label');
    const countInput = Object.assign(document.createElement('input'), { type: 'number', className: 'music-block-count', value: musicData.count || 10, min: 1 });
    countLabel.append('Track Count:', countInput);
    artistGrid.append(artistLabel, albumLabel, countLabel);
    artistContainer.appendChild(artistGrid);

    const genreContainer = document.createElement('div');
    genreContainer.className = 'music-genre-container';
    const genreFieldset = document.createElement('fieldset');
    genreFieldset.className = 'filter-group';
    const genreLegend = document.createElement('legend');
    genreLegend.textContent = 'Genres';
    const genreDetails = document.createElement('details');
    const genreSummary = document.createElement('summary');
    genreSummary.textContent = 'Expand/Collapse Genre List';
    const genreGrid = document.createElement('div');
    genreGrid.className = 'checkbox-grid';
    const genreMatchToggle = document.createElement('div');
    genreMatchToggle.className = 'genre-match-toggle';

    if (appState.musicGenreData && appState.musicGenreData.length > 0) {
        appState.musicGenreData.forEach(g => {
            const label = document.createElement('label');
            const cb = Object.assign(document.createElement('input'), { type: 'checkbox', className: 'music-block-genre-cb', value: g.Name, checked: filters.genres?.includes(g.Name) });
            label.append(cb, ` ${g.Name}`);
            genreGrid.appendChild(label);
        });

        ['any', 'all', 'none'].forEach(val => {
            const label = document.createElement('label');
            const radio = Object.assign(document.createElement('input'), { type: 'radio', name: `music-block-genre-match-${blockId}`, value: val });

            if (filters.genre_match === val) {
                radio.checked = true;
            } else if (!filters.genre_match && val === 'any') {
                radio.checked = true;
            }

            let labelText = val.charAt(0).toUpperCase() + val.slice(1);
            if (val === 'any') labelText = 'Match Any';
            if (val === 'all') labelText = 'Match All';
            if (val === 'none') labelText = 'Exclude These';

            label.append(radio, ` ${labelText}`);
            genreMatchToggle.appendChild(label);
        });
    } else {
        const noGenresMessage = document.createElement('p');
        noGenresMessage.className = 'placeholder-text-small';
        noGenresMessage.textContent = 'No music genres found in your library to filter by.';
        genreGrid.appendChild(noGenresMessage);
        genreMatchToggle.style.display = 'none';
    }

    genreDetails.append(genreSummary, genreGrid, genreMatchToggle);
    genreFieldset.append(genreLegend, genreDetails);
    const otherFiltersGrid = document.createElement('div');
    otherFiltersGrid.className = 'music-block-filter-grid';
    const sortLabel = document.createElement('label');
    const sortSelect = Object.assign(document.createElement('select'), { className: 'music-block-sort-by' });
    sortSelect.innerHTML = `<option value="Random">Random</option><option value="PlayCount">Most Played</option><option value="DateCreated">Date Added</option><option value="Name">Name</option>`;
    sortSelect.value = filters.sort_by || 'Random';
    sortLabel.append('Sort By: ', sortSelect);
    const limitLabel = document.createElement('label');
    const limitInput = Object.assign(document.createElement('input'), { type: 'number', className: 'music-block-limit', placeholder: 'e.g., 25', value: filters.limit || 25, min: 1 });
    limitLabel.append('Limit: ', limitInput);
    otherFiltersGrid.append(sortLabel, limitLabel);

    genreContainer.append(genreFieldset, otherFiltersGrid);

    body.append(modeLabel, artistContainer, genreContainer);
    blockElement.append(summary, body);

    const musicPreviewDebouncer = debounce(() => {
        updateMusicBlockSummary(blockElement);
        if (modeSelect.value === 'genre') {
             updateMusicBlockPreviewCount(blockElement, userSelectElement);
        }
        if (changeCallback) changeCallback();
    }, 500);

    blockElement.addEventListener('input', musicPreviewDebouncer);

    const toggleFields = () => {
        const mode = modeSelect.value;
        artistContainer.style.display = (mode !== 'genre') ? 'block' : 'none';
        genreContainer.style.display = (mode === 'genre') ? 'block' : 'none';
        albumLabel.style.display = (mode === 'album') ? 'flex' : 'none';
        countLabel.style.display = (mode.startsWith('artist_')) ? 'flex' : 'none';
        previewCountSpan.style.display = (mode === 'genre') ? 'inline' : 'none';
        if (mode === 'genre') updateMusicBlockPreviewCount(blockElement, userSelectElement);
        updateMusicBlockSummary(blockElement);
    };

    artistSearchInput.addEventListener('input', debounce((e) => {
        const searchTerm = e.target.value.toLowerCase();
        Array.from(artistSelect.options).forEach(opt => {
            if (opt.value === '') return;
            opt.style.display = opt.textContent.toLowerCase().includes(searchTerm) ? '' : 'none';
        });
    }, 200));

    artistSelect.addEventListener('change', async () => {
        albumSelect.innerHTML = '<option>Loading albums...</option>';
        albumSelect.disabled = true;
        const artistId = artistSelect.value;
        updateMusicBlockSummary(blockElement);
        if (!artistId) {
            albumSelect.innerHTML = '';
            return;
        }
        try {
            const resp = await fetch(`api/music/artists/${artistId}/albums`);
            const albums = await resp.json();
            albumSelect.innerHTML = '<option value="">-- Select Album --</option>';
            albums.forEach(album => albumSelect.add(new Option(album.Name, album.Id)));
        } catch (e) {
            albumSelect.innerHTML = '<option>Error loading</option>';
        } finally {
            albumSelect.disabled = false;
        }
    });

    albumSelect.addEventListener('change', () => updateMusicBlockSummary(blockElement));

    modeSelect.addEventListener('change', toggleFields);
    toggleFields();
    if (musicData.artistId) {
        artistSelect.dispatchEvent(new Event('change'));
        if (musicData.albumId) {
            const observer = new MutationObserver(() => {
                if (!albumSelect.disabled) {
                    albumSelect.value = musicData.albumId;
                        updateMusicBlockSummary(blockElement);
                    observer.disconnect();
                }
            });
            observer.observe(albumSelect, { childList: true, subtree: true });
        }
    }

    return blockElement;
}