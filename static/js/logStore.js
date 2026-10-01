// static/js/logStore.js
//
// Owner-only live log drawer. One stream per open drawer, retained entirely in page
// memory: nothing here writes log text to localStorage, sessionStorage or the server.
// Only the drawer height -- a display preference with no log content in it -- is saved.

import { api } from './apiClient.js';
import { toast } from './utils.js';

const STREAM_URL = 'api/admin/logs/stream';

// Browser-side retention. Independent of the server's ring: a long session can outlive
// far more records than the server holds, and the DOM is the scarcer resource.
const MAX_RECORDS = 1000;
const MAX_BYTES = 1024 * 1024;
const RENDER_INTERVAL_MS = 250;
const MAX_PENDING_BYTES = 4 * 1024 * 1024;

const RETRY_START_MS = 1000;
const RETRY_MAX_MS = 30000;

const HEIGHT_KEY = 'mixerbeeLogDrawerHeight';
const MIN_HEIGHT = 140;
const HEIGHT_STEP = 60;

const SEVERITIES = ['INFO', 'WARNING', 'ERROR', 'CRITICAL'];

const readStoredHeight = () => {
    try {
        const saved = parseInt(localStorage.getItem(HEIGHT_KEY) || '', 10);
        if (Number.isFinite(saved) && saved >= MIN_HEIGHT) return saved;
    } catch (e) {}
    return 0;
};

// Transport state lives here rather than on the store. Alpine wraps store properties
// in a reactive proxy, and none of this benefits from reactivity: an AbortController and
// a byte counter updated on every arriving record only pay the proxy's cost, and the
// counters would trigger re-renders of anything that read them.
let controller = null;
let retryTimer = null;
let retryDelay = RETRY_START_MS;
let renderTimer = null;
let pending = [];
let pendingBytes = 0;
let seenIds = new Set();
let retainedBytes = 0;
// Retired on every open, close, logout and account change. A response that resolves
// after its token was retired is discarded instead of writing into a closed drawer or
// another account's session.
let connectionToken = 0;

// visibleRecords is read several times per render -- the list, the empty state and the
// footer count -- and the filter walks up to MAX_RECORDS entries each time. Memoize on
// the reactive inputs so a burst costs one pass per change, not one per reference.
let visibleKey = null;
let visibleCache = [];
let totalsRevision = -1;
let totalsCache = { INFO: 0, WARNING: 0, ERROR: 0, CRITICAL: 0 };

export const logStore = {
    available: false,          // owner + verbose logging on
    isOpen: false,
    records: [],
    // Bumped whenever the retained set changes, so the memoized getters above can
    // tell a real change from a repeat read without walking the list.
    revision: 0,
    // 'idle' | 'connecting' | 'live' | 'reconnecting' | 'disconnected' | 'disabled' | 'denied'
    connection: 'idle',
    statusDetail: '',
    generation: '',
    cursor: '',
    following: true,
    pendingCount: 0,
    serverDropped: 0,
    browserDropped: 0,
    truncatedSeen: false,
    levels: { INFO: true, WARNING: true, ERROR: true, CRITICAL: true },
    search: '',
    subsystem: '',
    subsystems: [],
    height: readStoredHeight(),
    expanded: new Set(),
    visibleRecords: [],
    severityTotals: { INFO: 0, WARNING: 0, ERROR: 0, CRITICAL: 0 },
    statusLabel: 'Not connected',
    dropNotice: '',

    init() {
        if (!this.height) this.height = Math.round(window.innerHeight / 3);
        this.updateVisible();

        // Reload clears page memory anyway, but aborting first stops the stream from
        // being counted against the session's slot limit until the response times out.
        window.addEventListener('beforeunload', () => this._teardown());
        document.addEventListener('mixerbee:unauthorized', () => this.purge());
        document.addEventListener('keydown', (event) => {
            if (event.key !== 'Escape' || !this.isOpen) return;
            // Only when focus is inside the drawer, and never while a dialog is open:
            // Escape belongs to the topmost layer, which the drawer is not.
            const drawer = document.getElementById('log-drawer');
            if (!drawer || !drawer.contains(document.activeElement)) return;
            if (document.querySelector('.modal-overlay:not([style*="display: none"])')) return;
            this.close();
        });
    },

    // -- owner status ----------------------------------------------------------

    // Called at startup before the media-connection checks can return early, on focus,
    // and when Account settings opens, so the header button reflects a change made in
    // another tab or by another browser.
    async refreshAvailability({ silent = true } = {}) {
        const settings = Alpine.store('settings');
        if (!settings?.account?.is_admin) {
            this.available = false;
            if (this.isOpen) this.close();
            return false;
        }
        const res = await api.get('api/admin/settings/logging');
        if (res.status !== 'ok' || typeof res.data?.verbose_logging !== 'boolean') {
            if (!silent) toast('Could not read the logging setting.', false);
            return this.available;
        }
        this.applyVerbose(res.data.verbose_logging);
        return this.available;
    },

    // The single place the viewer reacts to the verbose setting, whichever way the
    // change arrived: this tab's checkbox, a status refresh, or a stream state event.
    applyVerbose(enabled) {
        this.available = !!enabled;
        if (enabled) {
            // Re-enabling starts a new server capture generation, so an old cursor is
            // worthless. Reconnect from scratch if the drawer is still open.
            if (this.isOpen && this.connection !== 'live') {
                this.cursor = '';
                this.connect();
            }
            return;
        }
        this._teardown();
        if (this.isOpen) {
            // Keep what was already captured readable and copyable; the owner may have
            // turned verbose off precisely because they found what they needed.
            this.connection = 'disabled';
            this.statusDetail = 'Verbose logging is off. These entries are the last ones received.';
        } else {
            this.reset();
        }
    },

    // -- drawer ----------------------------------------------------------------

    toggle() { this.isOpen ? this.close() : this.open(); },

    open() {
        if (!this.available) {
            toast('Turn on verbose logging in Account settings first.', false);
            return;
        }
        this.isOpen = true;
        this.following = true;
        this.pendingCount = 0;
        this.applyHeight(this.height);
        this.connect();
        requestAnimationFrame(() => {
            document.getElementById('log-drawer-close')?.focus();
            this.scrollToEnd();
        });
    },

    close() {
        this.isOpen = false;
        this._teardown();
        document.body.style.removeProperty('--log-drawer-height');
        if (this.available) {
            // Verbose is still on, so retained entries and the cursor stay in page
            // memory and reopening resumes where this stream left off.
            this.connection = 'idle';
            this.statusDetail = '';
        } else {
            this.reset();
        }
        document.getElementById('log-drawer-trigger')?.focus();
    },

    applyHeight(px) {
        const max = Math.max(MIN_HEIGHT, window.innerHeight - 120);
        this.height = Math.min(max, Math.max(MIN_HEIGHT, Math.round(px)));
        document.body.style.setProperty('--log-drawer-height', `${this.height}px`);
        try { localStorage.setItem(HEIGHT_KEY, String(this.height)); } catch (e) {}
    },

    nudgeHeight(direction) { this.applyHeight(this.height + direction * HEIGHT_STEP); },
    presetHeight(fraction) { this.applyHeight(window.innerHeight * fraction); },

    startResize(event) {
        const startY = event.clientY ?? event.touches?.[0]?.clientY;
        if (startY == null) return;
        const startHeight = this.height;
        const move = (e) => {
            const y = e.clientY ?? e.touches?.[0]?.clientY;
            if (y != null) this.applyHeight(startHeight + (startY - y));
        };
        const stop = () => {
            window.removeEventListener('pointermove', move);
            window.removeEventListener('pointerup', stop);
        };
        window.addEventListener('pointermove', move);
        window.addEventListener('pointerup', stop);
    },

    // -- transport -------------------------------------------------------------

    connect() {
        if (!this.isOpen || !this.available) return;
        this._teardown();

        const token = connectionToken;
        this.connection = this.records.length ? 'reconnecting' : 'connecting';
        this.statusDetail = '';
        this.updateVisible();
        controller = new AbortController();
        const signal = controller.signal;
        renderTimer = setInterval(() => this.flush(), RENDER_INTERVAL_MS);

        const url = this.cursor
            ? `${STREAM_URL}?after=${encodeURIComponent(this.cursor)}`
            : STREAM_URL;

        (async () => {
            const { response, error, status } = await api.stream(url, { signal });
            if (token !== connectionToken) {
                try { response?.body?.cancel(); } catch (e) {}
                return;
            }
            if (status === 'aborted') return;

            if (!response) {
                // Authorization, permission and disabled-capture answers are final:
                // retrying them would spin against a server that has already decided.
                if (status === 409 && error?.reason === 'logging_disabled') {
                    this.applyVerbose(false);
                    return;
                }
                if (status === 403 || status === 401) {
                    this.connection = 'denied';
                    this.statusDetail = error?.detail || 'This account cannot read MixerBee logs.';
                    this.updateVisible();
                    return;
                }
                if (status === 429) {
                    this.connection = 'disconnected';
                    this.statusDetail = error?.detail || 'Too many log viewers are open.';
                    this.updateVisible();
                    return;
                }
                this.scheduleRetry(error?.detail || 'Could not reach the log stream.');
                return;
            }

            this.connection = 'live';
            this.updateVisible();
            retryDelay = RETRY_START_MS;
            try {
                await this.readStream(response, token);
                if (token !== connectionToken) return;
                // A clean end of body with capture still on means the connection
                // dropped rather than the server declining to continue.
                if (this.connection === 'live') this.scheduleRetry('The log stream ended.');
            } catch (err) {
                if (token !== connectionToken || err?.name === 'AbortError') return;
                this.scheduleRetry('The log stream was interrupted.');
            }
        })();
    },

    // Incremental SSE parse. Must survive a frame split across reads, a multi-byte
    // UTF-8 character split across reads, and a frame larger than one read.
    async readStream(response, token) {
        const reader = response.body.getReader();
        const decoder = new TextDecoder('utf-8');
        let buffer = '';

        while (true) {
            const { value, done } = await reader.read();
            if (done || token !== connectionToken) break;
            // stream: true carries a partial character over to the next chunk.
            buffer += decoder.decode(value, { stream: true });

            if (buffer.length > MAX_PENDING_BYTES) {
                // A frame this large cannot be one of ours. Drop the partial buffer
                // rather than growing it without bound.
                buffer = '';
                this.statusDetail = 'Discarded an oversized log frame.';
                continue;
            }

            let split;
            while ((split = buffer.indexOf('\n\n')) !== -1) {
                const frame = buffer.slice(0, split);
                buffer = buffer.slice(split + 2);
                this.handleFrame(frame);
                if (token !== connectionToken) return;
            }
        }
        this.flush();
    },

    handleFrame(frame) {
        let name = 'message';
        const dataLines = [];
        for (const rawLine of frame.split('\n')) {
            const line = rawLine.endsWith('\r') ? rawLine.slice(0, -1) : rawLine;
            if (!line || line.startsWith(':')) continue;      // heartbeat comment
            if (line.startsWith('event:')) name = line.slice(6).trim();
            else if (line.startsWith('data:')) dataLines.push(line.slice(5).replace(/^ /, ''));
        }
        if (!dataLines.length) return;

        let payload;
        try { payload = JSON.parse(dataLines.join('\n')); } catch (e) { return; }

        switch (name) {
            case 'ready':
                this.generation = payload.generation || '';
                break;
            case 'logs':
                this.queue(payload.records || []);
                break;
            case 'gap':
                this.serverDropped += payload.skipped || 0;
                break;
            case 'reset':
                // A restart or a verbose re-enable. The old entries describe a capture
                // that no longer exists, so they are marked rather than silently mixed
                // with the new generation's records.
                this.generation = payload.generation || '';
                this.cursor = '';
                this.flush();
                for (const record of this.records) record.stale = true;
                this.revision += 1;
                break;
            case 'state':
                this.applyVerbose(false);
                break;
            case 'auth_expired':
                this.purge(payload.detail || 'This session is no longer signed in.');
                break;
        }
    },

    // Records are buffered and rendered on a timer: a burst of a hundred lines must
    // not mean a hundred Alpine re-renders.
    queue(records) {
        for (const record of records) {
            if (!record?.id || seenIds.has(record.id)) continue;
            seenIds.add(record.id);
            pending.push(record);
            pendingBytes += (record.message || '').length;
        }
        if (pendingBytes > MAX_PENDING_BYTES) this.flush();
    },

    flush() {
        if (!pending.length) return;
        const incoming = pending;
        pending = [];
        pendingBytes = 0;

        // The cursor only advances past records that are now retained, so an aborted
        // read cannot leave a gap that a reconnect would skip over.
        const last = incoming[incoming.length - 1];
        if (last?.gen && last?.seq) this.cursor = `${last.gen}:${last.seq}`;

        const subsystems = new Set(this.subsystems);
        for (const record of incoming) {
            record.time = this.formatTime(record.ts);
            if (record.truncated) this.truncatedSeen = true;
            subsystems.add(record.logger);
            this.records.push(record);
            retainedBytes += (record.message || '').length;
        }
        if (subsystems.size !== this.subsystems.length) {
            this.subsystems = [...subsystems].sort();
        }

        while (this.records.length > MAX_RECORDS || retainedBytes > MAX_BYTES) {
            const dropped = this.records.shift();
            if (!dropped) break;
            retainedBytes -= (dropped.message || '').length;
            seenIds.delete(dropped.id);
            this.expanded.delete(dropped.id);
            this.browserDropped += 1;
        }

        this.revision += 1;
        this.updateVisible();
        if (this.following) this.scrollToEnd();
        else this.pendingCount += incoming.length;
    },

    scheduleRetry(detail) {
        this._teardown();
        if (!this.isOpen || !this.available) return;
        this.connection = 'reconnecting';
        this.statusDetail = `${detail} Reconnecting...`;
        this.updateVisible();
        const delay = retryDelay;
        retryDelay = Math.min(RETRY_MAX_MS, Math.round(delay * 2));
        retryTimer = setTimeout(() => {
            retryTimer = null;
            this.connect();
        }, delay);
    },

    retryNow() {
        retryDelay = RETRY_START_MS;
        this.connect();
    },

    // Abort the stream and cancel retries, leaving retained entries alone. Always
    // retires the connection token: anything still in flight from the old stream must
    // not be able to write a record or schedule another retry after this point.
    _teardown() {
        connectionToken += 1;
        if (retryTimer) { clearTimeout(retryTimer); retryTimer = null; }
        if (renderTimer) { clearInterval(renderTimer); renderTimer = null; }
        if (controller) {
            try { controller.abort(); } catch (e) {}
            controller = null;
        }
    },

    // Drop every retained entry. Used on sign-out, account change, session expiry,
    // and whenever the drawer closes while capture is off.
    reset() {
        this.records = [];
        this.subsystems = [];
        this.expanded = new Set();
        seenIds = new Set();
        pending = [];
        pendingBytes = 0;
        retainedBytes = 0;
        this.cursor = '';
        this.generation = '';
        this.pendingCount = 0;
        this.serverDropped = 0;
        this.browserDropped = 0;
        this.truncatedSeen = false;
        this.connection = 'idle';
        this.statusDetail = '';
        this.revision += 1;
        this.updateVisible();
    },

    purge(detail = '') {
        this._teardown();
        this.reset();
        this.available = false;
        this.isOpen = false;
        document.body.style.removeProperty('--log-drawer-height');
        if (detail) this.statusDetail = detail;
    },

    // -- view ------------------------------------------------------------------

    formatTime(ts) {
        // The server sends a UTC epoch; the reader wants their own clock.
        const date = new Date((Number(ts) || 0) * 1000);
        if (Number.isNaN(date.getTime())) return '';
        const pad = (n, width = 2) => String(n).padStart(width, '0');
        return `${pad(date.getHours())}:${pad(date.getMinutes())}:${pad(date.getSeconds())}`
             + `.${pad(date.getMilliseconds(), 3)}`;
    },

    updateVisible() {
        const needle = (this.search || '').trim().toLowerCase();
        this.visibleRecords = this.records.filter(record => {
            if (!this.levels[record.level]) return false;
            if (this.subsystem && record.logger !== this.subsystem) return false;
            if (!needle) return true;
            return (record.message || '').toLowerCase().includes(needle)
                || (record.logger || '').toLowerCase().includes(needle);
        });

        const totals = { INFO: 0, WARNING: 0, ERROR: 0, CRITICAL: 0 };
        for (const record of this.records) {
            if (record.level in totals) totals[record.level] += 1;
        }
        this.severityTotals = totals;

        const parts = [];
        if (this.serverDropped) parts.push(`${this.serverDropped} older entries expired on the server`);
        if (this.browserDropped) parts.push(`${this.browserDropped} dropped from this view`);
        if (this.truncatedSeen) parts.push('some long messages are truncated');
        this.dropNotice = parts.length ? `${parts.join('; ')}.` : '';

        this.statusLabel = {
            idle: 'Not connected', connecting: 'Connecting...', live: 'Live',
            reconnecting: 'Reconnecting...', disconnected: 'Disconnected',
            disabled: 'Verbose logging is off', denied: 'Not permitted'
        }[this.connection] || this.connection;
    },

    getVisibleRecords() {
        return this.visibleRecords;
    },

    getSeverityTotals() {
        return this.severityTotals;
    },

    getStatusLabel() {
        return this.statusLabel;
    },

    getDropNotice() {
        return this.dropNotice;
    },

    toggleLevel(level) {
        if (!SEVERITIES.includes(level)) return;
        this.levels = { ...this.levels, [level]: !this.levels[level] };
        this.updateVisible();
    },

    isExpanded(id) { return this.expanded.has(id); },

    toggleExpanded(id) {
        const next = new Set(this.expanded);
        next.has(id) ? next.delete(id) : next.add(id);
        this.expanded = next;
    },

    isMultiline(record) { return (record.message || '').includes('\n'); },

    firstLine(record) {
        const message = record.message || '';
        const newline = message.indexOf('\n');
        return newline === -1 ? message : message.slice(0, newline);
    },

    onScroll(event) {
        const el = event.target;
        // Within a couple of pixels of the bottom still counts as following, so a
        // fractional scroll height or a trackpad bounce does not pause the feed.
        const atEnd = el.scrollHeight - el.scrollTop - el.clientHeight < 24;
        if (atEnd && !this.following) {
            this.following = true;
            this.pendingCount = 0;
        } else if (!atEnd && this.following) {
            this.following = false;
        }
    },

    resumeFollow() {
        this.following = true;
        this.pendingCount = 0;
        this.scrollToEnd();
    },

    scrollToEnd() {
        requestAnimationFrame(() => {
            const body = document.getElementById('log-drawer-body');
            if (body) body.scrollTop = body.scrollHeight;
        });
    },

    // Clears this browser's view only. The cursor is preserved, so the server keeps
    // streaming from where it was and nothing is re-delivered.
    clearView() {
        this.records = [];
        this.expanded = new Set();
        seenIds = new Set();
        retainedBytes = 0;
        this.browserDropped = 0;
        this.serverDropped = 0;
        this.truncatedSeen = false;
        this.pendingCount = 0;
        this.following = true;
        this.revision += 1;
        this.updateVisible();
    },

    exportText() {
        return this.getVisibleRecords()
            .map(r => `${r.time} ${r.level.padEnd(8)} [${r.logger}] (${r.thread}) ${r.message}`)
            .join('\n');
    },

    async copyVisible(button) {
        const text = this.exportText();
        if (!text) { toast('No log entries match the current filters.', false); return; }
        try {
            await navigator.clipboard.writeText(text);
            toast(`Copied ${this.getVisibleRecords().length} log entries.`, true);
        } catch (e) {
            // Clipboard access needs a secure context, which a plain-HTTP self-hosted
            // install is not. Download is the fallback, not a dead end.
            toast('Clipboard unavailable here. Use Download instead.', false);
        }
    },

    downloadVisible() {
        const text = this.exportText();
        if (!text) { toast('No log entries match the current filters.', false); return; }
        const stamp = new Date().toISOString().replace(/[:.]/g, '-').slice(0, 19);
        const url = URL.createObjectURL(new Blob([text], { type: 'text/plain' }));
        const link = document.createElement('a');
        link.href = url;
        link.download = `mixerbee-logs-${stamp}.log`;
        link.click();
        URL.revokeObjectURL(url);
    }
};
