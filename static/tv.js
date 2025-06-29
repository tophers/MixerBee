// static/tv.js
import { post, smartPlaylistModal } from './utils.js';
import { PresetManager, createTvShowRow } from './utils.js';

let tvSeriesList = [];
let tvShowBox;
let userSelectElement;
let tvPresetManager;

function getShowDataFromUI() {
    const shows = [...tvShowBox.children].map(r => {
        const sel = r.querySelector('select');
        const inputs = r.querySelectorAll('input[type="number"]');
        const cb = r.querySelector('.first-unwatched-cb');
        return {
            name: sel.value,
            s: inputs[0].value,
            e: inputs[1].value,
            unwatched: cb.checked
        };
    });
    return { shows, count: document.getElementById('count').value };
}

function applyPresetToUI(preset) {
    tvShowBox.innerHTML = '';
    if (preset && preset.shows) {
        document.getElementById('count').value = preset.count || '5';
        preset.shows.forEach(show => {
            const newRow = createTvShowRow({
                rowData: show,
                seriesData: tvSeriesList,
                userSelectElement: userSelectElement,
                changeCallback: saveCurrentStateToPreset
            });
            tvShowBox.appendChild(newRow);
        });
    } else {
        const newRow = createTvShowRow({
            seriesData: tvSeriesList,
            userSelectElement: userSelectElement,
            changeCallback: saveCurrentStateToPreset
        });
        tvShowBox.appendChild(newRow);
    }
}

function saveCurrentStateToPreset() {
    tvPresetManager.presets['__autosave__'] = getShowDataFromUI();
    tvPresetManager.savePresets();
}

export function initTvPane(showBoxElement, seriesData, userSel) {
    tvShowBox = showBoxElement;
    tvSeriesList = seriesData;
    userSelectElement = userSel;

    tvPresetManager = new PresetManager('mixerbeeTvPresets', {
        loadSelect: document.getElementById('tv-load-preset-select'),
        saveBtn: document.getElementById('tv-save-preset-btn'),
        deleteBtn: document.getElementById('tv-delete-preset-btn'),
        importBtn: document.getElementById('tv-import-preset-btn'), 
        exportBtn: document.getElementById('tv-export-preset-btn') 
    });
    tvPresetManager.init(getShowDataFromUI, applyPresetToUI);

    new Sortable(tvShowBox, {
        animation: 150,
        handle: '.drag-handle',
        ghostClass: 'sortable-ghost',
        onEnd: saveCurrentStateToPreset
    });

    const lastState = tvPresetManager.presets['__autosave__'];
    if(lastState && lastState.shows?.length > 0) {
        applyPresetToUI(lastState);
    } else {
        applyPresetToUI(null);
    }

    document.getElementById('pilot-sampler-btn').addEventListener('click', (event) => {
        smartPlaylistModal.show({
            title: 'Pilot Sampler',
            description: 'This will create a playlist with random, unwatched pilot episodes from your library.',
            countLabel: 'Number of Pilots',
            defaultCount: 10,
            defaultName: 'Pilot Sampler',
            onCreate: ({ playlistName, count }) => {
                post('api/create_pilot_sampler', {
                    user_id: userSelectElement.value,
                    playlist_name: playlistName,
                    count: count
                }, event);
            }
        });
    });

    document.getElementById('continue-watching-btn').addEventListener('click', (event) => {
        smartPlaylistModal.show({
            title: 'Continue Watching',
            description: 'This will create a playlist with the next unwatched episode from your most recent in-progress shows.',
            countLabel: 'Number of Shows',
            defaultCount: 10,
            defaultName: 'Continue Watching',
            onCreate: ({ playlistName, count }) => {
                post('api/create_continue_watching_playlist', {
                    user_id: userSelectElement.value,
                    playlist_name: playlistName,
                    count: count
                }, event);
            }
        });
    });

    document.getElementById('add-btn').onclick = () => {
        const newRow = createTvShowRow({
            seriesData: tvSeriesList,
            userSelectElement: userSelectElement,
            changeCallback: saveCurrentStateToPreset
        });
        tvShowBox.appendChild(newRow);
        saveCurrentStateToPreset();
    };

    document.getElementById('clear-btn').onclick = () => {
        if (confirm('Are you sure?')) {
            applyPresetToUI(null);
            saveCurrentStateToPreset();
        }
    };

    document.getElementById('create-tv-mix-btn').onclick = (event) => {
        const uiData = getShowDataFromUI();
        const showsForApi = uiData.shows.map(s => `${s.name}::S${String(s.s).padStart(2,'0')}E${String(s.e).padStart(2,'0')}`);
        const playlistName = document.getElementById('global-playlist-name').value;
        post('api/mix', { shows: showsForApi, count: +uiData.count, playlist: playlistName, target_uid: userSelectElement.value }, event);
    };

    tvShowBox.addEventListener('delete-row', (event) => {
        if (tvShowBox.children.length > 1) {
            event.target.remove();
            saveCurrentStateToPreset();
        }
    });

    document.getElementById('count').addEventListener('input', saveCurrentStateToPreset);
}

