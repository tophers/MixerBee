// static/js/presetStore.js

import { post, toast } from './utils.js';
import { presetModal, confirmModal, importPresetModal } from './modals.js';

export const presetStore = {
    registry: {},
    availableNames: [],
    currentName: '',

    async init() {
        await this.refresh();
    },

    async refresh() {
        try {
            const response = await fetch('api/presets');
            if (!response.ok) throw new Error('Failed to fetch presets');
            this.registry = await response.json();
            this.availableNames = Object.keys(this.registry);
        } catch (error) {
            console.error('Error populating presets:', error);
            toast('Could not load presets from server.', false);
        }
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
            const name = await presetModal.show({ 
                existingNames: this.availableNames,
                name: '' 
            });
            
            if (!name || !name.trim()) return;

            const res = await post('api/presets', { name: name.trim(), data: mixerBlocks });
            if (res.status === 'ok') {
                await this.refresh();
                this.currentName = name.trim();
                toast(`Preset "${name}" saved!`, true);
            }
        } catch (err) {
            // Cancelled
        }
    },

    async updateCurrent() {
        if (!this.currentName) return;
        const mixerBlocks = Alpine.store('mixer').blocks;
        
        const res = await post('api/presets', { name: this.currentName, data: mixerBlocks });
        if (res.status === 'ok') {
            this.registry[this.currentName] = JSON.parse(JSON.stringify(mixerBlocks));
            toast(`Preset "${this.currentName}" updated!`, true);
        }
    },

    async deleteCurrent() {
        if (!this.currentName) return;
        try {
            await confirmModal.show({ 
                title: 'Delete Preset?', 
                text: `Are you sure you want to delete "${this.currentName}"?`, 
                confirmText: 'Delete' 
            });

            const res = await post(`api/presets/${this.currentName}`, {}, null, 'DELETE');
            if (res.status === 'ok') {
                await this.refresh();
                const deletedName = this.currentName;
                this.currentName = '';
                await Alpine.store('mixer').loadBlocks([]);
                toast(`Preset "${deletedName}" deleted.`, true);
            }
        } catch (err) {
            // Cancelled
        }
    },

    async import() {
        try {
            const { name, data } = await importPresetModal.show();
            if (this.registry[name]) {
                await confirmModal.show({ 
                    title: 'Overwrite?', 
                    text: `A preset named "${name}" already exists. Overwrite?`, 
                    confirmText: 'Overwrite' 
                });
            }

            const res = await post('api/presets', { name, data });
            if (res.status === 'ok') {
                await this.refresh();
                this.currentName = name;
                await Alpine.store('mixer').loadBlocks(data);
                toast(`Imported "${name}" successfully!`, true);
            }
        } catch (err) {
            // Cancelled
        }
    },

    exportCurrent() {
        if (!this.currentName) return;
        try {
            const payload = JSON.stringify({ 
                name: this.currentName, 
                data: this.registry[this.currentName] 
            });
            const bytes = new TextEncoder().encode(payload);
            const binString = Array.from(bytes, (byte) => String.fromCharCode(byte)).join("");
            const code = btoa(binString);

            const shareText = `MixerBee Preset: "${this.currentName}"\n---\n${code}`;

            navigator.clipboard.writeText(shareText).then(
                () => toast('Share code copied to clipboard!', true),
                () => toast('Could not copy to clipboard.', false)
            );
        } catch (e) {
            console.error("Export failed:", e);
            toast("Failed to encode preset data.", false);
        }
    }
};