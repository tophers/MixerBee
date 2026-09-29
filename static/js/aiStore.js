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

    libraryIq: { total: 0, enriched: 0, percentage: 0 },
    enrichmentStatus: {
        status: 'idle',
        total_items: 0,
        processed_items: 0,
        succeeded_items: 0,
        failed_items: 0,
        remaining_items: 0,
        queue_depth: 0,
        last_message: '',
        elapsed_seconds: 0
    },
    enrichmentPollTimer: null,
    _pollInFlight: false,

    moodPool: [],
    activeMoods: [],
    samplePrompt: '',
    isLoadingMoods: false,

    _initialized: false,

    // Bumped whenever generative availability changes. Every request that can mutate
    // this store captures it and drops its own result if it no longer matches, so a
    // response that was already in flight when AI was turned off cannot repopulate the
    // panels or restart the poll chain.
    _capabilityToken: 0,

    get aiAvailable() {
        return !!Alpine.store('settings')?.generative_ai_available;
    },

    init() {
        if (this._initialized) return;
        this._initialized = true;

        // Both conditions matter: a media user must be active *and* generative AI must
        // be available. Nothing here runs for a disabled or unconfigured account.
        const start = () => {
            const sStore = Alpine.store('settings');
            if (!sStore?.activeUserId || !this.aiAvailable) return;
            this.loadIq();
            this.pollEnrichmentStatus();
            if (this.moodPool.length === 0 && !this.isLoadingMoods) this.fetchMoodDiscovery();
        };

        Alpine.watch(() => Alpine.store('settings').activeUserId, () => start());
        Alpine.watch(() => Alpine.store('settings').generative_ai_available, (available) => {
            this._capabilityToken += 1;
            if (available) start();
            else this.stopGenerativeActivity();
        });

        start();
    },

    // Called on disable. Stops polling and clears the generative panels without
    // touching drafts, blocks, or anything semantic: the index keeps working.
    stopGenerativeActivity() {
        this._capabilityToken += 1;

        // Close the generative panels and the AI Builder pane, leaving Builder blocks,
        // drafts and saved provider values untouched.
        Alpine.store('ui').showAiBuilder = false;
        const modals = Alpine.store('modals');
        ['aiHub', 'aiTweaks', 'ollamaModels'].forEach(name => {
            if (modals?.[name]) modals[name].isOpen = false;
        });

        if (this.enrichmentPollTimer) {
            clearTimeout(this.enrichmentPollTimer);
            this.enrichmentPollTimer = null;
        }
        this.isGenerating = false;
        this.isLoadingMoods = false;
        this.libraryIq = { total: 0, enriched: 0, percentage: 0 };
        this.moodPool = [];
        this.activeMoods = [];
        this.samplePrompt = '';
        Object.assign(this.enrichmentStatus, {
            status: 'idle', total_items: 0, processed_items: 0, succeeded_items: 0,
            failed_items: 0, remaining_items: 0, queue_depth: 0, last_message: '', elapsed_seconds: 0
        });
    },

    async generateWithAi() {
        // Guarded in the store as well as the template: a stale click on a control that
        // has not re-rendered yet must not reach the provider.
        if (!this.aiAvailable) return toast('AI features are turned off for this account.', false);
        if (!this.prompt.trim()) return toast('Prompt required.', false);
        const token = this._capabilityToken;
        this.isGenerating = true;
        const mixer = Alpine.store('mixer');
        const aiBlocks = mixer.blocks.filter(b => b.is_ai_generated);
        const isRefine = aiBlocks.length > 0;

        try {
            const payload = { prompt: this.prompt, tweaks: this.tweaks };
            if (isRefine) payload.existing_blocks = aiBlocks;

            const res = await useApi(api.post('api/create_from_text', payload));

            // A generation that finished after AI was turned off must not modify the
            // workspace. The request cannot be recalled; its result can be discarded.
            if (token !== this._capabilityToken) return;

            if (res.status === 'ok' && Array.isArray(res.data?.blocks)) {
                if (res.data.blocks.length === 0) {
                    const failMsg = res.data.log?.[0] || "No items matched your library.";
                    toast(`${failMsg} Try Relaxing Relevancy in AI Tweaks.`, false, {
                        actionText: "Tweaks",
                        actionCallback: () => aiTweaksModal.show()
                    });
                } else if (isRefine) {
                    const manualBefore = [];
                    const manualAfter = [];
                    let seenAi = false;
                    mixer.blocks.forEach(b => {
                        if (b.is_ai_generated) { seenAi = true; return; }
                        (seenAi ? manualAfter : manualBefore).push(b);
                    });
                    await mixer.loadBlocks([...manualBefore, ...res.data.blocks, ...manualAfter], false);
                    this.prompt = '';
                } else {
                    await mixer.loadBlocks(res.data.blocks, true);
                }
            }
        } catch (e) {
            console.error("[MixerBee] generateWithAi failed:", e);
        } finally {
            this.isGenerating = false;
        }
    },

    async quickSwitchModel(modelName) {
        if (!this.aiAvailable) return;
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
        // Prompt starters read enrichment tags and belong to the generator, so they are
        // never fetched for a disabled or unconfigured account.
        if (!this.aiAvailable || this.isLoadingMoods) return;
        const token = this._capabilityToken;
        this.isLoadingMoods = true;
        try {
            const res = await useApi(api.get('api/library/mood_discovery'), null, true, false);
            if (token !== this._capabilityToken) return;
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
    },

    async loadIq() {
        if (!this.aiAvailable) return;
        const token = this._capabilityToken;
        try {
            const res = await useApi(api.get('api/library/iq'), null, true, false);
            if (token !== this._capabilityToken) return;
            if (res.data) {
                this.libraryIq.total = res.data.total || 0;
                this.libraryIq.enriched = res.data.enriched || 0;
                this.libraryIq.percentage = res.data.total > 0 ? Math.round((res.data.enriched / res.data.total) * 100) : 0;
            }
        } catch (e) { console.error("Failed to load Library IQ", e); }
    },

    async pollEnrichmentStatus() {
        // init() starts a poll directly and the activeUserId watcher starts another, so
        // two chains can run at once. enrichmentPollTimer only prevents double-scheduling
        // a continuation, not two concurrent fetches; this drops the duplicate. The
        // surviving fetch still schedules the next tick, so the chain is never broken.
        if (!this.aiAvailable || this._pollInFlight) return;
        const token = this._capabilityToken;
        this._pollInFlight = true;
        try {
            const res = await useApi(api.get('api/library/enrichment/status'), null, true, false);
            // A late reply must not restart the chain after a disable.
            if (token !== this._capabilityToken) return;
            if (res.data) {
                Object.assign(this.enrichmentStatus, res.data);
                if (res.data.status === 'running' || res.data.status === 'stopping') {
                    if (!this.enrichmentPollTimer) {
                        this.enrichmentPollTimer = setTimeout(() => {
                            this.enrichmentPollTimer = null;
                            this.pollEnrichmentStatus();
                        }, 1500);
                    }
                } else {
                    if (this.enrichmentPollTimer) {
                        clearTimeout(this.enrichmentPollTimer);
                        this.enrichmentPollTimer = null;
                    }
                    this.loadIq();
                }
            }
        } catch (e) {
            console.error("Enrichment status poll failed", e);
        } finally {
            this._pollInFlight = false;
        }
    },

    async startEnrichment() {
        if (!this.aiAvailable) return toast('AI features are turned off for this account.', false);
        try {
            const res = await useApi(api.post('api/library/enrichment/start', { batch_size: 10 }));
            if (res.status === 'ok') {
                toast("AI enrichment started in background.");
                this.pollEnrichmentStatus();
            }
        } catch (e) {
            toast(e.message || "Failed to start enrichment", false);
        }
    },

    async stopEnrichment() {
        // Deliberately not gated: stopping must stay usable even after a disable so a
        // worker mid-flight can still be told to halt.
        try {
            const res = await useApi(api.post('api/library/enrichment/stop'));
            if (res.status === 'ok') {
                toast("Stopping AI enrichment...");
                this.pollEnrichmentStatus();
            }
        } catch (e) {
            toast("Failed to stop enrichment", false);
        }
    },

    // Index maintenance, not an AI feature: available whatever the account preference,
    // and deliberately not followed by loadIq/pollEnrichmentStatus so refreshing the
    // index never starts enrichment polling.
    async runSemanticRefresh(btnEl) {
        try {
            const res = await useApi(api.post('api/library/semantic_refresh'), btnEl);
            if (res.status === 'ok' || res.data?.status === 'ok') {
                const data = res.data || res;
                toast(`Index refreshed: ${data.added} added, ${data.refreshed} updated, ${data.removed} removed.`);
                if (this.aiAvailable) this.loadIq();
            }
        } catch (e) {
            toast("Semantic refresh failed", false);
        }
    },

    async saveAiSettings(btnEl) {
        const s = Alpine.store('settings');
        if (s.ai_disabled) return toast('AI features are turned off for this account.', false);
        // Refuse rather than hydrate: this writes the whole ai_settings row, so saving
        // before the stored values loaded would overwrite them with defaults. Hydrating
        // here instead would discard whatever the user just typed, so neither is safe.
        if (s && typeof s.hydrate === 'function' && !s.isHydrated) {
            toast('AI settings are still loading. Try again in a moment.', false);
            return;
        }
        try {
            const res = await useApi(api.post('api/settings/ai', {
                ai_provider: s.ai_provider || '',
                gemini_key: s.gemini_key ? s.gemini_key.trim() : '',
                // No fallback defaults: substituting localhost/llama3.1 for an empty
                // field would save a provider setup the user never actually entered.
                ollama_url: s.ollama_url ? s.ollama_url.trim() : '',
                ollama_model: s.ollama_model ? s.ollama_model.trim() : '',
                ollama_timeout: parseInt(s.ollama_timeout) || 120,
                starred_models: s.starred_models || []
            }), btnEl, false, true);

            if (res && res.status === 'ok') {
                // Consume the server's capability rather than re-deriving it from the
                // form: the backend is the only authority on whether this counts as a
                // configured provider.
                s.applyCapability(res.data);
                toast('AI settings saved.', true);
                this.loadIq();
                this.pollEnrichmentStatus();
            }
        } catch (e) {
            toast('Failed to save AI settings.', false);
        }
    }
};
