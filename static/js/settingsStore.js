// static/js/settingsStore.js

import { post, toast } from './utils.js';

export const settingsStore = {
    isOpen: false,
    server_type: 'emby',
    emby_url: '',
    emby_user: '',
    emby_pass: '',
    gemini_key: '',
    ai_provider: 'gemini',
    ollama_url: 'http://localhost:11434',
    ollama_model: 'llama3.1',
    is_ai_configured: false,
    version: '',

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
                this.version = data.version;
            }
        } catch (err) {
            console.error("Failed to hydrate settings:", err);
        }
        this.isOpen = true;
    },

    hide() {
        this.isOpen = false;
    },

    removeGeminiKey() {
        this.gemini_key = '';
        toast('Gemini API key has been cleared. Click Save to finalize.', true);
    },

    async testConnection(btnEl) {
        try {
            const res = await post('api/settings/test', {}, btnEl);
            toast(res.log.join(' '), res.status === 'ok');
        } catch (err) {
            toast('Failed to test connection.', false);
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
            ollama_model: this.ollama_model.trim()
        };

        if (!payload.emby_url || !payload.emby_user) {
            toast('URL and Username are required.', false);
            return;
        }

        try {
            const res = await post('api/settings', payload, btnEl);
            if (res.status === 'ok') {
                this.hide();
                sessionStorage.setItem('isReloading', 'true');
                toast("Settings saved! Server is restarting...", true);
                setTimeout(() => window.location.reload(), 500);
            }
        } catch (err) {
            // Error messaging is handled by the post utility
        }
    }
};