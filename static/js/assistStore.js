// static/js/assistStore.js
//
// Playlist Assist: a chat loop over a flat canvas of movies. The canvas stays
// editable while a request is in flight, so every response is merged onto the
// user's live edits rather than replacing them.

import { api } from './apiClient.js';
import { toast, useApi, generateUUID } from './utils.js';

const cloneItems = (items) => (items || []).map(it => ({ ...it }));

export const assistStore = {
    chatHistory: [],
    currentItems: [],
    undoStack: [],
    playlistTitle: '',
    playlistDescription: '',
    revisionId: '',
    isGenerating: false,

    prompt: '',
    isSaving: false,

    // Availability gate. Until statusLoaded is true the pane shows a neutral
    // loading state rather than flashing "AI Setup Required" at a configured user.
    statusLoaded: false,
    aiConfigured: false,
    vibeAvailable: false,
    provider: '',
    maxPlaylistSize: 50,
    aiDisabled: false,
    aiUnavailableReason: '',

    // Deltas applied by the user after a request was sent but before its response
    // arrived. Each entry carries the pre-request index so a pin can be re-inserted
    // where it was, not just flagged on an item that may be gone.
    _deltas: [],
    _initialized: false,

    init() {
        if (this._initialized) return;
        this._initialized = true;

        this.revisionId = generateUUID();

        Alpine.watch(() => Alpine.store('settings').activeUserId, (uid) => {
            if (uid) {
                this.reset();
                this.loadStatus();
            }
        });

        // A disable while the pane is open moves the view back to Builder and clears the
        // conversation state, so nothing AI stays on screen or in flight.
        Alpine.watch(() => Alpine.store('settings').generative_ai_available, (available) => {
            if (available) {
                this.loadStatus();
                return;
            }
            this.aiConfigured = false;
            this.vibeAvailable = false;
            this.isGenerating = false;
            this.aiDisabled = !!Alpine.store('settings').ai_disabled;
            if (Alpine.store('ui').currentTab === 'assist') Alpine.store('ui').setTab('mixed');
        });

        if (Alpine.store('settings')?.activeUserId) this.loadStatus();
    },

    async loadStatus() {
        // Nothing is asked of the server while generative AI is unavailable: the tab is
        // hidden, so there is no gate to render and no status to show.
        const sStore = Alpine.store('settings');
        if (sStore && !sStore.generative_ai_available) {
            this.aiConfigured = false;
            this.vibeAvailable = false;
            this.aiDisabled = !!sStore.ai_disabled;
            this.aiUnavailableReason = sStore.ai_unavailable_reason || '';
            this.statusLoaded = true;
            return;
        }
        try {
            const res = await useApi(api.get('api/ai/assist/status'), null, true, false);
            if (res.data) {
                this.aiConfigured = !!res.data.ai_configured;
                this.vibeAvailable = !!res.data.vibe_available;
                this.provider = res.data.provider || '';
                this.maxPlaylistSize = res.data.max_playlist_size || 50;
                this.aiDisabled = !!res.data.ai_disabled;
                this.aiUnavailableReason = res.data.ai_unavailable_reason || '';
                Alpine.store('settings').applyCapability(res.data);
            }
        } catch (e) {
            console.error('[MixerBee] Playlist Assist status failed:', e);
        } finally {
            this.statusLoaded = true;
        }
    },

    reset() {
        this.chatHistory = [];
        this.currentItems = [];
        this.undoStack = [];
        this.playlistTitle = '';
        this.playlistDescription = '';
        this.prompt = '';
        this._deltas = [];
        this.revisionId = generateUUID();
    },

    // --- Snapshots ---------------------------------------------------------

    // Deep and independent, so undo covers manual edits and AI turns alike.
    snapshot() {
        return {
            items: cloneItems(this.currentItems),
            title: this.playlistTitle,
            description: this.playlistDescription
        };
    },

    pushUndo() {
        this.undoStack.push(this.snapshot());
        if (this.undoStack.length > 30) this.undoStack.shift();
    },

    get canUndo() { return (this.undoStack || []).length > 0; },

    undo() {
        const prev = this.undoStack.pop();
        if (!prev) return;
        this.currentItems = cloneItems(prev.items);
        this.playlistTitle = prev.title;
        this.playlistDescription = prev.description;
        this.revisionId = generateUUID();
    },

    // --- Manual canvas edits (stay enabled during generation) --------------

    indexOfItem(id) {
        return this.currentItems.findIndex(it => it.Id === id);
    },

    _recordDelta(action, id, index, item) {
        if (!this.isGenerating) return;
        this._deltas.push({ action, id, index, item: item ? { ...item } : null });
    },

    togglePin(id) {
        const index = this.indexOfItem(id);
        if (index === -1) return;
        this.pushUndo();
        const item = this.currentItems[index];
        item.locked = !item.locked;
        this._recordDelta(item.locked ? 'pin' : 'unpin', id, index, item);
        this.revisionId = generateUUID();
    },

    removeItem(id) {
        const index = this.indexOfItem(id);
        if (index === -1) return;
        this.pushUndo();
        const [item] = this.currentItems.splice(index, 1);
        this._recordDelta('remove', id, index, item);
        this.revisionId = generateUUID();
    },

    clearCanvas() {
        if (!this.currentItems.length) return;
        this.pushUndo();
        this.currentItems.forEach(it => this._recordDelta('remove', it.Id, 0, it));
        this.currentItems = [];
        this.revisionId = generateUUID();
    },

    // --- Client-side merge -------------------------------------------------

    // Replay one mid-flight edit onto the array the backend just returned. Each
    // action is a different operation: a pin the backend never saw may need the
    // item re-inserted outright, while an unpin is not a removal.
    applyDelta(items, delta) {
        const at = items.findIndex(it => it.Id === delta.id);

        if (delta.action === 'remove') {
            if (at !== -1) items.splice(at, 1);
            return items;
        }

        if (delta.action === 'pin') {
            if (at !== -1) {
                items[at].locked = true;
            } else if (delta.item) {
                const target = Math.min(Math.max(delta.index, 0), items.length);
                items.splice(target, 0, { ...delta.item, locked: true });
            }
            return items;
        }

        if (delta.action === 'unpin' && at !== -1) {
            // The backend may have re-injected this as a pin. Unpinning is not a
            // removal, so the item stays and only its lock is cleared.
            items[at].locked = false;
        }
        return items;
    },

    mergeResponse(newItems) {
        let merged = cloneItems(newItems);
        for (const delta of this._deltas) merged = this.applyDelta(merged, delta);
        return merged;
    },

    // --- The turn ----------------------------------------------------------

    async sendPrompt() {
        if (this.isGenerating) return;
        if (!Alpine.store('settings').generative_ai_available) {
            return toast('AI features are turned off for this account.', false);
        }
        const prompt = (this.prompt || '').trim();
        if (!prompt) return toast('Type what you want changed first.', false);

        this.pushUndo();
        this.chatHistory.push({ role: 'user', content: prompt });
        this.prompt = '';

        const sentRevision = this.revisionId;
        this._deltas = [];
        this.isGenerating = true;

        try {
            const res = await useApi(api.post('api/ai/assist/chat', {
                prompt,
                revision_id: sentRevision,
                current_items: this.currentItems.map(it => ({
                    Id: it.Id, locked: !!it.locked, Name: it.Name || null
                })),
                chat_history: this.chatHistory.slice(0, -1)
            }), null, true, false);

            // A turn that lands after a disable must not touch the canvas.
            if (!Alpine.store('settings').generative_ai_available) return;

            if (res.status !== 'ok' || !res.data) {
                const detail = res.error?.detail || 'Playlist Assist could not complete that request.';
                this.chatHistory.push({ role: 'assistant', content: detail, isError: true });
                toast(detail, false);
                return;
            }

            const data = res.data;

            // The echoed revision is only a fast path: unchanged means no edits
            // landed mid-flight, so the merge step can be skipped. A mismatch is
            // never a reason to discard the response.
            const incoming = Array.isArray(data.new_items) ? data.new_items : [];
            this.currentItems = (data.revision_id === this.revisionId && this._deltas.length === 0)
                ? cloneItems(incoming)
                : this.mergeResponse(incoming);

            if (data.suggested_title) this.playlistTitle = data.suggested_title;
            if (data.suggested_description) this.playlistDescription = data.suggested_description;

            this.chatHistory.push({
                role: 'assistant',
                content: data.ai_chat_response || 'Updated the playlist.'
            });
            this.revisionId = generateUUID();
        } catch (e) {
            console.error('[MixerBee] Playlist Assist turn failed:', e);
            this.chatHistory.push({
                role: 'assistant',
                content: 'Something went wrong talking to the assistant.',
                isError: true
            });
        } finally {
            this.isGenerating = false;
            this._deltas = [];
        }
    },

    // --- Save --------------------------------------------------------------

    get pinnedCount() { return this.currentItems.filter(it => it.locked).length; },

    async save(btnEl) {
        if (this.isSaving) return;
        const name = (this.playlistTitle || '').trim();
        if (!name) return toast('Give the playlist a name first.', false);
        if (!this.currentItems.length) return toast('The playlist is empty.', false);

        this.isSaving = true;
        try {
            const res = await useApi(api.post('api/ai/assist/save', {
                playlist_name: name,
                description: (this.playlistDescription || '').trim(),
                item_ids: this.currentItems.map(it => it.Id),
                user_id: Alpine.store('settings').activeUserId
            }), btnEl);

            if (res.status === 'ok' && res.data?.warning) {
                toast(res.data.warning, false);
            }
        } finally {
            this.isSaving = false;
        }
    }
};
