// Filename: static/js/scheduler.js
// VERSION 2 - DOM elements moved inside init to prevent race conditions.

import { post } from './utils.js';
import { confirmModal } from './modals.js';
import { SMART_BUILD_TYPES } from './definitions.js';

// --- Declare variables in the module scope ---
// They will be assigned inside the init function to ensure the DOM is ready.
let userSelect, createBtn, schedulesList, schedulePlaylistNameInput, scheduleSourceSelect,
    frequencySelect, scheduleTimeInput, daysContainer, daysCheckboxes,
    builderOptionsContainer, quickOptionsContainer, presetSelect, quickTypeSelect, quickCountInput;

// --- Non-DOM dependent constants can stay at the top level ---
const schedulableQuickPlaylists = SMART_BUILD_TYPES.filter(t => t.schedulable);
const quickPlaylistFriendlyNames = schedulableQuickPlaylists.reduce((acc, curr) => {
    acc[curr.type] = curr.name;
    return acc;
}, {});

function populateQuickPlaylistDropdown() {
    quickTypeSelect.innerHTML = ''; // Clear existing options
    schedulableQuickPlaylists.forEach(playlist => {
        const option = document.createElement('option');
        option.value = playlist.type;
        option.textContent = playlist.name;
        quickTypeSelect.appendChild(option);
    });
}

export function initSchedulerPane() {
    // --- Assign DOM elements inside the init function ---
    // This guarantees the elements exist when the script looks for them.
    userSelect = document.getElementById('user-select');
    createBtn = document.getElementById('create-schedule-btn');
    schedulesList = document.getElementById('schedules-list');
    schedulePlaylistNameInput = document.getElementById('schedule-playlist-name');
    scheduleSourceSelect = document.getElementById('schedule-source-select');
    frequencySelect = document.getElementById('schedule-frequency');
    scheduleTimeInput = document.getElementById('schedule-time-input');
    daysContainer = document.getElementById('schedule-days-container');
    daysCheckboxes = document.querySelectorAll('input[name="schedule-day"]');
    builderOptionsContainer = document.getElementById('schedule-builder-options');
    quickOptionsContainer = document.getElementById('schedule-quick-options');
    presetSelect = document.getElementById('schedule-preset-select');
    quickTypeSelect = document.getElementById('schedule-quick-type-select');
    quickCountInput = document.getElementById('schedule-quick-count-input');

    // --- The rest of the initialization logic ---
    populatePresetDropdown();
    populateQuickPlaylistDropdown();
    loadAndRenderSchedules();

    createBtn.addEventListener('click', handleCreateSchedule);
    scheduleSourceSelect.addEventListener('change', toggleSourceOptions);
    frequencySelect.addEventListener('change', toggleDaysOfWeek);
    quickTypeSelect.addEventListener('change', syncPlaylistName);
    presetSelect.addEventListener('change', syncPlaylistName);

    // Re-populate preset dropdown when presets are changed elsewhere
    document.getElementById('save-preset-confirm-btn').addEventListener('click', () => setTimeout(populatePresetDropdown, 100));
    document.getElementById('delete-preset-btn').addEventListener('click', () => setTimeout(populatePresetDropdown, 100));
    document.getElementById('import-preset-confirm-btn').addEventListener('click', () => setTimeout(populatePresetDropdown, 100));
}

function syncPlaylistName() {
    const sourceType = scheduleSourceSelect.value;
    if (sourceType === 'builder') {
        const presetName = presetSelect.options[presetSelect.selectedIndex].text;
        if (presetName && !presetName.startsWith('--')) {
            schedulePlaylistNameInput.value = presetName;
        }
    } else if (sourceType === 'quick_playlist') {
        const selectedType = quickTypeSelect.options[quickTypeSelect.selectedIndex].text;
        schedulePlaylistNameInput.value = `Scheduled: ${selectedType}`;
    }
}

function toggleSourceOptions() {
    const sourceType = scheduleSourceSelect.value;
    builderOptionsContainer.style.display = (sourceType === 'builder') ? 'block' : 'none';
    quickOptionsContainer.style.display = (sourceType === 'quick_playlist') ? 'block' : 'none';
    syncPlaylistName();
}

function toggleDaysOfWeek() {
    const isWeekly = frequencySelect.value === 'weekly';
    daysContainer.style.display = isWeekly ? 'block' : 'none';
}

async function getMixedPresets() {
    const response = await fetch('api/presets');
    if (!response.ok) return {};
    return await response.json();
}

async function populatePresetDropdown() {
    const presets = await getMixedPresets();
    const currentVal = presetSelect.value;
    presetSelect.innerHTML = '<option value="">-- Select a saved preset --</option>';
    for (const name in presets) {
        const option = document.createElement('option');
        option.value = name;
        option.textContent = name;
        presetSelect.appendChild(option);
    }
    if (presets[currentVal]) {
        presetSelect.value = currentVal;
    }
}

async function loadAndRenderSchedules() {
    const scheduleCountSpan = document.getElementById('schedule-count');
    const scheduleListContainer = document.getElementById('schedules-list-container');

    try {
        const response = await fetch('api/schedules');
        if (!response.ok) throw new Error('Failed to fetch schedules');
        const schedules = await response.json();

        scheduleCountSpan.textContent = `(${schedules.length})`;
        scheduleListContainer.style.display = schedules.length > 0 ? 'block' : 'none';

        schedulesList.innerHTML = '';
        if (schedules.length === 0) {
            schedulesList.innerHTML = '<li style="text-align: center; padding: 2rem; color: var(--text-subtle);">No schedules configured. <br> Use the form above to create your first automated playlist.</li>';
            return;
        }

        schedules.forEach(renderSchedule);

        if (typeof feather !== 'undefined') {
            feather.replace();
        }
    } catch (err) {
        console.error("Error loading schedules:", err);
        schedulesList.innerHTML = '<li>Error loading schedules.</li>';
    }
}

function renderSchedule(schedule) {
    let sourceText = 'unknown source';
    if (schedule.job_type === 'builder') {
        sourceText = `preset: <em>${schedule.preset_name || 'Unknown Preset'}</em>`;
    } else if (schedule.job_type === 'quick_playlist') {
        const friendlyName = quickPlaylistFriendlyNames[schedule.quick_playlist_data?.quick_playlist_type] || 'Auto Playlist';
        sourceText = `Auto Playlist: <em>${friendlyName}</em>`;
    }

    const [hour, minute] = schedule.schedule_details.time.split(':');
    const hourNum = parseInt(hour, 10);
    const ampm = hourNum >= 12 ? 'PM' : 'AM';
    const friendlyHour = ((hourNum + 11) % 12 + 1);
    const friendlyTime = `${friendlyHour}:${minute} ${ampm}`;

    let frequencyText = 'daily';
    if (schedule.schedule_details.frequency === 'weekly') {
        const dayMap = ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat'];
        const selectedDays = (schedule.schedule_details.days_of_week || []).map(d => dayMap[d]).join(', ');
        frequencyText = `every ${selectedDays}`;
    }

    const listItem = document.createElement('li');
    listItem.innerHTML = `
        <fieldset class="filter-group" style="margin-bottom: 1rem;">
            <legend>${schedule.playlist_name}</legend>
            <div class="schedule-item-content">
                <p class="schedule-details-text">
                    <span style="font-weight: bold; font-style: normal; font-size: 1.2em; color: var(--accent); margin-right: 0.5rem;">→</span>
                    Builds ${frequencyText} at ${friendlyTime} from ${sourceText}
                </p>
                <div class="schedule-status-container">
                    ${schedule.last_run ? `
                        <span class="last-run-status ${schedule.last_run.status === 'ok' ? 'status-success' : 'status-danger'}" title="${(schedule.last_run.log || []).join('\n')}">
                            <i data-feather="${schedule.last_run.status === 'ok' ? 'check-circle' : 'alert-circle'}"></i>
                        </span>
                        <span>Last run: ${new Date(schedule.last_run.timestamp).toLocaleString()}</span>
                    ` : '<span style="font-style: italic;">Never run</span>'}
                </div>
                <div class="schedule-button-container">
                    <button type="button" class="icon-btn run-now-btn" title="Run Schedule Now" data-id="${schedule.id}"><i data-feather="play"></i></button>
                    <button type="button" class="icon-btn danger delete-schedule-btn" title="Delete Schedule" data-id="${schedule.id}"><i data-feather="trash-2"></i></button>
                </div>
            </div>
        </fieldset>
    `;
    schedulesList.appendChild(listItem);

    listItem.querySelector('.run-now-btn').addEventListener('click', async (event) => {
        const res = await post(`api/schedules/${schedule.id}/run`, {}, event.currentTarget, 'POST');
        if (res.status === 'ok') {
            loadAndRenderSchedules();
        }
    });

    listItem.querySelector('.delete-schedule-btn').addEventListener('click', (event) => {
        confirmModal.show({
            title: 'Delete Schedule?',
            text: `Are you sure you want to delete the schedule for "${schedule.playlist_name}"?`,
            confirmText: 'Delete',
            onConfirm: async () => {
                const res = await post(`api/schedules/${schedule.id}`, {}, event.currentTarget, 'DELETE');
                if (res.status === 'ok') {
                    loadAndRenderSchedules();
                }
            }
        });
    });
}

async function handleCreateSchedule(event) {
    const sourceType = scheduleSourceSelect.value;
    const userId = userSelect.value;
    const frequency = frequencySelect.value;
    const selectedDays = [...daysCheckboxes].filter(cb => cb.checked).map(cb => parseInt(cb.value));
    const playlistName = schedulePlaylistNameInput.value.trim();
    const timeValue = scheduleTimeInput.value;

    if (!playlistName || !timeValue || !userId) {
        alert('Please provide a playlist name and select a time.');
        return;
    }
     if (frequency === 'weekly' && selectedDays.length === 0) {
        alert('Please select at least one day for a weekly schedule.');
        return;
    }

    const requestBody = {
        playlist_name: playlistName,
        user_id: userId,
        job_type: sourceType,
        schedule_details: {
            frequency: frequency,
            time: timeValue,
            days_of_week: frequency === 'weekly' ? selectedDays : null
        }
    };

    if (sourceType === 'builder') {
        const presetName = presetSelect.value;
        if (!presetName) {
            alert('Please select a Builder Preset to schedule.');
            return;
        }
        const presets = await getMixedPresets();
        const presetData = presets[presetName];
        if (!presetData) {
            alert('Could not find data for the selected preset.');
            return;
        }
        requestBody.preset_name = presetName;
        requestBody.blocks = presetData;

    } else if (sourceType === 'quick_playlist') {
        const quickType = quickTypeSelect.value;
        const count = parseInt(quickCountInput.value, 10);
        if (!quickType || !count || count < 1) {
            alert('Please select an Auto Playlist type and enter a valid number of items.');
            return;
        }
        requestBody.quick_playlist_data = {
            quick_playlist_type: quickType,
            options: { count: count }
        };
        requestBody.preset_name = quickPlaylistFriendlyNames[quickType] || 'Auto Playlist';
    }

    post('api/schedules', requestBody, event.currentTarget).then(res => {
        if (res.status === 'ok') {
            loadAndRenderSchedules();
            // Reset form to defaults
            scheduleSourceSelect.value = 'builder';
            toggleSourceOptions();
        }
    });
}