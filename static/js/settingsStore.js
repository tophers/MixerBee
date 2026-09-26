// static/js/settingsStore.js
import { api, getSession } from './apiClient.js';
import { toast, useApi } from './utils.js';
import { confirmModal } from './modals.js';

export const settingsStore = {
    isOpen: false, accountOpen: false, accountMenuOpen: false,
    account: {}, connections: [], selectedConnection: '', connection_id: null, label: '',
    accounts: [], newUsername: '', newPassword: '', currentPassword: '', nextPassword: '',
    webhookRequests: [], webhook_public_base_url: '',
    external_api_key_set: false, clear_external_api_key: false, can_manage_collections: false,
    is_configured: false, connection_unavailable: false, connection_error: '',

    async initAccount() {
        const session = getSession();
        this.account = session.account;
        this.selectedConnection = session.connection_id || '';
        const res = await api.get('api/connections');
        this.connections = res.data || [];
        if (this.account?.is_admin) await this.fetchWebhookRequests(true);
    },
    async selectConnection(id) {
        if (!id || id === this.selectedConnection) return;
        this.selectedConnection = id;
        const res = await useApi(api.post(`api/connections/${encodeURIComponent(id)}/select`, {}));
        if (res.status === 'ok') window.location.reload();
        await this.initAccount();
    },
    async logout() {
        sessionStorage.removeItem('mixerbeeWebhookRequestsSeen');
        const res = await api.post('api/auth/logout', {});
        if (res.status === 'ok') window.location.reload();
        else toast('Could not sign out. Please try again.', false);
    },
    async showAccount() {
        this.accountMenuOpen = false;
        this.accountOpen = true;
        this.currentPassword = ''; this.nextPassword = ''; this.newPassword = '';
        if (this.account.is_admin) {
            const [res] = await Promise.all([
                useApi(api.get('api/accounts')),
                this.fetchWebhookRequests(false)
            ]);
            this.accounts = res.data || [];
        }
    },
    async createAccount(button) {
        const res = await useApi(api.post('api/accounts', { username: this.newUsername, password: this.newPassword }), button);
        if (res.status === 'ok') {
            this.newUsername = ''; this.newPassword = '';
            toast('Account created. They can now sign in and add their media connection.', true);
            await this.showAccount();
        }
    },
    async changePassword(button) {
        const res = await useApi(api.post('api/auth/password', { current_password: this.currentPassword, new_password: this.nextPassword }), button);
        if (res.status === 'ok') window.location.reload();
    },
    async removeConnection(button) {
        if (!this.connection_id) return;
        const latest = await useApi(api.get('api/connections'), button);
        if (latest.status !== 'ok') return;
        this.connections = latest.data || [];
        const connection = this.connections.find(item => item.id === this.connection_id) || {};
        const name = connection.label || connection.username || 'this connection';
        const presets = connection.preset_count || 0;
        const schedules = connection.schedule_count || 0;
        try {
            await confirmModal.show({
                title: 'Remove connection?',
                text: `Remove "${name}" and delete ${presets} local preset(s), ${schedules} schedule(s), its AI index, and saved credentials? Playlists and collections on the media server will not be changed.`,
                confirmText: 'Remove connection',
                isDanger: true
            });
            const res = await useApi(api.del(`api/connections/${encodeURIComponent(this.connection_id)}?delete_data=true`), button);
            if (res.status === 'ok') window.location.reload();
        } catch (e) { }
    },
    newConnection() {
        Object.assign(this, { connection_id: null, label: '', server_type: 'emby', emby_url: '', emby_user: '', emby_pass: '',
            gemini_key: '', ai_provider: 'ollama', ollama_url: 'http://localhost:11434', ollama_model: 'qwen2.5:7b',
            ollama_timeout: 120, starred_models: [], external_api_key: '', external_api_key_set: false,
            clear_external_api_key: false, webhook_secret: '', ollama_installed: [], ollama_running: [],
            webhook_status: 'disabled', can_manage_collections: false, server_ip: '', isOpen: true });
    },
    retryConnection() { window.location.reload(); },
    getWebhookUrl() {
        if (!this.connection_id || !this.webhook_secret) return '';
        const base = this.webhook_public_base_url
            ? `${this.webhook_public_base_url.replace(/\/$/, '')}/`
            : window.location.href;
        const url = new URL(`api/webhook/${this.connection_id}`, base);
        if ((url.hostname === 'localhost' || url.hostname === '127.0.0.1' || !url.hostname) && this.server_ip) {
            url.hostname = this.server_ip;
        }
        url.searchParams.set('token', this.webhook_secret);
        return url.href;
    },
    get webhookUrl() {
        return this.getWebhookUrl();
    },
    set webhookUrl(_) {},
    get pendingWebhookCount() {
        return (this.webhookRequests || []).filter(item => item.status === 'setup_requested').length;
    },
    set pendingWebhookCount(_) {},
    webhookStatusLabel(status = this.webhook_status) {
        return ({ disabled: 'Disabled', needs_setup: 'Server setup required', setup_requested: 'Setup requested',
            waiting_for_event: 'Waiting for event', connected: 'Connected' })[status] || 'Unknown';
    },
    webhookStatusClass(status = this.webhook_status) {
        if (status === 'connected') return 'badge-success';
        if (status === 'disabled') return 'badge-subtle';
        return 'badge-accent';
    },
    theme: localStorage.getItem('mixerbeeTheme') || 'dark',
    activeUserId: '', activeUserName: '', version: '',
    server_type: 'emby', emby_url: '', emby_user: '', emby_pass: '',
    gemini_key: '', ai_provider: 'ollama', ollama_url: 'http://localhost:11434',
    ollama_model: 'llama3.1', ollama_timeout: 120, starred_models: [],
    external_api_key: '', external_api_key_set: false, is_external_key_visible: false, vector_space: 'cosine',
    webhook_secret: '', webhook_status: 'disabled', is_webhook_secret_visible: false, server_ip: '',
    
    ollama_installed: [], ollama_running: [], is_loading_ollama: false,

    async show() {
        try {
            const res = await useApi(api.get('api/settings'), null, true, false);
            if (res.data) {
                Object.assign(this, {
                    connection_id: res.data.connection_id, label: res.data.label, clear_external_api_key: false,
                    external_api_key_set: Boolean(res.data.external_api_key || res.data.external_api_key_set),
                    server_type: res.data.server_type, emby_url: res.data.emby_url, emby_user: res.data.emby_user,
                    emby_pass: res.data.emby_pass, gemini_key: res.data.gemini_key, ai_provider: res.data.ai_provider,
                    ollama_url: res.data.ollama_url, ollama_model: res.data.ollama_model, ollama_timeout: res.data.ollama_timeout || 120,
                    starred_models: res.data.starred_models || [], version: res.data.version,
                    external_api_key: res.data.external_api_key || '', vector_space: res.data.vector_space || 'cosine',
                    webhook_secret: res.data.webhook_secret || '', webhook_status: res.data.webhook_status || 'disabled',
                    webhook_public_base_url: res.data.webhook_public_base_url || this.webhook_public_base_url || '',
                    server_ip: res.data.server_ip || ''
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
            const res = await useApi(api.get(`api/ollama/status?url=${encodeURIComponent(this.ollama_url)}`), null, true, false);
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


    async regenerateExternalKey(btnEl) {
        const res = await useApi(api.post('api/settings/external_api_key/regenerate', { connection_id: this.connection_id }), btnEl);
        if (res?.data?.external_api_key) {
            this.external_api_key = res.data.external_api_key;
            this.external_api_key_set = true;
            this.is_external_key_visible = true;
        }
    },

    async saveExternalKey(btnEl) {
        const key = (this.external_api_key || '').trim();
        if (key.length < 16) return toast('External API key must be at least 16 characters.', false);

        const res = await useApi(api.post('api/settings/external_api_key/regenerate', { connection_id: this.connection_id, key }), btnEl);
        if (res?.data?.external_api_key) {
            this.external_api_key = res.data.external_api_key;
            this.external_api_key_set = true;
            this.is_external_key_visible = true;
            toast('External API key saved.', true);
        }
    },

    async clearExternalKey(btnEl) {
        const res = await useApi(api.post('api/settings/external_api_key/clear', { connection_id: this.connection_id }), btnEl);
        if (res?.status === 'ok') {
            this.external_api_key = '';
            this.external_api_key_set = false;
            toast('External API key disabled.', true);
        }
    },

    toggleWebhookSecretVisibility() { this.is_webhook_secret_visible = !this.is_webhook_secret_visible; },

    async copyToClipboard(value, label = 'Value') {
        const text = (value || '').trim();
        if (!text) {
            toast(`No ${label.toLowerCase()} available to copy.`, false);
            return;
        }
        let copied = false;
        if (navigator?.clipboard?.writeText) {
            try {
                await navigator.clipboard.writeText(text);
                copied = true;
            } catch (err) {
                console.warn('navigator.clipboard.writeText failed, using fallback:', err);
            }
        }
        if (!copied) {
            try {
                const textarea = document.createElement('textarea');
                textarea.value = text;
                textarea.setAttribute('readonly', '');
                textarea.style.position = 'fixed';
                textarea.style.top = '0';
                textarea.style.left = '-9999px';
                textarea.style.opacity = '0';
                document.body.appendChild(textarea);
                textarea.focus();
                textarea.select();
                textarea.setSelectionRange(0, text.length);
                copied = document.execCommand('copy');
                document.body.removeChild(textarea);
            } catch (fallbackErr) {
                console.error('Fallback clipboard copy failed:', fallbackErr);
            }
        }
        if (copied) {
            toast(`${label} copied to clipboard.`, true);
        } else {
            toast('Could not copy to clipboard.', false);
        }
    },

    async regenerateWebhookSecret(btnEl) {
        const res = await useApi(api.post('api/settings/webhook_secret/regenerate', { connection_id: this.connection_id }), btnEl);
        if (res?.data?.webhook_secret) {
            this.webhook_secret = res.data.webhook_secret;
            this.webhook_status = res.data.webhook_status || 'needs_setup';
            this.is_webhook_secret_visible = true;
        }
    },

    async saveWebhookSecret(btnEl) {
        const key = (this.webhook_secret || '').trim();
        if (key.length < 16) return toast('Webhook secret must be at least 16 characters.', false);

        const res = await useApi(api.post('api/settings/webhook_secret/regenerate', { connection_id: this.connection_id, key }), btnEl);
        if (res?.data?.webhook_secret) {
            this.webhook_secret = res.data.webhook_secret;
            this.webhook_status = res.data.webhook_status || 'needs_setup';
            this.is_webhook_secret_visible = true;
        }
    },

    async clearWebhookSecret(btnEl) {
        const res = await useApi(api.post('api/settings/webhook_secret/clear', { connection_id: this.connection_id }), btnEl);
        if (res?.status === 'ok') {
            this.webhook_secret = '';
            this.webhook_status = 'disabled';
        }
    },

    async requestWebhookSetup(btnEl) {
        const res = await useApi(api.post('api/settings/webhook/setup-request', { connection_id: this.connection_id }), btnEl);
        if (res?.status === 'ok') this.webhook_status = res.data.webhook_status || 'setup_requested';
    },

    async fetchWebhookRequests(notify = false) {
        if (!this.account?.is_admin) return;
        const res = await useApi(api.get('api/admin/webhook-requests'), null, true, false);
        if (res?.data) {
            this.webhookRequests = res.data.requests || [];
            if (!this.webhook_public_base_url) this.webhook_public_base_url = res.data.public_base_url || '';
            const pending = this.webhookRequests.filter(item => item.status === 'setup_requested');
            const signature = pending.map(item => `${item.connection_id}:${item.requested_at}`).join('|');
            if (notify && pending.length && sessionStorage.getItem('mixerbeeWebhookRequestsSeen') !== signature) {
                sessionStorage.setItem('mixerbeeWebhookRequestsSeen', signature);
                toast(`${pending.length} webhook setup request${pending.length === 1 ? '' : 's'} need your attention.`, false, {
                    actionText: 'Review', actionCallback: () => this.showAccount()
                });
            }
        }
    },

    async acknowledgeWebhookRequest(connectionId, btnEl) {
        const res = await useApi(api.post(`api/admin/webhook-requests/${encodeURIComponent(connectionId)}/acknowledge`, {}), btnEl);
        if (res?.status === 'ok') await this.fetchWebhookRequests(false);
    },

    async saveWebhookBaseUrl(btnEl) {
        const res = await useApi(api.post('api/admin/settings/webhook-base-url', { url: this.webhook_public_base_url }), btnEl);
        if (res?.status === 'ok') {
            this.webhook_public_base_url = res.data.webhook_public_base_url || '';
            await this.fetchWebhookRequests(false);
        }
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
            connection_id: this.connection_id, label: this.label, clear_external_api_key: this.clear_external_api_key,
            server_type: this.server_type, emby_url: this.emby_url.trim(), emby_user: this.emby_user.trim(),
            emby_pass: this.emby_pass, gemini_key: this.gemini_key.trim(), ai_provider: this.ai_provider,
            ollama_url: this.ollama_url.trim(), ollama_model: this.ollama_model.trim(), ollama_timeout: parseInt(this.ollama_timeout),
            starred_models: this.starred_models, external_api_key: this.external_api_key.trim()
        }), btnEl, false, true);

        if (res && res.status === 'ok') {
            this.hide();
            toast('Connection saved.', true);
            setTimeout(() => window.location.reload(), 500);
        }
    }
};
