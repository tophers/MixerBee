// static/js/settingsStore.js
import { api, setStoredAccessKey } from './apiClient.js';
import { toast, useApi } from './utils.js';
import { confirmModal } from './modals.js';

export const settingsStore = {
    isOpen: false,
    theme: localStorage.getItem('mixerbeeTheme') || 'dark',
    activeUserId: '', activeUserName: '', version: '',
    server_type: 'emby', emby_url: '', emby_user: '', emby_pass: '',
    gemini_key: '', ai_provider: 'gemini', ollama_url: 'http://localhost:11434',
    ollama_model: 'llama3.1', ollama_timeout: 120, starred_models: [],
    external_api_key: '', is_external_key_visible: false, vector_space: 'cosine',
    access_key: '', is_access_key_visible: false, is_access_key_set: false,
    access_key_warning_dismissed: localStorage.getItem('mixerbeeAccessKeyWarningDismissed') === 'true',
    webhook_secret: '', is_webhook_secret_visible: false,
    
    ollama_installed: [], ollama_running: [], is_loading_ollama: false,

    async show() {
        try {
            const res = await useApi(api.get('api/settings'), null, true, false);
            if (res.data) {
                Object.assign(this, {
                    server_type: res.data.server_type, emby_url: res.data.emby_url, emby_user: res.data.emby_user,
                    emby_pass: res.data.emby_pass, gemini_key: res.data.gemini_key, ai_provider: res.data.ai_provider,
                    ollama_url: res.data.ollama_url, ollama_model: res.data.ollama_model, ollama_timeout: res.data.ollama_timeout || 120,
                    starred_models: res.data.starred_models || [], version: res.data.version,
                    external_api_key: res.data.external_api_key || '', vector_space: res.data.vector_space || 'cosine',
                    access_key: res.data.access_key || '', is_access_key_set: !!res.data.access_key,
                    webhook_secret: res.data.webhook_secret || ''
                });
                if (this.ai_provider === 'ollama') this.fetchOllamaStatus();
            }
        } catch (err) { console.error("Failed to hydrate settings"); }
        this.isOpen = true;
    },

    updateTheme(newTheme) {
        this.theme = newTheme;
        document.body.dataset.theme = newTheme;
        localStorage.setItem('mixerbeeTheme', newTheme);
    },

    async fetchOllamaStatus() {
        this.is_loading_ollama = true;
        try {
            const res = await useApi(api.get('api/ollama/status'), null, true, false);
            if (res.data) {
                this.ollama_installed = res.data.installed || [];
                this.ollama_running = (res.data.running || []).map(m => m.name);
            }
        } catch (e) { } 
        finally { this.is_loading_ollama = false; }
    },

    toggleStar(modelName) {
        if (this.starred_models.includes(modelName)) this.starred_models = this.starred_models.filter(m => m !== modelName);
        else this.starred_models.push(modelName);
    },

    hide() { this.isOpen = false; },

    removeGeminiKey() {
        this.gemini_key = '';
        toast('Gemini API key has been cleared. Click Save to finalize.', true);
    },

    toggleExternalKeyVisibility() { this.is_external_key_visible = !this.is_external_key_visible; },

    toggleAccessKeyVisibility() { this.is_access_key_visible = !this.is_access_key_visible; },

    toggleWebhookSecretVisibility() { this.is_webhook_secret_visible = !this.is_webhook_secret_visible; },

    async copyToClipboard(value, label) {
        try {
            await navigator.clipboard.writeText(value || '');
            toast(`${label} copied to clipboard.`, true);
        } catch (e) { toast('Could not copy to clipboard.', false); }
    },

    async regenerateAccessKey(btnEl) {
        const res = await useApi(api.post('api/settings/access_key/regenerate', {}), btnEl);
        if (res?.data?.access_key) {
            this.access_key = res.data.access_key;
            this.is_access_key_visible = true;
            this.is_access_key_set = true;
            setStoredAccessKey(res.data.access_key);
        }
    },

    async saveAccessKey(btnEl) {
        const key = this.access_key.trim();
        if (key.length < 8) return toast('Access key must be at least 8 characters.', false);

        const res = await useApi(api.post('api/settings/access_key/regenerate', { key }), btnEl);
        if (res?.data?.access_key) {
            this.access_key = res.data.access_key;
            this.is_access_key_set = true;
            setStoredAccessKey(res.data.access_key);
        }
    },

    async clearAccessKey(btnEl) {
        const res = await useApi(api.post('api/settings/access_key/clear', {}), btnEl);
        if (res?.status === 'ok') {
            this.access_key = '';
            this.is_access_key_set = false;
            setStoredAccessKey('');
            localStorage.removeItem('mixerbeeAccessKeyWarningDismissed');
            this.access_key_warning_dismissed = false;
        }
    },

    dismissAccessKeyWarning() {
        this.access_key_warning_dismissed = true;
        localStorage.setItem('mixerbeeAccessKeyWarningDismissed', 'true');
    },

    async regenerateWebhookSecret(btnEl) {
        const res = await useApi(api.post('api/settings/webhook_secret/regenerate', {}), btnEl);
        if (res?.data?.webhook_secret) {
            this.webhook_secret = res.data.webhook_secret;
            this.is_webhook_secret_visible = true;
        }
    },

    async saveWebhookSecret(btnEl) {
        const key = this.webhook_secret.trim();
        if (key.length < 8) return toast('Webhook secret must be at least 8 characters.', false);

        const res = await useApi(api.post('api/settings/webhook_secret/regenerate', { key }), btnEl);
        if (res?.data?.webhook_secret) {
            this.webhook_secret = res.data.webhook_secret;
            this.is_webhook_secret_visible = true;
        }
    },

    async clearWebhookSecret(btnEl) {
        const res = await useApi(api.post('api/settings/webhook_secret/clear', {}), btnEl);
        if (res?.status === 'ok') this.webhook_secret = '';
    },

    async resetVectorDb(preserveEnrichments = true) {
        const title = preserveEnrichments ? 'Wipe & Re-Index?' : 'FULL Semantic Wipe?';
        const text = preserveEnrichments
            ? 'This will clear all AI search data and rebuild it from your library. Your existing AI "Mood Tags" will be saved and restored.'
            : 'DANGER: This will permanently delete ALL AI semantic data AND all "Mood Tags" generated for your library.';

        try {
            await confirmModal.show({ title, text, confirmText: preserveEnrichments ? 'Re-Index' : 'Nuclear Wipe', isDanger: !preserveEnrichments });
            const res = await useApi(api.post('api/settings/reset_vector_db', { preserve_enrichments: preserveEnrichments }));
            if (res.status === 'ok') { this.hide(); }
        } catch (e) { }
    },

    async testConnection(btnEl) {
        if (!this.emby_url || !this.emby_user) return toast('URL and Username are required.', false);
        await useApi(api.post('api/settings/test', {
            server_type: this.server_type, emby_url: this.emby_url.trim(), emby_user: this.emby_user.trim(),
            emby_pass: this.emby_pass, ai_provider: this.ai_provider, ollama_url: this.ollama_url.trim(),
            ollama_model: this.ollama_model.trim(), ollama_timeout: parseInt(this.ollama_timeout),
            gemini_key: this.gemini_key.trim(), starred_models: this.starred_models
        }), btnEl, false, true);
    },

    async saveSettings(btnEl) {
        if (!this.emby_url || !this.emby_user) return toast('URL and Username are required.', false);
        const res = await useApi(api.post('api/settings', {
            server_type: this.server_type, emby_url: this.emby_url.trim(), emby_user: this.emby_user.trim(),
            emby_pass: this.emby_pass, gemini_key: this.gemini_key.trim(), ai_provider: this.ai_provider,
            ollama_url: this.ollama_url.trim(), ollama_model: this.ollama_model.trim(), ollama_timeout: parseInt(this.ollama_timeout),
            starred_models: this.starred_models, external_api_key: this.external_api_key.trim()
        }), btnEl, false, true);

        if (res && res.status === 'ok') {
            this.hide();
            sessionStorage.setItem('isReloading', 'true');
            toast("Settings saved! Server is restarting...", true);
            setTimeout(() => window.location.reload(), 500);
        }
    }
};
