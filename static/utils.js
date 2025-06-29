// static/utils.js

export function toast(m, ok) {
  const t = Object.assign(document.createElement('div'), { className: 'toast ' + (ok ? 'ok' : 'fail'), textContent: m });
  document.body.appendChild(t);
  setTimeout(() => t.remove(), 2500);
}

export function debounce(func, wait) {
    let timeout;
    return function executedFunction(...args) {
        const later = () => {
            clearTimeout(timeout);
            func(...args);
        };
        clearTimeout(timeout);
        timeout = setTimeout(later, wait);
    };
};

export function post(endpoint, body, event = null, method = 'POST') {
  const loadingOverlay = document.getElementById('loading-overlay');
  let clickedButton = null;

  if (event) {
    clickedButton = event.currentTarget;
    clickedButton.disabled = true;
  }

  if (loadingOverlay) loadingOverlay.style.display = 'flex';

  return fetch(endpoint, {
    method: method,
    headers: { 'Content-Type': 'application/json' },
    body: (method.toUpperCase() !== 'DELETE') ? JSON.stringify(body) : undefined
  })
    .then(r => r.json())
    .then(res => {
        if (res.status === 'ok') {
            toast(res.log?.join(' • ') || 'Success!', true);
        } else {
            toast('Error: ' + (res.log?.join(' • ') || 'unknown'), false);
        }
        return res.status;
    })
    .catch(e => {
        toast('Error: ' + e, false);
        return 'error';
    })
    .finally(() => {
        if (loadingOverlay) loadingOverlay.style.display = 'none';
        if (clickedButton) clickedButton.disabled = false;
    });
}

// --- Save Preset Modal ---
class SavePresetModal {
    constructor() {
        this.overlay = document.getElementById('save-preset-modal-overlay');
        this.closeBtn = document.getElementById('save-preset-close-btn');
        this.cancelBtn = document.getElementById('save-preset-cancel-btn');
        this.confirmBtn = document.getElementById('save-preset-confirm-btn');
        this.nameInput = document.getElementById('preset-name-input');
        this.warning = document.getElementById('preset-overwrite-warning');
        
        this.onSaveCallback = null;
        this.existingPresets = [];
        
        this.closeBtn.addEventListener('click', () => this.hide());
        this.cancelBtn.addEventListener('click', () => this.hide());
        this.confirmBtn.addEventListener('click', () => this._handleSave());
        this.nameInput.addEventListener('input', () => this._checkOverwrite());
        this.overlay.addEventListener('keydown', (e) => {
            if (e.key === 'Enter') this._handleSave();
            if (e.key === 'Escape') this.hide();
        });
    }
    _handleSave() {
        const presetName = this.nameInput.value.trim();
        if (presetName) {
            if (this.onSaveCallback) this.onSaveCallback(presetName);
            this.hide();
        } else {
            alert('Please enter a name for the preset.');
        }
    }
    _checkOverwrite() {
        this.warning.style.display = this.existingPresets.includes(this.nameInput.value.trim()) ? 'block' : 'none';
    }
    show(onSave, existingPresets = []) {
        this.onSaveCallback = onSave;
        this.existingPresets = existingPresets;
        this.nameInput.value = '';
        this.warning.style.display = 'none';
        this.overlay.style.display = 'flex';
        this.nameInput.focus();
    }
    hide() {
        this.overlay.style.display = 'none';
    }
}
const presetModal = new SavePresetModal();

// --- Smart Playlist Modal ---
class SmartPlaylistModal {
    constructor() {
        this.overlay = document.getElementById('smart-playlist-modal-overlay');
        this.closeBtn = document.getElementById('smart-playlist-close-btn');
        this.cancelBtn = document.getElementById('smart-playlist-cancel-btn');
        this.confirmBtn = document.getElementById('smart-playlist-confirm-btn');
        this.titleEl = document.getElementById('smart-playlist-title');
        this.descriptionEl = document.getElementById('smart-playlist-description');
        this.nameInput = document.getElementById('smart-playlist-name-input');
        this.countInput = document.getElementById('smart-playlist-count-input');
        this.countLabel = document.getElementById('smart-playlist-count-label');
        this.onCreateCallback = null;
        this.closeBtn.addEventListener('click', () => this.hide());
        this.cancelBtn.addEventListener('click', () => this.hide());
        this.confirmBtn.addEventListener('click', () => this._handleCreate());
        this.overlay.addEventListener('keydown', (e) => {
            if (e.key === 'Enter') this._handleCreate();
            if (e.key === 'Escape') this.hide();
        });
    }
    _handleCreate() {
        const playlistName = this.nameInput.value.trim();
        const count = parseInt(this.countInput.value, 10);
        if (playlistName && count > 0) {
            if (this.onCreateCallback) this.onCreateCallback({ playlistName, count });
            this.hide();
        } else {
            alert('Please provide a valid playlist name and number of items.');
        }
    }
    show({ title, description, countLabel, defaultCount, defaultName, onCreate }) {
        this.onCreateCallback = onCreate;
        this.titleEl.textContent = title;
        this.descriptionEl.textContent = description;
        this.countLabel.textContent = countLabel;
        this.countInput.value = defaultCount;
        this.nameInput.value = defaultName;
        this.overlay.style.display = 'flex';
        this.nameInput.focus();
        this.nameInput.select();
    }
    hide() {
        this.overlay.style.display = 'none';
    }
}
export const smartPlaylistModal = new SmartPlaylistModal();

// --- Import Preset Modal ---
class ImportPresetModal {
    constructor() {
        this.overlay = document.getElementById('import-preset-modal-overlay');
        this.closeBtn = document.getElementById('import-preset-close-btn');
        this.cancelBtn = document.getElementById('import-preset-cancel-btn');
        this.confirmBtn = document.getElementById('import-preset-confirm-btn');
        this.codeInput = document.getElementById('import-code-input');
        this.nameInput = document.getElementById('import-name-input');
        this.onImportCallback = null;
        
        this.closeBtn.addEventListener('click', () => this.hide());
        this.cancelBtn.addEventListener('click', () => this.hide());
        this.confirmBtn.addEventListener('click', () => this._handleImport());
    }
    _handleImport() {
        const code = this.codeInput.value.trim();
        const name = this.nameInput.value.trim();
        if (!code || !name) {
            alert('Please provide both a share code and a new name for the preset.');
            return;
        }
        try {
            const decodedString = atob(code);
            const presetData = JSON.parse(decodedString);
            if (this.onImportCallback) {
                this.onImportCallback(name, presetData);
            }
            this.hide();
        } catch (e) {
            console.error("Failed to decode or parse preset:", e);
            alert('Invalid share code. Please check the code and try again.');
        }
    }
    show(onImport) {
        this.onImportCallback = onImport;
        this.codeInput.value = '';
        this.nameInput.value = '';
        this.overlay.style.display = 'flex';
        this.codeInput.focus();
    }
    hide() {
        this.overlay.style.display = 'none';
    }
}
const importPresetModal = new ImportPresetModal();


// --- PresetManager Class ---
export class PresetManager {
    constructor(storageKey, { loadSelect, saveBtn, deleteBtn, importBtn, exportBtn }) {
        this.storageKey = storageKey;
        this.ui = { loadSelect, saveBtn, deleteBtn, importBtn, exportBtn };
        this.presets = this.getPresets();
    }

    getPresets() {
        const presetsJSON = localStorage.getItem(this.storageKey);
        return presetsJSON ? JSON.parse(presetsJSON) : {};
    }

    savePresets() {
        localStorage.setItem(this.storageKey, JSON.stringify(this.presets));
    }

    populateDropdown() {
        const currentVal = this.ui.loadSelect.value;
        this.ui.loadSelect.innerHTML = '<option value="">-- Select a preset --</option>';
        for (const name in this.presets) {
            if (name === '__autosave__') continue;
            const option = document.createElement('option');
            option.value = name;
            option.textContent = name;
            this.ui.loadSelect.appendChild(option);
        }
        this.ui.loadSelect.value = currentVal;
    }

    init(getUIDataFn, applyPresetFn) {
        this.ui.saveBtn.addEventListener('click', () => {
            presetModal.show(
                (presetName) => {
                    if (presetName === '__autosave__') {
                        alert("That name is reserved.");
                        return;
                    }
                    this.presets[presetName] = getUIDataFn();
                    this.savePresets();
                    this.populateDropdown();
                    this.ui.loadSelect.value = presetName;
                    this.ui.exportBtn.disabled = false;
                    toast(`Preset "${presetName}" saved!`, true);
                },
                Object.keys(this.presets).filter(k => k !== '__autosave__')
            );
        });

        this.ui.importBtn.addEventListener('click', () => {
            importPresetModal.show((name, data) => {
                if (this.presets[name]) {
                    if (!confirm(`A preset named "${name}" already exists. Overwrite it?`)) {
                        return;
                    }
                }
                this.presets[name] = data;
                this.savePresets();
                this.populateDropdown();
                this.ui.loadSelect.value = name;
                this.ui.loadSelect.dispatchEvent(new Event('change'));
                toast(`Preset "${name}" imported successfully!`, true);
            });
        });

        this.ui.exportBtn.addEventListener('click', () => {
            const presetName = this.ui.loadSelect.value;
            if (!presetName) return;
            const presetData = this.presets[presetName];
            const jsonString = JSON.stringify(presetData);
            const base64String = btoa(jsonString);
            
            navigator.clipboard.writeText(base64String).then(() => {
                toast('Share code copied to clipboard!', true);
            }).catch(err => {
                console.error('Failed to copy text: ', err);
                toast('Could not copy to clipboard.', false);
            });
        });

        this.ui.deleteBtn.addEventListener('click', () => {
            const presetName = this.ui.loadSelect.value;
            if (!presetName) { alert("Please select a preset to delete."); return; }
            if (confirm(`Are you sure you want to delete the preset "${presetName}"?`)) {
                delete this.presets[presetName];
                this.savePresets();
                this.populateDropdown();
                this.ui.exportBtn.disabled = true;
            }
        });

        this.ui.loadSelect.addEventListener('change', (event) => {
            const presetName = event.target.value;
            this.ui.exportBtn.disabled = !presetName;
            if (!presetName) return;
            applyPresetFn(this.presets[presetName]);
        });

        this.populateDropdown();
    }
}
// Creates an interactive row for selecting a TV show.
export function createTvShowRow({ rowData, seriesData, userSelectElement, changeCallback }) {
    const icon = (txt, cls, title) => Object.assign(document.createElement('button'), { type: 'button', className: 'icon-btn ' + cls, textContent: txt, title: title });

    const r = Object.assign(document.createElement('div'), { className: 'show-row tv-block-show-row' });

    const handle = icon('↕', 'drag-handle icon-btn', 'Drag to reorder');

    const showSelectWrapper = document.createElement('div');
    showSelectWrapper.className = 'show-select-wrapper';

    const searchAndSelectGroup = document.createElement('div');
    searchAndSelectGroup.className = 'search-and-select';

    const searchInput = Object.assign(document.createElement('input'), {
        type: 'search',
        className: 'show-search-input',
        placeholder: 'Filter shows...'
    });

    const sel = document.createElement('select');
    sel.className = 'tv-block-show-select';
    seriesData.forEach(s => {
        const option = document.createElement('option');
        option.value = s.name;
        option.textContent = s.name;
        option.dataset.id = s.id;
        sel.appendChild(option);
    });

    searchAndSelectGroup.append(searchInput, sel);

    const shuffleBtn = icon('🔀', 'shuffle-show-btn', 'Pick Random Show');
    showSelectWrapper.append(searchAndSelectGroup, shuffleBtn);

    const sInput = Object.assign(document.createElement('input'), { type: 'number', className: 'tv-block-season', value: rowData?.season || rowData?.s || 1, min: 1 });
    const eInput = Object.assign(document.createElement('input'), { type: 'number', className: 'tv-block-episode', value: rowData?.episode || rowData?.e || 1, min: 1 });
    const prev = Object.assign(document.createElement('div'), { className: 'tv-block-preview' });

    if (rowData?.name) {
        sel.value = rowData.name;
    }

    const optionsDiv = document.createElement('div');
    optionsDiv.className = 'tv-block-show-options';
    const unwatchedLabel = document.createElement('label');
    const unwatchedCb = Object.assign(document.createElement('input'), { type: 'checkbox', className: 'first-unwatched-cb' });
    if (rowData?.unwatched) {
        unwatchedCb.checked = true;
    }
    unwatchedLabel.append(unwatchedCb, ' Start from next unwatched');
    optionsDiv.appendChild(unwatchedLabel);

    const randomBtn = icon('🎲', 'random-ep-btn', 'Pick Random Episode');
    const delBtn = icon('❌', 'delete-btn', 'Delete Row');

    const controlsDiv = document.createElement('div');
    controlsDiv.className = 'show-row-controls';
    [randomBtn, delBtn].forEach(btn => controlsDiv.appendChild(btn));

    const updatePreview = () => {
        const selectedOption = sel.options[sel.selectedIndex];
        if (!sel.value || !selectedOption) { prev.textContent = ''; return; }
        const showId = selectedOption.dataset.id;
        if (!showId) { prev.textContent = ''; return; }

        prev.textContent = '...';
        fetch(`api/episode_lookup?series_id=${showId}&season=${sInput.value}&episode=${eInput.value}`)
            .then(r => r.ok ? r.json() : Promise.reject('Episode not found'))
            .then(data => { prev.textContent = `→ ${data.name}`; })
            .catch(err => { console.warn(err); prev.textContent = 'Episode not found'; });
    };

    searchInput.addEventListener('input', (e) => {
        const searchTerm = e.target.value.toLowerCase();
        let firstVisible = null;
        Array.from(sel.options).forEach(opt => {
            const showName = opt.textContent.toLowerCase();
            const isVisible = showName.includes(searchTerm);
            opt.style.display = isVisible ? '' : 'none';
            if (isVisible && !firstVisible) firstVisible = opt;
        });
        sel.value = firstVisible ? firstVisible.value : '';
        sel.dispatchEvent(new Event('input'));
    });

    shuffleBtn.addEventListener('click', () => {
        const randomIndex = Math.floor(Math.random() * seriesData.length);
        sel.value = seriesData[randomIndex].name;
        unwatchedCb.checked = true;
        unwatchedCb.dispatchEvent(new Event('change'));
    });

    unwatchedCb.addEventListener('change', async (event) => {
        const isChecked = event.target.checked;
        sInput.disabled = isChecked;
        eInput.disabled = isChecked;
        randomBtn.disabled = isChecked;
        if (isChecked) {
            prev.textContent = 'Finding...';
            const selectedOption = sel.options[sel.selectedIndex];
            if (!selectedOption) { prev.textContent = 'No show selected.'; return; }
            const seriesId = selectedOption.dataset.id;
            const userId = userSelectElement.value;
            try {
                const res = await fetch(`api/shows/${seriesId}/first_unwatched?user_id=${userId}`);
                if (!res.ok) throw new Error('Failed to fetch');
                const data = await res.json();
                sInput.value = data.season;
                eInput.value = data.episode;
                updatePreview();
            } catch (err) {
                prev.textContent = 'Error finding episode';
                console.error(err);
            }
        }
        if (changeCallback) changeCallback();
    });

    randomBtn.addEventListener('click', async () => {
        if (unwatchedCb.checked) return;
        prev.textContent = 'Finding...';
        const selectedOption = sel.options[sel.selectedIndex];
        if (!selectedOption) { prev.textContent = 'No show selected.'; return; }
        const seriesId = selectedOption.dataset.id;
        const userId = userSelectElement.value;
        try {
            const res = await fetch(`api/shows/${seriesId}/random_unwatched?user_id=${userId}`);
            if (!res.ok) throw new Error('Failed to fetch');
            const data = await res.json();
            sInput.value = data.season;
            eInput.value = data.episode;
            updatePreview();
        } catch (err) {
            prev.textContent = 'Error finding episode';
            console.error(err);
        }
        if (changeCallback) changeCallback();
    });

    [sel, sInput, eInput].forEach(el => el.addEventListener('input', () => {
        if(unwatchedCb.checked) unwatchedCb.checked = false;
        sInput.disabled = false;
        eInput.disabled = false;
        randomBtn.disabled = false;
        updatePreview();
        if (changeCallback) changeCallback();
    }));

    delBtn.addEventListener('click', () => {
        r.dispatchEvent(new CustomEvent('delete-row', { bubbles: true }));
    });

    r.append(handle, showSelectWrapper, sInput, eInput, controlsDiv, optionsDiv, prev);

    if (unwatchedCb.checked) {
        unwatchedCb.dispatchEvent(new Event('change'));
    } else {
        updatePreview();
    }

    return r;
}

