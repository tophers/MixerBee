// static/js/components.js

import { post, toast } from './utils.js';
import { presetModal, confirmModal, importPresetModal } from './modals.js';

export class PresetManager {
    constructor(storageKey, { loadSelect, updateBtn, saveAsBtn, deleteBtn, importBtn, exportBtn }) {
        this.ui = { loadSelect, updateBtn, saveAsBtn, deleteBtn, importBtn, exportBtn };
        this.presets = {};
    }

    toggleSaveButtons() {
        const isPresetSelected = !!this.ui.loadSelect.value;
        this.ui.updateBtn.classList.toggle('hidden', !isPresetSelected);
        this.ui.saveAsBtn.classList.toggle('hidden', isPresetSelected);
    }

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
            if (this.presets[currentVal]) {
                this.ui.loadSelect.value = currentVal;
            } else {
                 this.ui.exportBtn.disabled = true;
            }
            this.toggleSaveButtons();
        } catch (error) {
            console.error('Error populating presets:', error);
            toast('Could not load presets from server.', false);
        }
    }

    async update(getUIDataFn) {
        const presetName = this.ui.loadSelect.value;
        if (!presetName) return;

        const payload = {
            name: presetName,
            data: getUIDataFn()
        };
        const res = await post('api/presets', payload, this.ui.updateBtn, 'POST');
        if (res.status === 'ok') {
            this.presets[presetName] = payload.data;
            toast(`Preset "${presetName}" saved!`, true);
        }
    }

    async init(getUIDataFn, applyPresetFn, renderBuilder) {
        await this.populateDropdown();

        this.ui.updateBtn.addEventListener('click', () => {
            this.update(getUIDataFn);
        });

        this.ui.saveAsBtn.addEventListener('click', async () => {
            try {
                const presetName = await presetModal.show(Object.keys(this.presets));
                const payload = { name: presetName, data: getUIDataFn() };
                const res = await post('api/presets', payload, this.ui.saveAsBtn, 'POST');
                if (res.status === 'ok') {
                    await this.populateDropdown();
                    this.ui.loadSelect.value = presetName;
                    this.ui.exportBtn.disabled = false;
                    this.toggleSaveButtons();
                }
            } catch (err) {
                console.log('Save preset cancelled.');
            }
        });

        this.ui.importBtn.addEventListener('click', async () => {
            try {
                const { name, data } = await importPresetModal.show();
                const savePreset = async () => {
                    const payload = { name, data };
                    const res = await post('api/presets', payload, null, 'POST');
                    if (res.status === 'ok') {
                        await this.populateDropdown();
                        this.ui.loadSelect.value = name;
                        await applyPresetFn(data);
                        renderBuilder();
                        toast(`Preset "${name}" imported successfully!`, true);
                    }
                };

                if (this.presets[name]) {
                    try {
                        await confirmModal.show({
                            title: 'Overwrite Preset?',
                            text: `A preset named "${name}" already exists. Do you want to overwrite it?`,
                            confirmText: 'Overwrite',
                        });
                        await savePreset();
                    } catch (err) {
                        console.log('Overwrite cancelled.');
                    }
                } else {
                    await savePreset();
                }
            } catch (err) {
                console.log('Import preset cancelled.');
            }
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

        this.ui.deleteBtn.addEventListener('click', async () => {
            const presetName = this.ui.loadSelect.value;
            if (!presetName) {
                toast("Please select a preset to delete.", false);
                return;
            }
            try {
                await confirmModal.show({
                    title: 'Delete Preset?',
                    text: `Are you sure you want to delete the preset "${presetName}"? This cannot be undone.`,
                    confirmText: 'Delete',
                });
                const res = await post(`api/presets/${presetName}`, {}, this.ui.deleteBtn, 'DELETE');
                if (res.status === 'ok') {
                    await this.populateDropdown();
                    await applyPresetFn([]);
                    renderBuilder();
                }
            } catch (err) {
                console.log('Delete preset cancelled.');
            }
        });

        this.ui.loadSelect.addEventListener('change', async (event) => {
            const presetName = event.target.value;
            this.ui.exportBtn.disabled = !presetName;
            this.toggleSaveButtons();
            
            const dataToApply = presetName ? this.presets[presetName] : [];
            await applyPresetFn(dataToApply);
            renderBuilder();
        });
      }
}

export function createTvShowRow({ rowData, rowIndex }) {
    const template = document.getElementById('template-tv-show-row');
    const rowElement = template.content.cloneNode(true).firstElementChild;

    rowElement.dataset.rowIndex = rowIndex;

    const showSelect = rowElement.querySelector('.tv-block-show-select');
    const seasonInput = rowElement.querySelector('.tv-block-season');
    const episodeInput = rowElement.querySelector('.tv-block-episode');
    const previewDiv = rowElement.querySelector('.tv-block-preview');
    const unwatchedCb = rowElement.querySelector('.first-unwatched-cb');

    appState.seriesData.forEach(s => {
        const option = document.createElement('option');
        option.value = s.name;
        option.textContent = s.name;
        option.dataset.id = s.id;
        showSelect.appendChild(option);
    });

    if (rowData?.name) showSelect.value = rowData.name;
    seasonInput.value = rowData?.season ?? 1;
    episodeInput.value = rowData?.episode ?? 1;
    unwatchedCb.checked = rowData?.unwatched ?? false;

    previewDiv.textContent = '...';

    const isUnwatched = unwatchedCb.checked;
    seasonInput.disabled = isUnwatched;
    episodeInput.disabled = isUnwatched;
    rowElement.querySelector('.random-ep-btn').disabled = isUnwatched;

    return rowElement;
}