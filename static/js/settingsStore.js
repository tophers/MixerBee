// static/js/settingsStore.js

import { post, toast } from './utils.js';

export const settingsStore = {
    isOpen: false,
    server_type: 'emby',
    emby_url: '',
    emby_user: '',
    emby_pass: '',
    gemini_key: '',
    is_ai_configured: false,
    version: '',

    show() {
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
            gemini_key: this.gemini_key.trim()
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
        }
    }
};