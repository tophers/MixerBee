// static/js/settingsStore.js
import { api } from './apiClient.js';
import { toast } from './utils.js';
import { confirmModal } from './modals.js';

export const settingsStore = {
    isOpen: false,
    theme: localStorage.getItem('mixerbeeTheme') || 'dark',
    activeUserId: '', activeUserName: '', version: '',
    server_type: 'emby', emby_url: '', emby_user: '', emby_pass: '',
    gemini_key: '', ai_provider: 'gemini', ollama_url: 'http://localhost:11434',
    ollama_model: 'llama3.1', ollama_timeout: 120, starred_models: [],
    external_api_key: '', is_external_key_visible: false, vector_space: 'cosine',
    
    ollama_installed: [], ollama_running: [], is_loading_ollama: false,

    async show() {
        try {
            const data = await api.get('api/settings', true, false);
            if (data) {
                Object.assign(this, {
                    server_type: data.server_type, emby_url: data.emby_url, emby_user: data.emby_user,
                    emby_pass: data.emby_pass, gemini_key: data.gemini_key, ai_provider: data.ai_provider,
                    ollama_url: data.ollama_url, ollama_model: data.ollama_model, ollama_timeout: data.ollama_timeout || 120,
                    starred_models: data.starred_models || [], version: data.version,
                    external_api_key: data.external_api_key || '', vector_space: data.vector_space || 'cosine'
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
            const data = await api.get('api/ollama/status', true, false);
            if (data) {
                this.ollama_installed = data.installed || [];
                this.ollama_running = (data.running || []).map(m => m.name);
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

    async resetVectorDb(preserveEnrichments = true) {
        const title = preserveEnrichments ? 'Wipe & Re-Index?' : 'FULL Semantic Wipe?';
        const text = preserveEnrichments
            ? 'This will clear all AI search data and rebuild it from your library. Your existing AI "Mood Tags" will be saved and restored.'
            : 'DANGER: This will permanently delete ALL AI semantic data AND all "Mood Tags" generated for your library.';

        try {
            await confirmModal.show({ title, text, confirmText: preserveEnrichments ? 'Re-Index' : 'Nuclear Wipe', isDanger: !preserveEnrichments });
            const res = await api.post('api/settings/reset_vector_db', { preserve_enrichments: preserveEnrichments });
            if (res.status === 'ok') { this.hide(); }
        } catch (e) { }
    },

    async testConnection(btnEl) {
        if (!this.emby_url || !this.emby_user) return toast('URL and Username are required.', false);
        await api.post('api/settings/test', {
            server_type: this.server_type, emby_url: this.emby_url.trim(), emby_user: this.emby_user.trim(),
            emby_pass: this.emby_pass, ai_provider: this.ai_provider, ollama_url: this.ollama_url.trim(),
            ollama_model: this.ollama_model.trim(), ollama_timeout: parseInt(this.ollama_timeout),
            gemini_key: this.gemini_key.trim(), starred_models: this.starred_models
        }, btnEl, false, true);
    },

    async saveSettings(btnEl) {
        if (!this.emby_url || !this.emby_user) return toast('URL and Username are required.', false);
        const res = await api.post('api/settings', {
            server_type: this.server_type, emby_url: this.emby_url.trim(), emby_user: this.emby_user.trim(),
            emby_pass: this.emby_pass, gemini_key: this.gemini_key.trim(), ai_provider: this.ai_provider,
            ollama_url: this.ollama_url.trim(), ollama_model: this.ollama_model.trim(), ollama_timeout: parseInt(this.ollama_timeout),
            starred_models: this.starred_models, external_api_key: this.external_api_key.trim()
        }, btnEl, false, true);

        if (res && res.status === 'ok') {
            this.hide();
            sessionStorage.setItem('isReloading', 'true');
            toast("Settings saved! Server is restarting...", true);
            setTimeout(() => window.location.reload(), 500);
        }
    }
};
