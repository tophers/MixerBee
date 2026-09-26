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
        if (!name) {
            this.currentName = '';
            await Alpine.store('mixer').loadBlocks([]);
            return;
        }
        const data = this.registry[name];
        if (data) {
            this.currentName = name;
            await Alpine.store('mixer').loadBlocks(JSON.parse(JSON.stringify(data)));
        }
    },

    async saveAs() {
        const mixerBlocks = Alpine.store('mixer').blocks;
        if (mixerBlocks.length === 0) return toast("No blocks to save.", false);

        try {
            const name = await presetModal.show({ existingNames: this.availableNames, name: '' });
            if (!name || !name.trim()) return;

            const res = await useApi(api.post('api/presets', { name: name.trim(), data: mixerBlocks }));
            if (res.status === 'ok') {
                await this.refresh();
                this.currentName = name.trim();
            }
        } catch (err) { }
    },

    async updateCurrent() {
        if (!this.currentName) return;
        const mixerBlocks = Alpine.store('mixer').blocks;
        const res = await useApi(api.post('api/presets', { name: this.currentName, data: mixerBlocks }));
        if (res.status === 'ok') {
            this.registry[this.currentName] = JSON.parse(JSON.stringify(mixerBlocks));
        }
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
