// static/js/settingsStore.js

import { post, toast } from './utils.js';
import { confirmModal } from './modals.js';

export const settingsStore = {
    isOpen: false,
    activeUserId: '',
    activeUserName: '',
    server_type: 'emby',
    emby_url: '',
    emby_user: '',
    emby_pass: '',
    gemini_key: '',
    ai_provider: 'gemini',
    ollama_url: 'http://localhost:11434',
    ollama_model: 'llama3.1',
    ollama_timeout: 120,
    starred_models: [],
    version: '',
    external_api_key: '',
    is_external_key_visible: false,
    vector_space: 'cosine',

    // Local UI state
    ollama_installed: [],
    ollama_running: [],
    is_loading_ollama: false,

    async show() {
        try {
            const response = await fetch('api/settings');
            if (response.ok) {
                const data = await response.json();
                this.server_type = data.server_type;
                this.emby_url = data.emby_url;
                this.emby_user = data.emby_user;
                this.emby_pass = data.emby_pass;
                this.gemini_key = data.gemini_key;
                this.ai_provider = data.ai_provider;
                this.ollama_url = data.ollama_url;
                this.ollama_model = data.ollama_model;
                this.ollama_timeout = data.ollama_timeout || 120;
                this.starred_models = data.starred_models || [];
                this.version = data.version;
                this.external_api_key = data.external_api_key || '';
                this.vector_space = data.vector_space || 'cosine';

                if (this.ai_provider === 'ollama') {
                    this.fetchOllamaStatus();
                }
            }
        } catch (err) {
            console.error("Failed to hydrate settings:", err);
        }
        this.isOpen = true;
    },

    async fetchOllamaStatus() {
        this.is_loading_ollama = true;
        try {
            const res = await fetch('api/ollama/status');
            if (res.ok) {
                const data = await res.json();
                this.ollama_installed = data.installed || [];
                this.ollama_running = (data.running || []).map(m => m.name);
            }
        } catch (e) {
            console.warn("Ollama status fetch failed");
        } finally {
            this.is_loading_ollama = false;
        }
    },

    toggleStar(modelName) {
        if (this.starred_models.includes(modelName)) {
            this.starred_models = this.starred_models.filter(m => m !== modelName);
        } else {
            this.starred_models.push(modelName);
        }
    },

    hide() {
        this.isOpen = false;
    },

    removeGeminiKey() {
        this.gemini_key = '';
        toast('Gemini API key has been cleared. Click Save to finalize.', true);
    },

    toggleExternalKeyVisibility() {
        this.is_external_key_visible = !this.is_external_key_visible;
    },

    async resetVectorDb(preserveEnrichments = true) {
        const title = preserve_enrichments ? 'Wipe & Re-Index?' : 'FULL Semantic Wipe?';
        const text = preserveEnrichments 
            ? 'This will clear all AI search data and rebuild it from your library. Your existing AI "Mood Tags" will be saved and restored. Re-indexing large libraries takes time.'
            : 'DANGER: This will permanently delete ALL AI semantic data AND all "Mood Tags" generated for your library. You will have to run enrichment again.';

        try {
            await confirmModal.show({
                title,
                text,
                confirmText: preserveEnrichments ? 'Re-Index' : 'Nuclear Wipe',
                isDanger: !preserveEnrichments
            });

            const res = await post('api/settings/reset_vector_db', { preserve_enrichments: preserveEnrichments });
            if (res.status === 'ok') {
                this.hide();
                toast(res.log.join(' '), true);
            }
        } catch (e) {
            // Cancelled or error
        }
    },

    async testConnection(btnEl) {
        const payload = {
            server_type: this.server_type,
            emby_url: this.emby_url.trim(),
            emby_user: this.emby_user.trim(),
            emby_pass: this.emby_pass,
            ai_provider: this.ai_provider,
            ollama_url: this.ollama_url.trim(),
            ollama_model: this.ollama_model.trim(),
            ollama_timeout: parseInt(this.ollama_timeout),
            gemini_key: this.gemini_key.trim(),
            starred_models: this.starred_models
        };

        if (!payload.emby_url || !payload.emby_user) {
            toast('URL and Username are required to test connection.', false);
            return;
        }

        try {
            const res = await post('api/settings/test', payload, btnEl, 'POST', true);
            if (res.status === 'ok') {
                toast(res.log.join(' '), true);
            }
        } catch (err) {
            toast('Failed to reach server.', false);
        }
    },

    async saveSettings(btnEl) {
        const payload = {
            server_type: this.server_type,
            emby_url: this.emby_url.trim(),
            emby_user: this.emby_user.trim(),
            emby_pass: this.emby_pass,
            gemini_key: this.gemini_key.trim(),
            ai_provider: this.ai_provider,
            ollama_url: this.ollama_url.trim(),
            ollama_model: this.ollama_model.trim(),
            ollama_timeout: parseInt(this.ollama_timeout),
            starred_models: this.starred_models,
            external_api_key: this.external_api_key.trim()
        };

        if (!payload.emby_url || !payload.emby_user) {
            toast('URL and Username are required.', false);
            return;
        }

        try {
            const res = await post('api/settings', payload, btnEl, 'POST', true);
            if (res.status === 'ok') {
                this.hide();
                sessionStorage.setItem('isReloading', 'true');
                toast("Settings saved! Server is restarting...", true);
                setTimeout(() => window.location.reload(), 500);
            }
        } catch (err) {
            toast('Error saving settings.', false);
        }
    }
};
