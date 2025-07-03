// static/js/scheduler.js
import { post, confirmModal } from './utils.js';

const presetSelect = document.getElementById('schedule-preset-select');
const timeSelect = document.getElementById('schedule-time-select');
const createBtn = document.getElementById('create-schedule-btn');
const schedulesList = document.getElementById('schedules-list');
const userSelect = document.getElementById('user-select');
const frequencySelect = document.getElementById('schedule-frequency');
const daysContainer = document.getElementById('schedule-days-container');
const daysCheckboxes = document.querySelectorAll('input[name="schedule-day"]');
const schedulePlaylistNameInput = document.getElementById('schedule-playlist-name');

export function initSchedulerPane() {
    populatePresetDropdown();
    loadAndRenderSchedules();
    createBtn.addEventListener('click', handleCreateSchedule);
    frequencySelect.addEventListener('change', toggleDaysOfWeek);

    presetSelect.addEventListener('change', (event) => {
        const presetName = event.target.value;
        if (presetName) {
            schedulePlaylistNameInput.value = presetName;
        }
    });

    document.getElementById('save-preset-confirm-btn').addEventListener('click', () => setTimeout(populatePresetDropdown, 100));
    document.getElementById('delete-preset-btn').addEventListener('click', () => setTimeout(populatePresetDropdown, 100));
    document.getElementById('import-preset-confirm-btn').addEventListener('click', () => setTimeout(populatePresetDropdown, 100));
}

function toggleDaysOfWeek() {
    const isWeekly = frequencySelect.value === 'weekly';
    daysContainer.style.display = isWeekly ? 'block' : 'none';
}

function getMixedPresets() {
    const presetsJSON = localStorage.getItem('mixerbeeMixedPresets');
    return presetsJSON ? JSON.parse(presetsJSON) : {};
}

function populatePresetDropdown() {
    const presets = getMixedPresets();
    const currentVal = presetSelect.value;
    presetSelect.innerHTML = '<option value="">-- Select a mixed preset --</option>';
    for (const name in presets) {
        if (name === '__autosave__') continue;
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
    try {
        const response = await fetch('api/schedules');
        if (!response.ok) throw new Error('Failed to fetch schedules');
        const schedules = await response.json();

        schedulesList.innerHTML = '';
        if (schedules.length === 0) {
            schedulesList.innerHTML = '<li style="color: var(--text-subtle);">No schedules configured.</li>';
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
    let friendlyText = '';
    const presetName = schedule.preset_name || 'Unknown Preset';

    if (schedule.schedule_details) {
        const scheduleDetails = schedule.schedule_details;
        friendlyText = 'Builds ';
        if (scheduleDetails.frequency === 'weekly') {
            const dayMap = ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat'];
            const selectedDays = (scheduleDetails.days_of_week || []).map(d => dayMap[d]).join(', ');
            friendlyText += `every ${selectedDays}`;
        } else {
            friendlyText += 'daily';
        }
        const [hour, minute] = scheduleDetails.time.split(':');
        const hourNum = parseInt(hour, 10);
        const ampm = hourNum >= 12 ? 'PM' : 'AM';
        const friendlyHour = ((hourNum + 11) % 12 + 1);
        const friendlyTime = `${friendlyHour}:${minute} ${ampm}`;

        friendlyText += ` at ${friendlyTime}`;
    } else {
        friendlyText = 'Builds on an unknown schedule';
    }

    const listItem = document.createElement('li');

    const fieldset = document.createElement('fieldset');
    fieldset.className = 'filter-group';
    fieldset.style.marginBottom = '1rem';

    const legend = document.createElement('legend');
    legend.textContent = schedule.playlist_name;

    const contentWrapper = document.createElement('div');
    contentWrapper.className = 'schedule-item-content';

    const detailsText = document.createElement('p');
    detailsText.className = 'schedule-details-text';
    detailsText.innerHTML = `
        <span style="font-weight: bold; font-style: normal; font-size: 1.2em; color: var(--accent); margin-right: 0.5rem;">→</span>
        ${friendlyText} from preset: <em>${presetName}</em>
    `;

    const statusContainer = document.createElement('div');
    statusContainer.className = 'schedule-status-container';

    if (schedule.last_run) {
        const statusIcon = document.createElement('i');
        const statusClass = schedule.last_run.status === 'ok' ? 'status-success' : 'status-danger';
        const iconName = schedule.last_run.status === 'ok' ? 'check-circle' : 'alert-circle';
        statusIcon.dataset.feather = iconName;

        const statusWrapper = document.createElement('span');
        statusWrapper.className = `last-run-status ${statusClass}`;
        statusWrapper.title = (schedule.last_run.log || []).join('\n');

        const timeText = document.createElement('span');
        const runDate = new Date(schedule.last_run.timestamp);
        timeText.textContent = `Last run: ${runDate.toLocaleString()}`;

        statusWrapper.appendChild(statusIcon);
        statusContainer.append(statusWrapper, timeText);
    } else {
        const timeText = document.createElement('span');
        timeText.textContent = 'Never run';
        timeText.style.fontStyle = 'italic';
        statusContainer.appendChild(timeText);
    }

    const buttonContainer = document.createElement('div');
    buttonContainer.className = 'schedule-button-container';
    
    const runBtn = document.createElement('button');
    runBtn.type = 'button';
    runBtn.className = 'icon-btn';
    runBtn.title = 'Run Schedule Now';
    runBtn.innerHTML = '<i data-feather="play"></i>';
    runBtn.addEventListener('click', async (event) => {
        const res = await post(`api/schedules/${schedule.id}/run`, {}, event, 'POST');
        if (res.status === 'ok') {
            loadAndRenderSchedules();
        }
    });

    const deleteBtn = document.createElement('button');
    deleteBtn.type = 'button';
    deleteBtn.className = 'icon-btn danger';
    deleteBtn.title = 'Delete Schedule';
    deleteBtn.innerHTML = '<i data-feather="trash-2"></i>';

    deleteBtn.addEventListener('click', (event) => {
        confirmModal.show({
            title: 'Delete Schedule?',
            text: `Are you sure you want to delete the schedule for "${schedule.playlist_name}"?`,
            confirmText: 'Delete',
            onConfirm: async () => {
                const res = await post(`api/schedules/${schedule.id}`, {}, event.target, 'DELETE');
                if (res.status === 'ok') {
                    loadAndRenderSchedules();
                }
            }
        });
    });
    
    buttonContainer.append(runBtn, deleteBtn);
    contentWrapper.append(detailsText, statusContainer, buttonContainer);
    fieldset.append(legend, contentWrapper);
    listItem.append(fieldset);

    schedulesList.appendChild(listItem);
}


function handleCreateSchedule() {
    const presetName = presetSelect.value;
    const timeValue = timeSelect.value;
    const userId = userSelect.value;
    const frequency = frequencySelect.value;
    const selectedDays = [...daysCheckboxes].filter(cb => cb.checked).map(cb => parseInt(cb.value));
    const playlistName = schedulePlaylistNameInput.value.trim();

    if (!presetName || !timeValue || !userId || !playlistName) {
        alert('Please select a preset, a time, and provide a playlist name.');
        return;
    }
    if (frequency === 'weekly' && selectedDays.length === 0) {
        alert('Please select at least one day for a weekly schedule.');
        return;
    }

    const presets = getMixedPresets();
    const presetData = presets[presetName];
    if (!presetData) {
        alert('Could not find data for the selected preset.');
        return;
    }

    const requestBody = {
        playlist_name: playlistName,
        user_id: userId,
        blocks: presetData,
        preset_name: presetName,
        schedule_details: {
            frequency: frequency,
            time: timeValue,
            days_of_week: frequency === 'weekly' ? selectedDays : null
        }
    };

    post('api/schedules', requestBody).then(res => {
        if (res.status === 'ok') {
            loadAndRenderSchedules();
        }
    });
}