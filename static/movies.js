// static/movies.js
import { post, debounce, PresetManager, smartPlaylistModal } from './utils.js';

let userSelectElement;

function applyPresetToUI(preset) {
    if (!preset) return;
    document.querySelectorAll('#movie-genre-list input[type="checkbox"]').forEach(cb => {
        cb.checked = (preset.genres && preset.genres.includes(cb.value));
    });
    const genreMatchEl = document.querySelector(`input[name="genre-match"][value="${preset.genre_match || 'any'}"]`);
    if (genreMatchEl) genreMatchEl.checked = true;

    document.getElementById('movie-watched-status').value = preset.watched_status || 'all';
    document.getElementById('movie-year-from').value = preset.year_from || '';
    document.getElementById('movie-year-to').value = preset.year_to || '';
    document.getElementById('movie-duration-target').value = preset.duration_minutes ?? '360';
    document.getElementById('movie-sort-by').value = preset.sort_by || 'Random';
}

function getFiltersFromUI(forApi = false) {
    const selectedGenres = [...document.querySelectorAll('#movie-genre-list input:checked')].map(cb => cb.value);
    const yearFrom = document.getElementById('movie-year-from').value;
    const yearTo = document.getElementById('movie-year-to').value;
    const duration = document.getElementById('movie-duration-target').value;
    
    let durationMinutes = forApi
        ? (duration ? parseInt(duration) : undefined)
        : duration;

    return {
        genres: selectedGenres.length > 0 ? selectedGenres : undefined,
        genre_match: document.querySelector('input[name="genre-match"]:checked').value,
        watched_status: document.getElementById('movie-watched-status').value,
        year_from: yearFrom ? parseInt(yearFrom) : undefined,
        year_to: yearTo ? parseInt(yearTo) : undefined,
        duration_minutes: durationMinutes,
        sort_by: document.getElementById('movie-sort-by').value,
    };
}

async function updatePreviewCount() {
    const countSpan = document.getElementById('movie-preview-count');
    if (!countSpan) return;
    countSpan.textContent = '...';
    
    const previewFilters = getFiltersFromUI(true);
    previewFilters.duration_minutes = undefined;
    previewFilters.limit = undefined;

    const requestBody = { user_id: userSelectElement.value, filters: previewFilters };
    
    try {
        const response = await fetch('api/movies/preview_count', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(requestBody)
        });
        if (!response.ok) throw new Error(`HTTP error! status: ${response.status}`);
        const data = await response.json();
        countSpan.textContent = `${data.count} movies match filters`;
    } catch (error) {
        console.error("Error fetching movie preview count:", error);
        countSpan.textContent = 'Error!';
    }
}

function renderMovieGenres(genres) {
    const genreListDiv = document.getElementById('movie-genre-list');
    genreListDiv.innerHTML = '';
    genres.forEach(genre => {
        const label = document.createElement('label');
        const checkbox = Object.assign(document.createElement('input'), { type: 'checkbox', value: genre.Name });
        label.appendChild(checkbox);
        label.appendChild(document.createTextNode(` ${genre.Name}`));
        genreListDiv.appendChild(label);
    });
}

export function initMoviesPane(userSel, genreData) {
    userSelectElement = userSel;
    renderMovieGenres(genreData);

    const moviePresetManager = new PresetManager('mixerbeeMoviePresets', {
        loadSelect: document.getElementById('movie-load-preset-select'),
        saveBtn: document.getElementById('movie-save-preset-btn'),
        deleteBtn: document.getElementById('movie-delete-preset-btn'),
        importBtn: document.getElementById('movie-import-preset-btn'), // NEW
        exportBtn: document.getElementById('movie-export-preset-btn')  // NEW
    });
    moviePresetManager.init(
        () => getFiltersFromUI(false),
        (presetData) => {
            applyPresetToUI(presetData);
            debouncedUpdate();
        }
    );

    const debouncedUpdate = debounce(updatePreviewCount, 500);

    const filterContainer = document.getElementById('movies-pane');
    filterContainer.addEventListener('input', (event) => {
        if (event.target.matches('input, select')) {
            debouncedUpdate();
        }
    });
    userSelectElement.addEventListener('change', debouncedUpdate);
    updatePreviewCount();

    document.getElementById('create-movie-playlist-btn').addEventListener('click', (event) => {
        const filtersForApi = getFiltersFromUI(true);
        filtersForApi.movie_playlist_name = document.getElementById('global-playlist-name').value;
        post('api/create_movie_playlist', { user_id: userSelectElement.value, filters: filtersForApi }, event);
    });

    document.getElementById('forgotten-favorites-btn').addEventListener('click', (event) => {
        smartPlaylistModal.show({
            title: 'Forgotten Favorites',
            description: 'This will create a playlist of favorited movies you haven\'t seen in a while.',
            countLabel: 'Number of Movies',
            defaultCount: 20,
            defaultName: 'Forgotten Favorites',
            onCreate: ({ playlistName, count }) => {
                post('api/create_forgotten_favorites', {
                    user_id: userSelectElement.value,
                    playlist_name: playlistName,
                    count: count
                }, event);
            }
        });
    });

    document.getElementById('reset-movie-filters-btn').addEventListener('click', () => {
        applyPresetToUI({ genres: [], genre_match: 'any', watched_status: 'all' });
        debouncedUpdate();
    });
}

