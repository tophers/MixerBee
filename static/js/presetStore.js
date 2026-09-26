// static/js/presetStore.js

import { api } from './apiClient.js';
import { toast, useApi } from './utils.js';
import { presetModal, confirmModal, importPresetModal } from './modals.js';

export const presetStore = {
    registry: {},
    records: [],
    availableNames: [],
    currentName: '',

    async init() {
        await this.refresh();
    },

    async refresh() {
        try {
            const res = await useApi(api.get('api/presets/catalog'), null, true, false);
            if (Array.isArray(res.data)) {
                this.records = res.data;
                this.registry = Object.fromEntries(res.data.map(record => [record.name, record.data]));
                this.availableNames.splice(0, this.availableNames.length, ...res.data.map(record => record.name));
            }
        } catch (error) {
            console.error('Error populating presets:', error);
            toast('Could not load presets from server.', false);
        }
    },

    nameForId(id) {
        return this.records.find(record => record.id === id)?.name || '';
    },

    idForName(name) {
        return this.records.find(record => record.name === name)?.id || '';
    },

    async load(name) {
        const mixer = Alpine.store('mixer');
        if (!name) {
            this.currentName = '';
            await mixer.loadBlocks([]);
            mixer.markSaved();
            return;
        }
        const record = this.records.find(r => r.name === name);
        const data = this.registry[name];
        if (data) {
            this.currentName = name;
            let blocks = data;
            let mixOptions = record?.mix_options || null;
            if (data && typeof data === 'object' && !Array.isArray(data) && data.blocks) {
                blocks = data.blocks;
                mixOptions = data.mix_options || mixOptions;
            }
            await mixer.loadBlocks(JSON.parse(JSON.stringify(blocks)), false, mixOptions);
            mixer.markSaved();
        }
    },

    async saveAs() {
        const mixer = Alpine.store('mixer');
        const mixerBlocks = mixer.blocks;
        if (mixerBlocks.length === 0) return toast("No blocks to save.", false);

        try {
            const name = await presetModal.show({ existingNames: this.availableNames, name: '' });
            if (!name || !name.trim()) return;

            const res = await useApi(api.post('api/presets', {
                name: name.trim(),
                data: mixerBlocks,
                mix_options: mixer.mix_options
            }));
            if (res.status === 'ok') {
                await this.refresh();
                this.currentName = name.trim();
                mixer.markSaved();
            }
        } catch (err) { }
    },

    async updateCurrent() {
        if (!this.currentName) return;
        const mixer = Alpine.store('mixer');
        const mixerBlocks = mixer.blocks;
        const res = await useApi(api.post('api/presets', {
            name: this.currentName,
            data: mixerBlocks,
            mix_options: mixer.mix_options
        }));
        if (res.status === 'ok') {
            this.registry[this.currentName] = JSON.parse(JSON.stringify(mixerBlocks));
            mixer.markSaved();
            toast('Preset saved.', true);
        }
    },

    async promptRename() {
        if (!this.currentName) return;
        const presetId = this.idForName(this.currentName);
        if (!presetId) return toast("Preset ID not found.", false);
        try {
            const newName = await Alpine.store('modals').renamePresetAction.show({ presetId, oldName: this.currentName, newName: this.currentName });
            if (!newName || !newName.trim() || newName.trim() === this.currentName) return;
            const res = await useApi(api.patch(`api/presets/${presetId}`, { name: newName.trim() }));
            if (res.status === 'ok') {
                await this.refresh();
                this.currentName = newName.trim();
                toast(`Preset renamed to "${newName.trim()}"`, true);
            }
        } catch (e) { }
    },

    async deleteCurrent() {
        if (!this.currentName) return;
        try {
            await confirmModal.show({ title: 'Delete Preset?', text: `Delete "${this.currentName}"?`, confirmText: 'Delete' });
            const presetId = this.idForName(this.currentName);
            if (!presetId) return toast('Preset could not be found. Refresh and try again.', false);
            const res = await useApi(api.del(`api/presets/id/${encodeURIComponent(presetId)}`));
            if (res.status === 'ok') {
                await this.refresh();
                this.currentName = '';
                await Alpine.store('mixer').loadBlocks([]);
            }
        } catch (err) { }
    },

    async import() {
        try {
            const { name, data } = await importPresetModal.show();
            if (this.registry[name]) {
                await confirmModal.show({ title: 'Overwrite?', text: `A preset named "${name}" already exists. Overwrite?`, confirmText: 'Overwrite' });
            }
            const res = await useApi(api.post('api/presets', { name, data }));
            if (res.status === 'ok') {
                await this.refresh();
                this.currentName = name;
                await Alpine.store('mixer').loadBlocks(data);
            }
        } catch (err) { }
    },

    exportCurrent() {
        if (!this.currentName) return;
        try {
            const payload = JSON.stringify({ name: this.currentName, data: this.registry[this.currentName] });
            const code = btoa(Array.from(new TextEncoder().encode(payload), byte => String.fromCharCode(byte)).join(""));
            navigator.clipboard.writeText(`MixerBee Preset: "${this.currentName}"\n---\n${code}`).then(
                () => toast('Share code copied to clipboard!', true),
                () => toast('Could not copy to clipboard.', false)
            );
        } catch (e) {
            console.error("Export failed:", e);
            toast("Failed to encode preset data.", false);
        }
    }
};
