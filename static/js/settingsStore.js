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

    // AI capability, authoritative from the server. Both start false so nothing AI can
    // render or fire a request before /api/config_status has been read.
    ai_disabled: false, ai_provider_configured: false, generative_ai_available: false,
    ai_unavailable_reason: '', retained_ai_schedules: 0, isSavingAiPreference: false,

    // Writes onto the Alpine store proxy, so aiStore/assistStore pick the change up
    // through their Alpine.watch on generative_ai_available. Must be called as
    // Alpine.store('settings').applyCapability(...), never on the raw module object.
    applyCapability(data) {
        if (!data) return;
        if ('ai_disabled' in data) this.ai_disabled = !!data.ai_disabled;
        if ('ai_provider_configured' in data) this.ai_provider_configured = !!data.ai_provider_configured;
        if ('generative_ai_available' in data) this.generative_ai_available = !!data.generative_ai_available;
        if ('ai_unavailable_reason' in data) this.ai_unavailable_reason = data.ai_unavailable_reason || '';
        if ('retained_ai_schedules' in data) this.retained_ai_schedules = data.retained_ai_schedules || 0;
        // Legacy alias, kept in sync for any template still reading it.
        this.is_ai_configured = this.generative_ai_available;
        if (this.account) this.account.ai_disabled = this.ai_disabled;
    },

    async refreshCapability() {
        const res = await api.get('api/config_status');
        if (res?.data) this.applyCapability(res.data);
    },

    // The checkbox renders from ai_disabled via :checked and calls this on change, so
    // this is the only writer. A rejected save therefore leaves the stored value in
    // place and the box snaps back on its own, instead of the UI claiming a preference
    // the server never accepted. useApi surfaces the server's own log message.
    async setAiDisabled(disabled, btnEl) {
        if (this.isSavingAiPreference) return;
        this.isSavingAiPreference = true;
        try {
            const res = await useApi(api.post('api/account/preferences', { ai_disabled: !!disabled }), btnEl);
            if (res.status === 'ok' && res.data) this.applyCapability(res.data);
        } catch (e) {
            toast('Could not save the AI preference.', false);
        } finally {
            this.isSavingAiPreference = false;
        }
    },

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
        // Refresh so the checkbox and the retained-schedule count reflect the server,
        // not a value this tab may have been holding since page load.
        await this.refreshCapability();
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
        // A new connection selects no AI provider and stores no Ollama URL/model. The
        // form shows localhost/model examples as placeholders instead, so saving media
        // credentials can never look like a deliberate AI setup.
        Object.assign(this, { connection_id: null, label: '', server_type: 'emby', emby_url: '', emby_user: '', emby_pass: '',
            gemini_key: '', ai_provider: '', ollama_url: '', ollama_model: '',
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
    gemini_key: '', ai_provider: '', ollama_url: '',
    ollama_model: '', ollama_timeout: 120, starred_models: [],
    is_ai_configured: false,
    external_api_key: '', external_api_key_set: false, is_external_key_visible: false, vector_space: 'cosine',
    webhook_secret: '', webhook_status: 'disabled', is_webhook_secret_visible: false, server_ip: '',
    
    ollama_installed: [], ollama_running: [], is_loading_ollama: false,
    isHydrated: false,

    // Split out of show() so anything that edits saved settings can load the current
    // values first. The AI hub modal writes the same fields from a different entry
    // point, and saving unhydrated defaults over them erases the stored credentials.
    async hydrate() {
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
                this.applyCapability(res.data);
                // Only scan Ollama for a connection that deliberately selected it and is
                // allowed to use AI. Opening ordinary connection settings used to probe
                // localhost unconditionally.
                if (this.ai_provider === 'ollama' && !this.ai_disabled) this.fetchOllamaStatus();
                this.isHydrated = true;
                return true;
            }
        } catch (err) { console.error("Failed to hydrate settings"); }
        return false;
    },

    async show() {
        await this.hydrate();
        this.isOpen = true;
    },

    updateTheme(newTheme) {
        this.theme = newTheme;
        document.body.dataset.theme = newTheme;
        localStorage.setItem('mixerbeeTheme', newTheme);
    },

    async fetchOllamaStatus() {
        // Discovery is part of deliberate setup, so it is refused outright once the
        // account has opted out -- never a background probe of the user's machine.
        if (this.ai_disabled) return;
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

    // Index maintenance: never gated by the AI preference. Echo blocks and semantic
    // search read this index, so rebuilding it has to stay possible with AI turned off.
    async resetVectorDb(preserveEnrichments = true) {
        const title = preserveEnrichments ? 'Rebuild search index?' : 'Full index reset?';
        const text = preserveEnrichments
            ? 'This clears the local search index and rebuilds it from your library. Existing AI mood tags are saved and restored, and Echo blocks keep working once the rebuild finishes.'
            : 'DANGER: this permanently deletes the search index AND every AI mood tag generated for your library. The index rebuilds from your library metadata; the tags are not recoverable.';

        try {
            await confirmModal.show({ title, text, confirmText: preserveEnrichments ? 'Rebuild' : 'Delete everything', isDanger: !preserveEnrichments });
            const res = await useApi(api.post('api/settings/reset_vector_db', { preserve_enrichments: preserveEnrichments }));
            if (res.status === 'ok') { this.hide(); }
        } catch (e) { }
    },

    async testConnection(btnEl) {
        if (!this.emby_url || !this.emby_user) return toast('URL and Username are required.', false);
        // Media credentials only: testing a server must never require AI settings.
        await useApi(api.post('api/settings/test', {
            server_type: this.server_type, emby_url: this.emby_url.trim(), emby_user: this.emby_user.trim(),
            emby_pass: this.emby_pass
        }), btnEl, false, true);
    },

    async saveSettings(btnEl) {
        if (!this.emby_url || !this.emby_user) return toast('URL and Username are required.', false);
        const res = await useApi(api.post('api/settings', {
            connection_id: this.connection_id, label: this.label, clear_external_api_key: this.clear_external_api_key,
            server_type: this.server_type, emby_url: this.emby_url.trim(), emby_user: this.emby_user.trim(),
            emby_pass: this.emby_pass, external_api_key: this.external_api_key.trim()
            // No AI fields: this save must not be able to touch the stored provider
            // setup. Provider changes go through saveAiSettings in the AI Hub.
        }), btnEl, false, true);

        if (res && res.status === 'ok') {
            this.applyCapability(res.data);
            this.hide();
            toast('Connection saved.', true);
            setTimeout(() => window.location.reload(), 500);
        }
    }
};
