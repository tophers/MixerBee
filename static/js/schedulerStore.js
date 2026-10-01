// static/js/schedulerStore.js

import { api } from './apiClient.js';
import { toast, generateUUID, useApi } from './utils.js';
import { confirmModal } from './modals.js';

const DAY_NAMES = ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat'];
const RUN_POLL_MS = 3000;
const RUN_POLL_MAX = 200;

export const schedulerStore = {
    schedule: [],
    isLoading: false,
    _pollTimer: null,
    _pollCount: 0,

    async loadSchedule() {
        this.isLoading = true;
        try {
            await Alpine.store('presets').refresh();
            const res = await useApi(api.get('api/schedules'), null, true, false);
            if (res.data) {
                const rawList = Array.isArray(res.data) ? res.data : [];
                this.schedule = rawList.map(entry => {
                    const details = entry.schedule_details || {};
                    return {
                        ...entry,
                        _uid: generateUUID(),
                        preset_id: entry.preset_id || "",
                        job_type: entry.job_type || "builder",
                        playlist_name: entry.playlist_name || entry.preset_name || "Scheduled Mix",
                        user_id: entry.user_id || Alpine.store('settings').activeUserId || "",
                        create_as_collection: !!entry.create_as_collection,
                        enabled: entry.enabled !== false,
                        snoozed_until: entry.snoozed_until || null,
                        trigger_sources: entry.trigger_sources || ['clock', 'watch', 'library'],
                        quick_playlist_data: entry.quick_playlist_data ? { ...entry.quick_playlist_data, options: entry.quick_playlist_data.options || {} } : { quick_playlist_type: 'recently_added', options: { count: 25 } },
                        enrichment_data: entry.enrichment_data || { batch_size: 15, timeout: 120 },
                        schedule_details: {
                            time: details.time || entry.time || "12:00",
                            frequency: details.frequency || entry.frequency || "daily",
                            interval_minutes: details.interval_minutes || 30,
                            days_of_week: Array.isArray(details.days_of_week) ? details.days_of_week.map(Number) : [0, 1, 2, 3, 4, 5, 6]
                        }
                    };
                });
                if (this.schedule.some(e => e.is_running)) this.startRunPolling();
            }
        } catch (err) {
            console.error("Scheduler Load Error:", err);
            toast("Failed to load schedules", false);
        } finally {
            this.isLoading = false;
        }
    },

    async saveSchedule(entry, btnEl) {
        if (!entry) return;
        if (entry.create_as_collection && !Alpine.store('settings').can_manage_collections) {
            return toast('This media account cannot manage collections. Choose Playlist output.', false);
        }
        const uid = Alpine.store('settings').activeUserId;
        let freq = entry.schedule_details.frequency;
        if (freq !== 'interval') freq = (entry.schedule_details?.days_of_week?.length === 7) ? "daily" : "weekly";

        const presetId = entry.preset_id || "";
        const payload = {
            user_id: uid,
            job_type: entry.job_type || "builder",
            playlist_name: entry.playlist_name || "Scheduled Mix",
            preset_id: presetId,
            preset_name: presetId ? Alpine.store('presets').nameForId(presetId) : "",
            quick_playlist_data: entry.job_type === 'quick_playlist' ? entry.quick_playlist_data : null,
            enrichment_data: entry.job_type === 'enrichment' ? entry.enrichment_data : null,
            schedule_details: {
                time: entry.schedule_details.time,
                frequency: freq,
                days_of_week: entry.schedule_details.days_of_week,
                interval_minutes: parseInt(entry.schedule_details.interval_minutes) || 30
            },
            create_as_collection: !!entry.create_as_collection,
            mix_options: entry.mix_options || (presetId ? (Alpine.store('presets').records.find(r => r.id === presetId)?.mix_options || null) : null),
            enabled: entry.enabled !== false,
            snoozed_until: entry.snoozed_until || null,
            trigger_sources: entry.trigger_sources || ['clock', 'watch', 'library']
        };

        try {
            let res = entry.id 
                ? await useApi(api.put(`api/schedules/${entry.id}`, payload), btnEl)
                : await useApi(api.post('api/schedules', payload), btnEl);
            
            if (res && res.status === 'ok') {
                if (res.data?.id) entry.id = res.data.id;
                this.schedule = [...this.schedule];
            }
        } catch (err) { }
    },

    async toggleEnabled(entry, btnEl) {
        if (!entry.id) {
            entry.enabled = !entry.enabled;
            return;
        }
        const endpoint = entry.enabled ? `api/schedules/${entry.id}/pause` : `api/schedules/${entry.id}/resume`;
        try {
            const res = await useApi(api.post(endpoint, {}), btnEl);
            if (res && res.status === 'ok') {
                entry.enabled = !entry.enabled;
                if (entry.enabled) entry.snoozed_until = null;
                this.schedule = [...this.schedule];
                toast(entry.enabled ? 'Schedule resumed.' : 'Schedule paused.', true);
            }
        } catch (err) { }
    },

    async snooze(entry, minutes, btnEl) {
        if (!entry.id) return toast("Save schedule first.", false);
        try {
            const res = await useApi(api.post(`api/schedules/${entry.id}/snooze`, { minutes }), btnEl);
            if (res && res.status === 'ok') {
                entry.snoozed_until = new Date(Date.now() + minutes * 60000).toISOString();
                this.schedule = [...this.schedule];
                toast(`Snoozed for ${minutes} minutes.`, true);
            }
        } catch (err) { }
    },

    async runNow(entry, btnEl) {
        if (!entry?.id) return toast("Save the schedule first to generate a Job ID.", false);
        if (entry.is_running) return;
        try {
            const res = await useApi(api.post(`api/schedules/${entry.id}/run`, {}), btnEl);
            if (res && res.status === 'ok') {
                entry.is_running = true;
                this.schedule = [...this.schedule];
                this.startRunPolling();
            }
        } catch (err) { }
    },

    // Refreshes only the runtime fields, so an open edit modal never loses unsaved changes.
    startRunPolling() {
        this._pollCount = 0;
        if (this._pollTimer) return;
        this._pollTimer = setInterval(() => this.refreshRunState(), RUN_POLL_MS);
    },

    stopRunPolling() {
        clearInterval(this._pollTimer);
        this._pollTimer = null;
    },

    async refreshRunState() {
        this._pollCount += 1;
        if (this._pollCount > RUN_POLL_MAX || Alpine.store('ui').currentTab !== 'scheduler') {
            this.stopRunPolling();
            return;
        }
        const res = await useApi(api.get('api/schedules'), null, true, false);
        if (!Array.isArray(res?.data)) return;
        const byId = new Map(res.data.map(s => [s.id, s]));
        for (const entry of this.schedule) {
            const fresh = entry.id && byId.get(entry.id);
            if (!fresh) continue;
            const finished = entry.is_running && !fresh.is_running;
            entry.is_running = !!fresh.is_running;
            entry.last_run = fresh.last_run || null;
            entry.next_run_time = fresh.next_run_time || null;
            if (finished && fresh.last_run) {
                const ok = fresh.last_run.status === 'ok';
                toast(`${entry.playlist_name}: ${ok ? 'run finished' : 'run failed'}${fresh.last_run.log?.length ? ' — ' + fresh.last_run.log[fresh.last_run.log.length - 1] : ''}`, ok);
            }
        }
        this.schedule = [...this.schedule];
        if (!this.schedule.some(e => e.is_running)) this.stopRunPolling();
    },

    async removeEntry(entry, btnEl) {
        if (!entry.id) {
            this.schedule = this.schedule.filter(s => s !== entry);
            return;
        }
        try {
            await confirmModal.show({
                title: 'Delete Job?',
                text: `Delete the scheduled job "${entry.playlist_name}"? Playlists it already built stay on the media server.`,
                confirmText: 'Delete',
                isDanger: true
            });
        } catch (e) { return; }
        try {
            const res = await useApi(api.del(`api/schedules/${entry.id}`), btnEl);
            if (res && res.status === 'ok') this.schedule = this.schedule.filter(s => s !== entry);
        } catch (err) { }
    },

    addEntry() {
        const newEntry = {
            id: null, _uid: generateUUID(), job_type: "builder", playlist_name: "New Scheduled Mix",
            preset_id: "", preset_name: "", user_id: Alpine.store('settings').activeUserId, create_as_collection: false,
            enabled: true, snoozed_until: null, trigger_sources: ['clock', 'watch', 'library'],
            quick_playlist_data: { quick_playlist_type: 'recently_added', options: { count: 25 } },
            enrichment_data: { batch_size: 15, timeout: 120 },
            schedule_details: { time: "12:00", frequency: "daily", interval_minutes: 30, days_of_week: [0, 1, 2, 3, 4, 5, 6] }
        };
        this.schedule = [...this.schedule, newEntry];
        return newEntry._uid;
    },

    duplicateEntry(entry) {
        const copy = JSON.parse(JSON.stringify(entry));
        Object.assign(copy, {
            id: null, _uid: generateUUID(), playlist_name: `${entry.playlist_name} (copy)`,
            last_run: null, next_run_time: null, is_running: false
        });
        const idx = this.schedule.indexOf(entry);
        const list = [...this.schedule];
        list.splice(idx + 1, 0, copy);
        this.schedule = list;
        return copy._uid;
    },

    formatDays(days) {
        const set = [...new Set((days || []).map(Number))].sort((a, b) => a - b);
        if (set.length === 7) return 'Daily';
        if (set.length === 0) return 'No days';
        if (set.join() === '1,2,3,4,5') return 'Weekdays';
        if (set.join() === '0,6') return 'Weekends';
        // Collapse consecutive runs (Mon–Wed) so long selections stay short.
        const parts = [];
        let start = set[0], prev = set[0];
        for (const d of [...set.slice(1), null]) {
            if (d === prev + 1) { prev = d; continue; }
            parts.push(prev - start >= 2 ? `${DAY_NAMES[start]}–${DAY_NAMES[prev]}` : (start === prev ? DAY_NAMES[start] : `${DAY_NAMES[start]}, ${DAY_NAMES[prev]}`));
            start = prev = d;
        }
        return parts.join(', ');
    },

    formatRelative(iso) {
        if (!iso) return '';
        const then = new Date(iso);
        if (isNaN(then)) return '';
        const diffMs = then - Date.now();
        if (Math.abs(diffMs) < 60000) return 'just now';
        const abs = Math.round(Math.abs(diffMs) / 60000);
        let text;
        if (abs < 60) text = `${abs}m`;
        else if (abs < 60 * 24) text = `${Math.round(abs / 60)}h`;
        else text = `${Math.round(abs / 1440)}d`;
        return diffMs < 0 ? `${text} ago` : `in ${text}`;
    },

    nextRunLabel(entry) {
        if (!entry.id) return 'Not saved';
        if (!entry.enabled) return 'Paused';
        if (entry.snoozed_until && new Date(entry.snoozed_until) > new Date()) return 'Snoozed until ' + new Date(entry.snoozed_until).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
        if (!(entry.trigger_sources || []).includes('clock')) return 'Webhook only';
        return entry.next_run_time ? this.formatRelative(entry.next_run_time) : '—';
    },

    lastRunLog(entry) {
        const log = entry.last_run?.log;
        return Array.isArray(log) ? log.join(' • ') : '';
    },

    toggleDay(entry, dayNum) {
        let days = [...(entry.schedule_details.days_of_week || [])];
        if (days.includes(dayNum)) days = days.filter(d => d !== dayNum);
        else days.push(dayNum);
        entry.schedule_details.days_of_week = days.sort((a,b) => a - b);
        this.schedule = [...this.schedule];
    },

    formatRulesSummary(mixOptions) {
        if (!mixOptions) return 'Default mix rules (no active constraints).';
        const parts = [];
        if (mixOptions.freshness?.last_successful_builds > 0) {
            parts.push(`Cooldown: ${mixOptions.freshness.last_successful_builds} builds`);
        }
        if (mixOptions.freshness?.watched_within_days > 0) {
            parts.push(`Exclude watched < ${mixOptions.freshness.watched_within_days}d`);
        }
        if (mixOptions.duplicate_policy?.max_movies_per_franchise > 0) {
            parts.push(`Max ${mixOptions.duplicate_policy.max_movies_per_franchise} per franchise`);
        }
        if (mixOptions.sequencing?.mode && mixOptions.sequencing.mode !== 'sequential') {
            parts.push(`Sequencing: ${mixOptions.sequencing.mode}`);
        }
        if (mixOptions.runtime_budget?.mode && mixOptions.runtime_budget.mode !== 'off' && mixOptions.runtime_budget.target_minutes > 0) {
            parts.push(`Budget: ${mixOptions.runtime_budget.target_minutes}m`);
        }
        return parts.length > 0 ? parts.join(' • ') : 'Default mix rules (no active constraints).';
    },

    async loadAlbumsForArtist(entry, artistId) {
        if (!artistId) {
            entry._artistAlbums = [];
            return;
        }
        entry._loadingAlbums = true;
        try {
            const albums = await Alpine.store('mixer').loadArtistAlbums(artistId);
            entry._artistAlbums = albums || [];
        } catch (e) {
            console.error('Failed to load artist albums for scheduler:', e);
            entry._artistAlbums = [];
        } finally {
            entry._loadingAlbums = false;
            this.schedule = [...this.schedule];
        }
    }
};
