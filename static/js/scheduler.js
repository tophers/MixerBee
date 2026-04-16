// static/js/scheduler.js

import { post, toast } from './utils.js';
import { confirmModal } from './modals.js';
import { SMART_BUILD_TYPES } from './definitions.js';
import { getSchedulerAutosave, setSchedulerAutosave } from './builderState.js';

let userSelect, createBtn, schedulesList, schedulePlaylistNameInput, scheduleSourceSelect,
    frequencySelect, scheduleTimeInput, daysContainer, daysCheckboxes,
    builderOptionsContainer, quickOptionsContainer, presetSelect, quickTypeSelect, quickCountInput,
    cancelEditBtn, schedulerPane, scheduleCreateAsCollectionCb;

let editingScheduleId = null;
let schedulesData = [];
let isHydrating = true; 

const schedulableQuickPlaylists = SMART_BUILD_TYPES.filter(t => t.schedulable);
const quickPlaylistFriendlyNames = schedulableQuickPlaylists.reduce((acc, curr) => {
    acc[curr.type] = curr.name;
    return acc;
}, {});

function populateQuickPlaylistDropdown() {
  if (!quickTypeSelect) return;
  quickTypeSelect.innerHTML = '';
  schedulableQuickPlaylists.forEach(playlist => {
    const option = document.createElement('option');
    option.value = playlist.type;
    option.textContent = playlist.name;
    quickTypeSelect.appendChild(option);
  });
}

function syncPlaylistName() {
  if (editingScheduleId || isHydrating) return;
  const sourceType = scheduleSourceSelect?.value;
  if (sourceType === 'builder') {
    const presetName = presetSelect?.options[presetSelect.selectedIndex]?.text;
    if (presetName && !presetName.startsWith('--') && schedulePlaylistNameInput) {
      schedulePlaylistNameInput.value = presetName;
    }
  } else if (sourceType === 'quick_playlist') {
    const selectedType = quickTypeSelect?.options[quickTypeSelect.selectedIndex]?.text;
    if (selectedType && schedulePlaylistNameInput) {
        schedulePlaylistNameInput.value = `Scheduled: ${selectedType}`;
    }
  }
}

async function getMixedPresets() {
  try {
    const response = await fetch('api/presets');
    return response.ok ? await response.json() : {};
  } catch (err) {
    console.error('Failed to fetch presets for scheduler.', err);
    return {};
  }
}

async function populatePresetDropdown() {
  if (!presetSelect) return;
  const presets = await getMixedPresets();
  const currentVal = presetSelect.value;
  presetSelect.innerHTML = '<option value="">-- Select a saved preset --</option>';
  for (const name in presets) {
    const option = document.createElement('option');
    option.value = name;
    option.textContent = name;
    presetSelect.appendChild(option);
  }
  if (presets[currentVal]) presetSelect.value = currentVal;
}

function resetCreateForm() {
    editingScheduleId = null;
    isHydrating = true; 
    
    const form = document.querySelector('#scheduler-pane .collapsible-section-body');
    if (form) {
        form.querySelectorAll('input[type="text"], input[type="number"], input[type="time"]').forEach(input => {
            if(input.id === 'schedule-quick-count-input') input.value = '10';
            else if(input.id === 'schedule-time-input') input.value = '19:00';
            else input.value = 'Scheduled';
        });
        form.querySelectorAll('select').forEach(select => select.selectedIndex = 0);
        if (daysCheckboxes) daysCheckboxes.forEach(cb => cb.checked = false);
        if (scheduleCreateAsCollectionCb) scheduleCreateAsCollectionCb.checked = false;
    }

    window.dispatchEvent(new CustomEvent('cancel-edit'));

    setSchedulerAutosave(null); 
    isHydrating = false;
}

function populateFormForEdit(schedule) {
    isHydrating = true;
    if (schedulePlaylistNameInput) schedulePlaylistNameInput.value = schedule.playlist_name;
    if (scheduleSourceSelect) scheduleSourceSelect.value = schedule.job_type;
    
    if (schedule.job_type === 'builder') {
        if (presetSelect) presetSelect.value = schedule.preset_name;
        if (scheduleCreateAsCollectionCb) scheduleCreateAsCollectionCb.checked = schedule.create_as_collection || false;
    } else if (schedule.job_type === 'quick_playlist') {
        if (quickTypeSelect) quickTypeSelect.value = schedule.quick_playlist_data.quick_playlist_type;
        if (quickCountInput) quickCountInput.value = schedule.quick_playlist_data.options.count;
    }
    const details = schedule.schedule_details;
    if (frequencySelect) frequencySelect.value = details.frequency;
    if (scheduleTimeInput) scheduleTimeInput.value = details.time;
    if (daysCheckboxes) daysCheckboxes.forEach(cb => cb.checked = (details.days_of_week || []).includes(parseInt(cb.value)));
    isHydrating = false;
}

function enterEditMode(scheduleId) {
    const scheduleToEdit = schedulesData.find(s => s.id === scheduleId);
    if (!scheduleToEdit) return toast('Could not find schedule data to edit.', false);
    
    editingScheduleId = scheduleId;
    populateFormForEdit(scheduleToEdit);

    window.dispatchEvent(new CustomEvent('edit-schedule', {
        detail: {
            source: scheduleToEdit.job_type,
            frequency: scheduleToEdit.schedule_details.frequency
        }
    }));

    const createSection = schedulerPane?.querySelector('.collapsible-section');
    if (createSection) { createSection.open = true; createSection.scrollIntoView({ behavior: 'smooth' }); }
}

export async function loadSchedulerData() {
    const schedulesListEl = document.getElementById('schedules-list');
    if (!schedulesListEl) return;
    try {
        const response = await fetch('api/schedules');
        schedulesData = response.ok ? await response.json() : [];
        const countSpan = document.getElementById('schedule-count');
        if (countSpan) countSpan.textContent = `(${schedulesData.length})`;
        const container = document.getElementById('schedules-list-container');
        if (container) container.classList.toggle('hidden', schedulesData.length === 0);
        schedulesListEl.innerHTML = schedulesData.length === 0 ? '<li style="text-align: center; padding: 2rem; color: var(--text-subtle);">No schedules configured.</li>' : '';
        schedulesData.forEach(schedule => renderSchedule(schedule, schedulesListEl));
        if (typeof feather !== 'undefined') feather.replace();
    } catch (err) {
        console.error("Error loading schedules:", err);
    }
}

function renderSchedule(schedule, parentList) {
  let sourceText = 'unknown source';
  if (schedule.job_type === 'builder') {
    const outputType = schedule.create_as_collection ? "Collection" : "Playlist";
    sourceText = `preset: <em>${schedule.preset_name || 'Unknown Preset'}</em> (${outputType})`;
  } else if (schedule.job_type === 'quick_playlist') {
    const key = schedule.quick_playlist_data?.quick_playlist_type;
    const friendly = quickPlaylistFriendlyNames[key] || 'Auto Playlist';
    sourceText = `Auto Playlist: <em>${friendly}</em>`;
  }
  const [hour, minute] = schedule.schedule_details.time.split(':');
  const friendlyTime = `${((parseInt(hour, 10) + 11) % 12) + 1}:${minute} ${parseInt(hour, 10) >= 12 ? 'PM' : 'AM'}`;
  let frequencyText = schedule.schedule_details.frequency === 'weekly' 
    ? `every ${ (schedule.schedule_details.days_of_week || []).map(d => ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat'][d]).join(', ') }` 
    : 'daily';

  const listItem = document.createElement('li');
  listItem.innerHTML = `
    <fieldset class="filter-group" style="margin-bottom:1rem;">
        <legend>${schedule.playlist_name}</legend>
        <div class="schedule-item-content">
            <p class="schedule-details-text">
                <span style="font-weight:bold;color:var(--accent);margin-right:0.5rem;">→</span>
                Builds ${frequencyText} at ${friendlyTime} from ${sourceText}
            </p>
            <div class="schedule-status-container">
                ${schedule.last_run ? `<span class="last-run-status ${schedule.last_run.status === 'ok' ? 'status-success' : 'status-danger'}" title="${(schedule.last_run.log || []).join('\n')}"><i data-feather="${schedule.last_run.status === 'ok' ? 'check-circle' : 'alert-circle'}"></i></span><span>Last run: ${new Date(schedule.last_run.timestamp).toLocaleString()}</span>` : `<span style="font-style:italic;">Never run</span>`}
            </div>
            
            <div class="schedule-button-container dropdown-container" x-data="{ open: false }">
                <button type="button" class="icon-btn" @click="open = !open" @click.outside="open = false">
                    <i data-feather="more-vertical"></i>
                </button>
                <div class="dropdown-menu" x-show="open" style="display: none; right: 0; left: auto; top: 100%; z-index: 10; min-width: 150px;">
                    <a href="#" class="dropdown-item run-now-btn" @click.prevent="open = false"><i data-feather="play"></i> Run Now</a>
                    <a href="#" class="dropdown-item edit-schedule-btn" @click.prevent="open = false"><i data-feather="edit-2"></i> Edit</a>
                    <a href="#" class="dropdown-item danger delete-schedule-btn" @click.prevent="open = false" style="color: var(--danger);"><i data-feather="trash-2"></i> Delete</a>
                </div>
            </div>
        </div>
    </fieldset>`;

  parentList.appendChild(listItem);

  // Link the actions
  listItem.querySelector('.edit-schedule-btn').addEventListener('click', () => enterEditMode(schedule.id));
  listItem.querySelector('.run-now-btn').addEventListener('click', async e => { await post(`api/schedules/${schedule.id}/run`, {}, e.currentTarget, 'POST'); loadSchedulerData(); });
  listItem.querySelector('.delete-schedule-btn').addEventListener('click', async e => {
      try { 
          await confirmModal.show({ title: 'Delete Schedule?', text: `Are you sure?`, confirmText: 'Delete' }); 
          const res = await post(`api/schedules/${schedule.id}`, {}, e.currentTarget, 'DELETE'); 
          if (res.status === 'ok') loadSchedulerData(); 
      } catch {}
  });
}

async function handleScheduleFormSubmit(event) {
    const selectedDays = daysCheckboxes ? Array.from(daysCheckboxes).filter(cb => cb.checked).map(cb => parseInt(cb.value)) : [];
    const requestBody = { 
        playlist_name: schedulePlaylistNameInput.value.trim(), 
        user_id: userSelect.value, 
        job_type: scheduleSourceSelect.value, 
        schedule_details: { frequency: frequencySelect.value, time: scheduleTimeInput.value, days_of_week: frequencySelect.value === 'weekly' ? selectedDays : null } 
    };
    if (scheduleSourceSelect.value === 'builder') {
        const presets = await getMixedPresets();
        requestBody.preset_name = presetSelect.value;
        requestBody.blocks = presets[presetSelect.value];
        requestBody.create_as_collection = scheduleCreateAsCollectionCb?.checked || false;
    } else {
        requestBody.quick_playlist_data = { quick_playlist_type: quickTypeSelect.value, options: { count: parseInt(quickCountInput.value, 10) } };
        requestBody.preset_name = quickPlaylistFriendlyNames[quickTypeSelect.value] || 'Auto Playlist';
    }
    const method = editingScheduleId ? 'PUT' : 'POST';
    const endpoint = editingScheduleId ? `api/schedules/${editingScheduleId}` : 'api/schedules';
    post(endpoint, requestBody, event.currentTarget, method).then(res => { if (res.status === 'ok') { loadSchedulerData(); resetCreateForm(); } });
}

function getSchedulerFormState() {
    return {
        playlistName: schedulePlaylistNameInput?.value || '',
        source: scheduleSourceSelect?.value || '',
        presetName: presetSelect?.value || '',
        createAsCollection: scheduleCreateAsCollectionCb ? scheduleCreateAsCollectionCb.checked : false,
        quickType: quickTypeSelect?.value || '',
        quickCount: quickCountInput?.value || '',
        frequency: frequencySelect?.value || '',
        time: scheduleTimeInput?.value || '',
        days: daysCheckboxes ? Array.from(daysCheckboxes).filter(cb => cb.checked).map(cb => cb.value) : []
    };
}

function applySchedulerFormState(state) {
    if (!state) return;
    isHydrating = true;
    try {
        if (state.source) scheduleSourceSelect.value = state.source;
        if (state.presetName) presetSelect.value = state.presetName;
        if (state.createAsCollection !== undefined && scheduleCreateAsCollectionCb) scheduleCreateAsCollectionCb.checked = state.createAsCollection;
        if (state.quickType) quickTypeSelect.value = state.quickType;
        if (state.quickCount) quickCountInput.value = state.quickCount;
        if (state.frequency) frequencySelect.value = state.frequency;
        if (state.time) scheduleTimeInput.value = state.time;
        if (state.days && daysCheckboxes) daysCheckboxes.forEach(cb => cb.checked = state.days.includes(cb.value));
        
        window.dispatchEvent(new CustomEvent('edit-schedule', {
            detail: { source: state.source, frequency: state.frequency }
        }));

        if (state.playlistName) schedulePlaylistNameInput.value = state.playlistName;
    } catch (e) { console.error("Restore failed:", e); }
}

export function initSchedulerPane() {
    schedulerPane = document.getElementById('scheduler-pane');
    if (!schedulerPane) return;
    isHydrating = true; 

    userSelect = document.getElementById('user-select');
    createBtn = schedulerPane.querySelector('#create-schedule-btn');
    cancelEditBtn = schedulerPane.querySelector('#cancel-edit-schedule-btn');
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
    scheduleCreateAsCollectionCb = schedulerPane.querySelector('#schedule-create-as-collection-cb');

    populateQuickPlaylistDropdown();
    
    populatePresetDropdown().then(() => {
        const saved = getSchedulerAutosave();
        if (saved) applySchedulerFormState(saved);
        
        isHydrating = false;

        const body = schedulerPane.querySelector('.collapsible-section-body');
        const triggerSave = () => { if (!editingScheduleId && !isHydrating) setSchedulerAutosave(getSchedulerFormState()); };
        body?.addEventListener('input', triggerSave);
        body?.addEventListener('change', triggerSave);
    });

    createBtn?.addEventListener('click', handleScheduleFormSubmit);
    cancelEditBtn?.addEventListener('click', resetCreateForm);
    
    scheduleSourceSelect?.addEventListener('change', syncPlaylistName);
    quickTypeSelect?.addEventListener('change', syncPlaylistName);
    presetSelect?.addEventListener('change', syncPlaylistName);

    ['save-preset-confirm-btn', 'delete-preset-btn', 'import-preset-confirm-btn'].forEach(id => {
        document.getElementById(id)?.addEventListener('click', () => {
            setTimeout(populatePresetDropdown, 250);
        });
    });
}