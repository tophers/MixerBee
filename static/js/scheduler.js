// Filename: static/js/scheduler.js

import { post, toast } from './utils.js';
import { confirmModal } from './modals.js';
import { SMART_BUILD_TYPES } from './definitions.js';

let userSelect, createBtn, schedulesList, schedulePlaylistNameInput, scheduleSourceSelect,
    frequencySelect, scheduleTimeInput, daysContainer, daysCheckboxes,
    builderOptionsContainer, quickOptionsContainer, presetSelect, quickTypeSelect, quickCountInput;

const schedulableQuickPlaylists = SMART_BUILD_TYPES.filter(t => t.schedulable);
const quickPlaylistFriendlyNames = schedulableQuickPlaylists.reduce((acc, curr) => {
    acc[curr.type] = curr.name;
    return acc;
}, {});

function populateQuickPlaylistDropdown() {
  quickTypeSelect.innerHTML = '';
  schedulableQuickPlaylists.forEach(playlist => {
    const option = document.createElement('option');
    option.value = playlist.type;
    option.textContent = playlist.name;
    quickTypeSelect.appendChild(option);
  });
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
  builderOptionsContainer.classList.toggle('hidden', sourceType !== 'builder');
  quickOptionsContainer.classList.toggle('hidden', sourceType !== 'quick_playlist');
  syncPlaylistName();
}

function toggleDaysOfWeek() {
  const isWeekly = frequencySelect.value === 'weekly';
  daysContainer.classList.toggle('hidden', !isWeekly);
}

async function getMixedPresets() {
  try {
    const response = await fetch('api/presets');
    if (!response.ok) return {};
    return await response.json();
  } catch (err) {
    console.error('Failed to fetch presets for scheduler.', err);
    return {};
  }
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

export async function loadSchedulerData() {
    const scheduleCountSpan = document.getElementById('schedule-count');
    const scheduleListContainer = document.getElementById('schedules-list-container');
    const schedulesListEl = document.getElementById('schedules-list');
    try {
        const response = await fetch('api/schedules');
        if (!response.ok) throw new Error('Failed to fetch schedules');
        const schedules = await response.json();
        scheduleCountSpan.textContent = `(${schedules.length})`;
        scheduleListContainer.classList.toggle('hidden', schedules.length === 0);
        schedulesListEl.innerHTML = '';
        if (schedules.length === 0) {
            schedulesListEl.innerHTML = '<li style="text-align: center; padding: 2rem; color: var(--text-subtle);">No schedules configured.</li>';
            return;
        }
        schedules.forEach(schedule => renderSchedule(schedule, schedulesListEl));
        if (typeof feather !== 'undefined') feather.replace();
    } catch (err) {
        console.error("Error loading schedules:", err);
        schedulesListEl.innerHTML = '<li>Error loading schedules.</li>';
    }
}

function renderSchedule(schedule, parentList) {
  let sourceText = 'unknown source';
  if (schedule.job_type === 'builder') {
    sourceText = `preset: <em>${schedule.preset_name || 'Unknown Preset'}</em>`;
  } else if (schedule.job_type === 'quick_playlist') {
    const key = schedule.quick_playlist_data?.quick_playlist_type;
    const friendly = quickPlaylistFriendlyNames[key] || 'Auto Playlist';
    sourceText = `Auto Playlist: <em>${friendly}</em>`;
  }

  const [hour, minute] = schedule.schedule_details.time.split(':');
  const hourNum = parseInt(hour, 10);
  const ampm = hourNum >= 12 ? 'PM' : 'AM';
  const friendlyHour = ((hourNum + 11) % 12) + 1;
  const friendlyTime = `${friendlyHour}:${minute} ${ampm}`;

  let frequencyText = 'daily';
  if (schedule.schedule_details.frequency === 'weekly') {
    const dayMap = ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat'];
    const days = schedule.schedule_details.days_of_week || [];
    const selectedDays = days.map(d => dayMap[d]).join(', ');
    frequencyText = `every ${selectedDays}`;
  }

  const listItem = document.createElement('li');
  listItem.innerHTML = `
    <fieldset class="filter-group" style="margin-bottom:1rem;">
      <legend>${schedule.playlist_name}</legend>
      <div class="schedule-item-content">
        <p class="schedule-details-text">
          <span style="
            font-weight:bold;
            font-style:normal;
            font-size:1.2em;
            color:var(--accent);
            margin-right:0.5rem;">→
          </span>
          Builds ${frequencyText} at ${friendlyTime} from ${sourceText}
        </p>
        <div class="schedule-status-container">
          ${
            schedule.last_run
              ? `
            <span
              class="last-run-status ${schedule.last_run.status === 'ok'
                ? 'status-success'
                : 'status-danger'}"
              title="${(schedule.last_run.log || []).join('\n')}">
              <i data-feather="${
                schedule.last_run.status === 'ok' ? 'check-circle' : 'alert-circle'
              }"></i>
            </span>
            <span>Last run: ${new Date(schedule.last_run.timestamp).toLocaleString()}</span>
          `
              : `<span style="font-style:italic;">Never run</span>`
          }
        </div>
        <div class="schedule-button-container">
          <button
            type="button"
            class="icon-btn run-now-btn"
            title="Run Schedule Now"
            data-id="${schedule.id}">
            <i data-feather="play"></i>
          </button>
          <button
            type="button"
            class="icon-btn danger delete-schedule-btn"
            title="Delete Schedule"
            data-id="${schedule.id}">
            <i data-feather="trash-2"></i>
          </button>
        </div>
      </div>
    </fieldset>
  `;
  parentList.appendChild(listItem);

  listItem
    .querySelector('.run-now-btn')
    .addEventListener('click', async event => {
      const res = await post(
        `api/schedules/${schedule.id}/run`,
        {},
        event.currentTarget,
        'POST'
      );
      if (res.status === 'ok') loadSchedulerData();
    });

  listItem
    .querySelector('.delete-schedule-btn')
    .addEventListener('click', async event => {
      try {
        await confirmModal.show({
          title: 'Delete Schedule?',
          text: `Are you sure you want to delete the schedule for "${schedule.playlist_name}"?`,
          confirmText: 'Delete',
        });
        const res = await post(
          `api/schedules/${schedule.id}`,
          {},
          event.currentTarget,
          'DELETE'
        );
        if (res.status === 'ok') loadSchedulerData();
      } catch {
        // Modal cancelled
      }
    });
}

async function handleCreateSchedule(event) {
    const sourceType = scheduleSourceSelect.value;
    const userId = userSelect.value;
    const frequency = frequencySelect.value;
    const selectedDays = [...daysCheckboxes].filter(cb => cb.checked).map(cb => parseInt(cb.value));
    const playlistName = schedulePlaylistNameInput.value.trim();
    const timeValue = scheduleTimeInput.value;
    if (!playlistName || !timeValue || !userId) { toast('Please provide a playlist name and select a time.', false); return; }
    if (frequency === 'weekly' && selectedDays.length === 0) { toast('Please select at least one day for a weekly schedule.', false); return; }
    const requestBody = { playlist_name: playlistName, user_id: userId, job_type: sourceType, schedule_details: { frequency, time: timeValue, days_of_week: frequency === 'weekly' ? selectedDays : null } };
    if (sourceType === 'builder') {
        const presetName = presetSelect.value;
        if (!presetName) { toast('Please select a Builder Preset to schedule.', false); return; }
        const presets = await getMixedPresets();
        const presetData = presets[presetName];
        if (!presetData) { toast('Could not find data for the selected preset.', false); return; }
        requestBody.preset_name = presetName;
        requestBody.blocks = presetData;
    } else if (sourceType === 'quick_playlist') {
        const quickType = quickTypeSelect.value;
        const count = parseInt(quickCountInput.value, 10);
        if (!quickType || !count || count < 1) { toast('Please select an Auto Playlist type and enter a valid number of items.', false); return; }
        requestBody.quick_playlist_data = { quick_playlist_type: quickType, options: { count: count } };
        requestBody.preset_name = quickPlaylistFriendlyNames[quickType] || 'Auto Playlist';
    }
    post('api/schedules', requestBody, event.currentTarget).then(res => { if (res.status === 'ok') { loadSchedulerData(); scheduleSourceSelect.value = 'builder'; toggleSourceOptions(); } });
}

export function initSchedulerPane() {
    const schedulerPane = document.getElementById('scheduler-pane');
    userSelect = document.getElementById('user-select');
    createBtn = schedulerPane.querySelector('#create-schedule-btn');
    schedulePlaylistNameInput = schedulerPane.querySelector('#schedule-playlist-name');
    scheduleSourceSelect = schedulerPane.querySelector('#schedule-source-select');
    frequencySelect = schedulerPane.querySelector('#schedule-frequency');
    scheduleTimeInput = schedulerPane.querySelector('#schedule-time-input');
    daysContainer = schedulerPane.querySelector('#schedule-days-container');
    daysCheckboxes = schedulerPane.querySelectorAll('input[name="schedule-day"]');
    builderOptionsContainer = schedulerPane.querySelector('#schedule-builder-options');
    quickOptionsContainer = schedulerPane.querySelector('#schedule-quick-options');
    presetSelect = schedulerPane.querySelector('#schedule-preset-select');
    quickTypeSelect = schedulerPane.querySelector('#schedule-quick-type-select');
    quickCountInput = schedulerPane.querySelector('#schedule-quick-count-input');

    populatePresetDropdown();
    populateQuickPlaylistDropdown();
    createBtn.addEventListener('click', handleCreateSchedule);
    scheduleSourceSelect.addEventListener('change', toggleSourceOptions);
    frequencySelect.addEventListener('change', toggleDaysOfWeek);
    quickTypeSelect.addEventListener('change', syncPlaylistName);
    presetSelect.addEventListener('change', syncPlaylistName);
    document.getElementById('save-preset-confirm-btn').addEventListener('click', () => setTimeout(populatePresetDropdown, 100));
    document.getElementById('delete-preset-btn').addEventListener('click', () => setTimeout(populatePresetDropdown, 100));
    document.getElementById('import-preset-confirm-btn').addEventListener('click', () => setTimeout(populatePresetDropdown, 100));
}