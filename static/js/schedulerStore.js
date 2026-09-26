// static/js/schedulerStore.js

import { api } from './apiClient.js';
import { toast, generateUUID, useApi } from './utils.js';

export const schedulerStore = {
    schedule: [],
    isLoading: false,

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
                        quick_playlist_data: entry.quick_playlist_data || { quick_playlist_type: 'recently_added', options: { count: 25 } },
                        enrichment_data: entry.enrichment_data || { batch_size: 15, timeout: 120 },
                        schedule_details: {
                            time: details.time || entry.time || "12:00",
                            frequency: details.frequency || entry.frequency || "daily",
                            interval_minutes: details.interval_minutes || 30,
                            days_of_week: Array.isArray(details.days_of_week) ? details.days_of_week.map(Number) : [0, 1, 2, 3, 4, 5, 6]
                        }
                    };
                });
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

    async runNow(id, btnEl) {
        if (!id) return toast("Save the schedule first to generate a Job ID.", false);
        try { await useApi(api.post(`api/schedules/${id}/run`, {}), btnEl); } catch (err) { }
    },

    async removeEntry(entry, btnEl) {
        if (!entry.id) {
            this.schedule = this.schedule.filter(s => s !== entry);
            return;
        }
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

    toggleDay(entry, dayNum) {
        let days = [...(entry.schedule_details.days_of_week || [])];
        if (days.includes(dayNum)) days = days.filter(d => d !== dayNum);
        else days.push(dayNum);
        entry.schedule_details.days_of_week = days.sort((a,b) => a - b);
        this.schedule = [...this.schedule];
    }
};
