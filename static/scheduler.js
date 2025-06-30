import { post } from './utils.js';

const presetSelect = document.getElementById('schedule-preset-select');
const timeSelect = document.getElementById('schedule-time-select');
const createBtn = document.getElementById('create-schedule-btn');
const schedulesList = document.getElementById('schedules-list');
const userSelect = document.getElementById('user-select');
const frequencySelect = document.getElementById('schedule-frequency');
const daysContainer = document.getElementById('schedule-days-container');
const daysCheckboxes = document.querySelectorAll('input[name="schedule-day"]');

export function initSchedulerPane() {
    populatePresetDropdown();
    loadAndRenderSchedules();
    createBtn.addEventListener('click', handleCreateSchedule);
    frequencySelect.addEventListener('change', toggleDaysOfWeek);

    document.getElementById('save-preset-btn').addEventListener('click', () => setTimeout(populatePresetDropdown, 100));
    document.getElementById('delete-preset-btn').addEventListener('click', () => setTimeout(populatePresetDropdown, 100));
}

// UI Logic

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
    presetSelect.innerHTML = '<option value="">-- Select a mixed preset --</option>';
    for (const name in presets) {
        if (name === '__autosave__') continue;
        const option = document.createElement('option');
        option.value = name;
        option.textContent = name;
        presetSelect.appendChild(option);
    }
}

// Data

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

    } else if (schedule.crontab) {
        friendlyText = `Builds on a legacy schedule (${schedule.crontab})`;
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
    contentWrapper.style.display = 'flex';
    contentWrapper.style.justifyContent = 'space-between';
    contentWrapper.style.alignItems = 'center';
    contentWrapper.style.padding = '0.2rem';

    const detailsText = document.createElement('p');
    detailsText.style.margin = '0';
    detailsText.style.fontStyle = 'italic';
    detailsText.style.color = 'var(--text-subtle)';
    detailsText.innerHTML = `
        <span style="font-weight: bold; font-style: normal; font-size: 1.2em; color: var(--accent); margin-right: 0.5rem;">→</span>
        ${friendlyText} from preset: <em>${presetName}</em>
    `;

    const deleteBtn = document.createElement('button');
    deleteBtn.type = 'button';
    deleteBtn.className = 'icon-btn danger';
    deleteBtn.title = 'Delete Schedule';
    deleteBtn.innerHTML = '&times;'; // The 'x' character for delete

    deleteBtn.addEventListener('click', async (event) => {
        if (confirm(`Are you sure you want to delete the schedule for "${schedule.playlist_name}"?`)) {
            await post(`api/schedules/${schedule.id}`, {}, event, 'DELETE');
            loadAndRenderSchedules();
        }
    });

    contentWrapper.appendChild(detailsText);
    contentWrapper.appendChild(deleteBtn);
    fieldset.appendChild(legend);
    fieldset.appendChild(contentWrapper);
    listItem.appendChild(fieldset);

    schedulesList.appendChild(listItem);
}


function handleCreateSchedule() {
    const presetName = presetSelect.value;
    const timeValue = timeSelect.value;
    const userId = userSelect.value;
    const frequency = frequencySelect.value;
    const selectedDays = [...daysCheckboxes].filter(cb => cb.checked).map(cb => parseInt(cb.value));

    if (!presetName || !timeValue || !userId) {
        alert('Please select a user, a preset, and a time.');
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

    const playlistName = document.getElementById('global-playlist-name').value;

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

    post('api/schedules', requestBody).then(status => {
        if (status === 'ok') {
            loadAndRenderSchedules();
        }
    });
}