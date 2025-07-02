// static/js/block_renderers.js
import { debounce } from './utils.js';
import { createTvShowRow } from './utils.js';

const icon = (txt, cls, title) => Object.assign(document.createElement('button'), { type: 'button', className: 'icon-btn ' + cls, textContent: txt, title: title });

async function updateMovieBlockPreviewCount(blockElement, userSelectElement) {
    const countSpan = blockElement.querySelector('.movie-block-preview-count');
    if (!countSpan) return;
    countSpan.textContent = '...';
    const yearFrom = blockElement.querySelector('.movie-block-year-from').value;
    const yearTo = blockElement.querySelector('.movie-block-year-to').value;
    const filters = {
        genres: [...blockElement.querySelectorAll('.movie-block-genre-cb:checked')].map(cb => cb.value),
        genre_match: blockElement.querySelector(`input[name^="movie-block-genre-match-"]:checked`).value,
        watched_status: blockElement.querySelector('.movie-block-watched').value,
        year_from: yearFrom ? parseInt(yearFrom) : undefined,
        year_to: yearTo ? parseInt(yearTo) : undefined,
        sort_by: blockElement.querySelector('.movie-block-sort-by').value,
        parent_ids: [...blockElement.querySelectorAll('.movie-block-library-cb:checked')].map(cb => cb.value)
    };

    const requestBody = { user_id: userSelectElement.value, filters };
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

async function updateMusicBlockPreviewCount(blockElement, userSelectElement) {
    const countSpan = blockElement.querySelector('.music-block-preview-count');
    if (!countSpan) return;
    countSpan.textContent = '...';

    const filters = {
        genres: [...blockElement.querySelectorAll('.music-block-genre-cb:checked')].map(cb => cb.value),
        genre_match: blockElement.querySelector(`input[name^="music-block-genre-match-"]:checked`).value,
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


export function renderTvBlock({ data = null, seriesData, userSelectElement, changeCallback }) {
    const initialRows = data?.shows || [{}];
    const isInterleaved = (data?.interleave !== false);

    const blockElement = document.createElement('div');
    blockElement.className = 'mixed-block';
    blockElement.dataset.type = 'tv';

    const header = document.createElement('div');
    header.className = 'mixed-block-header';
    const headerTitle = document.createElement('h3');
    headerTitle.innerHTML = `<span class="block-icon">📺</span> TV Block`;
    const headerControls = document.createElement('div');
    headerControls.className = 'mixed-block-controls';
    headerControls.append(icon('×', 'danger delete-block-btn', 'Delete Block'));
    header.append(icon('↕', 'drag-handle icon-btn', 'Drag to reorder'), headerTitle, headerControls);

    const body = document.createElement('div');
    body.className = 'mixed-block-body';

    const showsContainer = document.createElement('div');
    showsContainer.className = 'tv-block-shows';
    initialRows.forEach(rowData => {
        const newRow = createTvShowRow({ rowData, seriesData, userSelectElement, changeCallback });
        showsContainer.appendChild(newRow);
    });

    const addShowBtn = Object.assign(document.createElement('button'), { type: 'button', className: 'secondary add-show-row-btn', textContent: '➕ Add Show' });
    const buttonGroup = document.createElement('div');
    buttonGroup.className = 'button-group';
    buttonGroup.appendChild(addShowBtn);

    const footer = document.createElement('div');
    footer.className = 'block-options-footer';
    const countLabel = document.createElement('label');
    const countInput = Object.assign(document.createElement('input'), { type: 'number', className: 'tv-block-count', value: data?.count || 1, min: 1 });
    countLabel.append('Episodes per show: ', countInput);
    const interleaveLabel = document.createElement('label');
    interleaveLabel.className = 'interleave-label';
    const interleaveCb = Object.assign(document.createElement('input'), { type: 'checkbox', className: 'tv-block-interleave', checked: isInterleaved });
    interleaveLabel.append(interleaveCb, ' Interleave');
    footer.append(countLabel, interleaveLabel);

    body.append(showsContainer, buttonGroup, footer);
    blockElement.append(header, body);

    return blockElement;
}

export function renderMovieBlock({ data = null, libraryData, movieGenreData, userSelectElement }) {
    const filters = data?.filters || {};
    const blockId = `block-${Date.now()}`;

    const blockElement = document.createElement('div');
    blockElement.className = 'mixed-block';
    blockElement.dataset.type = 'movie';
    blockElement.dataset.id = blockId;

    const header = document.createElement('div');
    header.className = 'mixed-block-header';
    const headerTitle = document.createElement('h3');
    headerTitle.innerHTML = `<span class="block-icon">🎬</span> Movie Block`;
    const headerControls = document.createElement('div');
    headerControls.className = 'mixed-block-controls';
    headerControls.append(icon('×', 'danger delete-block-btn', 'Delete Block'));
    header.append(icon('↕', 'drag-handle icon-btn', 'Drag to reorder'), headerTitle, headerControls);

    const body = document.createElement('div');
    body.className = 'mixed-block-body';

    const libraryFieldset = document.createElement('fieldset');
    libraryFieldset.className = 'filter-group';
    const libraryLegend = document.createElement('legend');
    libraryLegend.textContent = 'Libraries';
    const libraryGrid = document.createElement('div');
    libraryGrid.className = 'checkbox-grid';
    libraryData.forEach(lib => {
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
    genreSummary.textContent = 'Expand/Collapse Genre List';
    const genreGrid = document.createElement('div');
    genreGrid.className = 'checkbox-grid';
    movieGenreData.forEach(g => {
        const label = document.createElement('label');
        const cb = Object.assign(document.createElement('input'), { type: 'checkbox', className: 'movie-block-genre-cb', value: g.Name, checked: filters.genres?.includes(g.Name) });
        label.append(cb, ` ${g.Name}`);
        genreGrid.appendChild(label);
    });
    const genreMatchToggle = document.createElement('div');
    genreMatchToggle.className = 'genre-match-toggle';
    ['any', 'all'].forEach(val => {
        const label = document.createElement('label');
        const radio = Object.assign(document.createElement('input'), { type: 'radio', name: `movie-block-genre-match-${blockId}`, value: val });
        if ((val === 'any' && filters.genre_match !== 'all') || !filters.genre_match) radio.checked = true;
        if (val === 'all' && filters.genre_match === 'all') radio.checked = true;
        label.append(radio, ` Match ${val.charAt(0).toUpperCase() + val.slice(1)}`);
        genreMatchToggle.appendChild(label);
    });
    genreDetails.append(genreSummary, genreGrid, genreMatchToggle);
    genreFieldset.append(genreLegend, genreDetails);

    const otherFiltersFieldset = document.createElement('fieldset');
    otherFiltersFieldset.className = 'filter-group';
    const otherFiltersLegend = document.createElement('legend');
    otherFiltersLegend.textContent = 'Filters';
    const filterDetails = document.createElement('details');
    const filterSummary = document.createElement('summary');
    filterSummary.textContent = 'Expand/Collapse Filters';
    const otherFiltersGrid = document.createElement('div');
    otherFiltersGrid.className = 'movie-block-filter-grid';
    const watchedLabel = document.createElement('label');
    const watchedSelect = Object.assign(document.createElement('select'), { className: 'movie-block-watched' });
    watchedSelect.innerHTML = `<option value="all">All</option><option value="unplayed">Unwatched Only</option><option value="played">Watched Only</option>`;
    watchedSelect.value = filters.watched_status || 'all';
    watchedLabel.append('Watched: ', watchedSelect);
    const yearFromLabel = document.createElement('label');
    const yearFromInput = Object.assign(document.createElement('input'), { type: 'number', className: 'movie-block-year-from', placeholder: 'e.g., 1980', value: filters.year_from || '' });
    yearFromLabel.append('From Year: ', yearFromInput);
    const yearToLabel = document.createElement('label');
    const yearToInput = Object.assign(document.createElement('input'), { type: 'number', className: 'movie-block-year-to', placeholder: 'e.g., 1989', value: filters.year_to || '' });
    yearToLabel.append('To Year: ', yearToInput);
    const sortLabel = document.createElement('label');
    const sortSelect = Object.assign(document.createElement('select'), { className: 'movie-block-sort-by' });
    sortSelect.innerHTML = `<option value="Random">Random</option><option value="PremiereDate">Release Date</option><option value="DateCreated">Date Added</option><option value="SortName">Name</option>`;
    sortSelect.value = filters.sort_by || 'Random';
    sortLabel.append('Sort By: ', sortSelect);
    const limitLabel = document.createElement('label');
    const limitSelect = Object.assign(document.createElement('select'), { className: 'movie-block-limit-select' });
    limitSelect.innerHTML = `<optgroup label="By Count"><option value="limit:1">1 Movie</option><option value="limit:2">2 Movies</option><option value="limit:3">3 Movies</option><option value="limit:5">5 Movies</option><option value="limit:10">10 Movies</option></optgroup><optgroup label="By Duration"><option value="duration:180">~3 Hours</option><option value="duration:240">~4 Hours</option><option value="duration:360">~6 Hours</option><option value="duration:480">~8 Hours</option><option value="duration:600">~10 Hours</option></optgroup><option value="">All Matching Movies</option>`;
    if (filters.duration_minutes) limitSelect.value = `duration:${filters.duration_minutes}`;
    else if (filters.limit) limitSelect.value = `limit:${filters.limit}`;
    else limitSelect.value = 'limit:1';
    limitLabel.append('Limit: ', limitSelect);
    otherFiltersGrid.append(watchedLabel, yearFromLabel, yearToLabel, sortLabel, limitLabel);
    const movieBlockFooter = document.createElement('div');
    movieBlockFooter.className = 'movie-block-footer';
    const previewCountSpan = document.createElement('span');
    previewCountSpan.className = 'movie-block-preview-count';
    movieBlockFooter.appendChild(previewCountSpan);
    filterDetails.append(filterSummary, otherFiltersGrid, movieBlockFooter);
    otherFiltersFieldset.append(otherFiltersLegend, filterDetails);
    body.append(libraryFieldset, genreFieldset, otherFiltersFieldset);
    blockElement.append(header, body);

    const moviePreviewDebouncer = debounce(() => updateMovieBlockPreviewCount(blockElement, userSelectElement), 500);
    blockElement.addEventListener('input', moviePreviewDebouncer);
    updateMovieBlockPreviewCount(blockElement, userSelectElement);

    return blockElement;
}

export function renderMusicBlock({ data = null, artistData, musicGenreData, userSelectElement }) {
    const musicData = data?.music || {};
    const filters = musicData.filters || {};
    const blockId = `block-${Date.now()}`;

    const blockElement = document.createElement('div');
    blockElement.className = 'mixed-block';
    blockElement.dataset.type = 'music';
    blockElement.dataset.id = blockId;

    const header = document.createElement('div');
    header.className = 'mixed-block-header';
    const headerTitle = document.createElement('h3');
    headerTitle.innerHTML = `<span class="block-icon">🎵</span> Music Block`;
    const headerControls = document.createElement('div');
    headerControls.className = 'mixed-block-controls';
    headerControls.append(icon('×', 'danger delete-block-btn', 'Delete Block'));
    header.append(icon('↕', 'drag-handle icon-btn', 'Drag to reorder'), headerTitle, headerControls);

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
    artistData.forEach(artist => artistSelect.add(new Option(artist.Name, artist.Id)));
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
    musicGenreData.forEach(g => {
        const label = document.createElement('label');
        const cb = Object.assign(document.createElement('input'), { type: 'checkbox', className: 'music-block-genre-cb', value: g.Name, checked: filters.genres?.includes(g.Name) });
        label.append(cb, ` ${g.Name}`);
        genreGrid.appendChild(label);
    });
    const genreMatchToggle = document.createElement('div');
    genreMatchToggle.className = 'genre-match-toggle';
    ['any', 'all'].forEach(val => {
        const label = document.createElement('label');
        const radio = Object.assign(document.createElement('input'), { type: 'radio', name: `music-block-genre-match-${blockId}`, value: val });
        if ((val === 'any' && filters.genre_match !== 'all') || !filters.genre_match) radio.checked = true;
        if (val === 'all' && filters.genre_match === 'all') radio.checked = true;
        label.append(radio, ` Match ${val.charAt(0).toUpperCase() + val.slice(1)}`);
        genreMatchToggle.appendChild(label);
    });
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
    const musicBlockFooter = document.createElement('div');
    musicBlockFooter.className = 'movie-block-footer';
    const previewCountSpan = document.createElement('span');
    previewCountSpan.className = 'music-block-preview-count';
    musicBlockFooter.appendChild(previewCountSpan);
    genreContainer.append(genreFieldset, otherFiltersGrid, musicBlockFooter);
    
    body.append(modeLabel, artistContainer, genreContainer);
    blockElement.append(header, body);

    const musicPreviewDebouncer = debounce(() => updateMusicBlockPreviewCount(blockElement, userSelectElement), 500);
    blockElement.addEventListener('input', (e) => {
        if (e.target.closest('.music-genre-container')) musicPreviewDebouncer();
    });

    const toggleFields = () => {
        const mode = modeSelect.value;
        artistContainer.style.display = (mode !== 'genre') ? 'block' : 'none';
        genreContainer.style.display = (mode === 'genre') ? 'block' : 'none';
        albumLabel.style.display = (mode === 'album') ? 'flex' : 'none';
        countLabel.style.display = (mode.startsWith('artist_')) ? 'flex' : 'none';
        if (mode === 'genre') updateMusicBlockPreviewCount(blockElement, userSelectElement);
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
    modeSelect.addEventListener('change', toggleFields);
    toggleFields();
    if (musicData.artistId) {
        artistSelect.dispatchEvent(new Event('change'));
        if (musicData.albumId) {
            const observer = new MutationObserver(() => {
                if (!albumSelect.disabled) {
                    albumSelect.value = musicData.albumId;
                    observer.disconnect();
                }
            });
            observer.observe(albumSelect, { childList: true, subtree: true });
        }
    }

    return blockElement;
}