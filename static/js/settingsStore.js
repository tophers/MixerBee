// static/js/settingsStore.js

import { post, toast } from './utils.js';

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
            starred_models: this.starred_models
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