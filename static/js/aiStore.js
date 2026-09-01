// static/js/aiStore.js

import { api } from './apiClient.js';
import { toast, useApi } from './utils.js';
import { aiTweaksModal } from './modals.js';

export const aiStore = {
    prompt: '',
    isGenerating: false,
    
    tweaks: {
        threshold: 0.65,
        limit: 25,
        strictness: 'genre_verified',
        temperature: 0.2,
        target_size: 10,
        only_unwatched: false,
        system_prompt: ''
    },

    moodPool: [],
    activeMoods: [],
    samplePrompt: '',
    isLoadingMoods: false,

    init() {
        Alpine.watch(() => Alpine.store('settings').activeUserId, (uid) => {
            if (uid && this.moodPool.length === 0 && !this.isLoadingMoods) {
                this.fetchMoodDiscovery();
            }
        });

        const sStore = Alpine.store('settings');
        if (sStore && sStore.activeUserId) {
            this.fetchMoodDiscovery();
        }
    },

    async generateWithAi() {
        if (!this.prompt.trim()) return toast('Prompt required.', false);
        this.isGenerating = true;
        try {
            const res = await useApi(api.post('api/create_from_text', {
                prompt: this.prompt,
                tweaks: this.tweaks
            }));
            
            if (res.status === 'ok' && Array.isArray(res.data?.blocks)) {
                if (res.data.blocks.length === 0) {
                    const failMsg = res.data.log?.[0] || "No items matched your library.";
                    toast(`${failMsg} Try Relaxing Relevancy in AI Tweaks.`, false, {
                        actionText: "Tweaks",
                        actionCallback: () => aiTweaksModal.show()
                    });
                } else {
                    await Alpine.store('mixer').loadBlocks(res.data.blocks, true);
                }
            }
        } catch (e) {
            console.error("[MixerBee] generateWithAi failed:", e);
        } finally {
            this.isGenerating = false;
        }
    },

    async quickSwitchModel(modelName) {
        const sStore = Alpine.store('settings');
        if (sStore.ollama_model === modelName) return;

        try {
            const res = await useApi(api.post('api/settings/model', { ollama_model: modelName }));
            if (res.status === 'ok') {
                sStore.ollama_model = modelName;
                toast(`AI Model switched to ${modelName}`, true);
            }
        } catch (e) {
            toast('Failed to switch AI model.', false);
        }
    },

    clearPrompt() { this.prompt = ''; },

    async fetchMoodDiscovery() {
        if (this.isLoadingMoods) return;
        this.isLoadingMoods = true;
        try {
            const res = await useApi(api.get('api/library/mood_discovery'), null, true, false);
            if (res.data && res.data.tags && res.data.tags.length > 0) {
                this.moodPool = res.data.tags;
                this.refreshMoodSlots();
                this.refreshSamplePrompt();
            } else {
                console.warn("[MixerBee] Mood Discovery: API returned no tags.");
            }
        } catch (e) {
            console.error("[MixerBee] Mood Discovery Error:", e);
        } finally {
            this.isLoadingMoods = false;
        }
    },

    refreshMoodSlots() {
        if (this.moodPool.length === 0) return;
        const shuffled = [...this.moodPool].sort(() => 0.5 - Math.random());
        const count = Math.min(shuffled.length, 3);
        this.activeMoods = shuffled.slice(0, count);
    },

    refreshSamplePrompt() {
        if (this.moodPool.length === 0) return;
        const count = Math.min(this.moodPool.length, 2);
        const tags = [...this.moodPool].sort(() => 0.5 - Math.random()).slice(0, count);
        
        const structures = count > 1 ? [
            `A mix of ${tags[0]} and ${tags[1]} movies with some hints of ${tags[0]}`,
            `${tags[0].charAt(0).toUpperCase() + tags[0].slice(1)} cinema with a touch of ${tags[1]}`,
            `Highly ${tags[0]} shows, followed by something ${tags[1]}`,
            `A ${tags[0]} marathon`,
            `A block of ${tags[0]} and ${tags[1]} movies.`,
            `Explore ${tags[0]} vibes blended with ${tags[1]}`
        ] : [
            `A ${tags[0]} marathon`,
            `${tags[0].charAt(0).toUpperCase() + tags[0].slice(1)} vibes only`,
            `Pure ${tags[0]} cinema`
        ];
        
        this.samplePrompt = structures[Math.floor(Math.random() * structures.length)];
    }, 

    useSamplePrompt() {
        this.prompt = this.samplePrompt;
        this.refreshSamplePrompt();
    },

    appendMood(index) {
        const mood = this.activeMoods[index];
        if (!mood) return;

        const current = this.prompt.trim();
        if (!current) {
            this.prompt = mood.charAt(0).toUpperCase() + mood.slice(1);
        } else {
            const lastChar = current.slice(-1);
            const separator = (lastChar === ',' || lastChar === '.') ? ' ' : ', ';
            this.prompt = current + separator + mood;
        }

        const usedTags = new Set(this.activeMoods);
        const available = this.moodPool.filter(t => !usedTags.has(t));
        
        if (available.length > 0) {
            const newTag = available[Math.floor(Math.random() * available.length)];
            const updated = [...this.activeMoods];
            updated[index] = newTag;
            this.activeMoods = updated;
        }
    }
};
