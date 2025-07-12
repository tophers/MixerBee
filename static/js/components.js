// static/js/components.js
import { post, toast } from './utils.js';
import { presetModal, confirmModal, importPresetModal } from './modals.js';

export class PresetManager {
    constructor(storageKey, { loadSelect, updateBtn, saveAsBtn, deleteBtn, importBtn, exportBtn }) {
        // storageKey is no longer used but kept for compatibility with existing calls
        this.ui = { loadSelect, updateBtn, saveAsBtn, deleteBtn, importBtn, exportBtn };
        this.presets = {}; // Will be populated from the server
    }

    // START: New method to control which save button is visible
    toggleSaveButtons() {
        const isPresetSelected = !!this.ui.loadSelect.value;
        this.ui.updateBtn.style.display = isPresetSelected ? 'inline-flex' : 'none';
        this.ui.saveAsBtn.style.display = isPresetSelected ? 'none' : 'inline-flex';
    }
    // END: New method

    async populateDropdown() {
        try {
            const response = await fetch('api/presets');
            if (!response.ok) throw new Error('Failed to fetch presets');
            this.presets = await response.json();

            const currentVal = this.ui.loadSelect.value;
            this.ui.loadSelect.innerHTML = '<option value="">-- Select a preset --</option>';
            for (const name in this.presets) {
                const option = document.createElement('option');
                option.value = name;
                option.textContent = name;
                this.ui.loadSelect.appendChild(option);
            }
            // Restore selection if possible
            if (this.presets[currentVal]) {
                this.ui.loadSelect.value = currentVal;
            } else {
                 this.ui.exportBtn.disabled = true;
            }
            this.toggleSaveButtons(); // Update buttons after populating
        } catch (error) {
            console.error('Error populating presets:', error);
            toast('Could not load presets from server.', false);
        }
    }

    // START: New method to handle updating an existing preset
    async update(getUIDataFn) {
        const presetName = this.ui.loadSelect.value;
        if (!presetName) return; // Should not happen if button is visible, but good practice

        const payload = {
            name: presetName,
            data: getUIDataFn()
        };
        const res = await post('api/presets', payload, this.ui.updateBtn, 'POST');
        if (res.status === 'ok') {
            // No need to re-populate dropdown, just update local cache
            this.presets[presetName] = payload.data;
            toast(`Preset "${presetName}" saved!`, true);
        }
    }
    // END: New method

    async init(getUIDataFn, applyPresetFn) {
        await this.populateDropdown();

        // Listener for the new "Save" (update) button
        this.ui.updateBtn.addEventListener('click', () => {
            this.update(getUIDataFn);
        });

        // Updated listener for the "Save as..." button
        this.ui.saveAsBtn.addEventListener('click', () => {
            presetModal.show(
                async (presetName) => {
                    const payload = {
                        name: presetName,
                        data: getUIDataFn()
                    };
                    const res = await post('api/presets', payload, this.ui.saveAsBtn, 'POST');
                    if (res.status === 'ok') {
                        await this.populateDropdown();
                        this.ui.loadSelect.value = presetName;
                        this.ui.exportBtn.disabled = false;
                        this.toggleSaveButtons();
                    }
                },
                Object.keys(this.presets)
            );
        });

        this.ui.importBtn.addEventListener('click', () => {
            importPresetModal.show(async (name, data) => {
                const savePreset = async () => {
                    const payload = { name, data };
                    const res = await post('api/presets', payload, null, 'POST');
                    if (res.status === 'ok') {
                        await this.populateDropdown();
                        this.ui.loadSelect.value = name;
                        applyPresetFn(data);
                        toast(`Preset "${name}" imported successfully!`, true);
                    }
                };

                if (this.presets[name]) {
                    confirmModal.show({
                        title: 'Overwrite Preset?',
                        text: `A preset named "${name}" already exists. Do you want to overwrite it?`,
                        confirmText: 'Overwrite',
                        onConfirm: savePreset
                    });
                } else {
                    await savePreset();
                }
            });
        });

        this.ui.exportBtn.addEventListener('click', () => {
            const presetName = this.ui.loadSelect.value;
            if (!presetName) return;

            const presetData = this.presets[presetName];
            const sharePayload = { name: presetName, data: presetData };
            const jsonString = JSON.stringify(sharePayload);
            const base64String = btoa(jsonString);
            const shareText = `MixerBee Preset: "${presetName}"\n--------------------------------------\n${base64String}`;

            navigator.clipboard.writeText(shareText).then(
                () => toast('Share code copied to clipboard!', true),
                () => toast('Could not copy to clipboard.', false)
            );
        });

        this.ui.deleteBtn.addEventListener('click', () => {
            const presetName = this.ui.loadSelect.value;
            if (!presetName) {
                alert("Please select a preset to delete.");
                return;
            }

            confirmModal.show({
                title: 'Delete Preset?',
                text: `Are you sure you want to delete the preset "${presetName}"? This cannot be undone.`,
                confirmText: 'Delete',
                onConfirm: async () => {
                    const res = await post(`api/presets/${presetName}`, {}, this.ui.deleteBtn, 'DELETE');
                    if (res.status === 'ok') {
                        await this.populateDropdown();
                        // This will implicitly deselect and disable the export/save buttons
                    }
                }
            });
        });

        this.ui.loadSelect.addEventListener('change', (event) => {
            const presetName = event.target.value;
            this.ui.exportBtn.disabled = !presetName;
            this.toggleSaveButtons(); // Control visibility of save buttons
            if (!presetName) {
                applyPresetFn([]); // Clear blocks if no preset is selected
                return;
            };
            applyPresetFn(this.presets[presetName]);
        });
    }
}

export function createTvShowRow({ rowData, seriesData, userSelectElement, changeCallback }) {

    const icon = (featherName, cls, title) => {
    const btn = Object.assign(document.createElement('button'), { type: 'button', className: 'icon-btn ' + cls, title: title });
    btn.innerHTML = `<i data-feather="${featherName}"></i>`;
    return btn;
};
    const r = Object.assign(document.createElement('div'), { className: 'show-row tv-block-show-row' });

    const handle = icon('move', 'drag-handle icon-btn', 'Drag to reorder');

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
    const shuffleBtn = icon('shuffle', 'shuffle-show-btn', 'Pick Random Show');
    showSelectWrapper.append(searchAndSelectGroup, shuffleBtn);

    const sInput = Object.assign(document.createElement('input'), { type: 'number', className: 'tv-block-season', value: rowData?.season ?? 1, min: 1 });
    const eInput = Object.assign(document.createElement('input'), { type: 'number', className: 'tv-block-episode', value: rowData?.episode ?? 1, min: 1 });
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

    const randomBtn = icon('shuffle', 'random-ep-btn', 'Pick Random Episode');
    const delBtn = icon('x', 'delete-btn danger', 'Delete Row');

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
                sInput.value = data.ParentIndexNumber ?? 1;
                eInput.value = data.IndexNumber ?? 1;
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