/* static/js/schedulerStore.js */

import { post, toast, generateUUID } from './utils.js';

export const schedulerStore = {
    schedule: [],
    isLoading: false,

    async loadSchedule() {
        this.isLoading = true;
        try {
            await Alpine.store('presets').refresh();

            const response = await fetch('api/schedules');
            if (response.ok) {
                const data = await response.json();
                const rawList = Array.isArray(data) ? data : [];

                this.schedule = rawList.map(entry => {
                    const details = entry.schedule_details || {};
                    return {
                        ...entry,
                        _uid: generateUUID(),
                        job_type: entry.job_type || "builder",
                        playlist_name: entry.playlist_name || entry.preset_name || "Scheduled Mix",
                        user_id: entry.user_id || Alpine.store('settings').activeUserId || "",
                        create_as_collection: !!entry.create_as_collection,
                        enrichment_data: entry.enrichment_data || { batch_size: 15, timeout: 120 },
                        schedule_details: {
                            time: details.time || entry.time || "12:00",
                            frequency: details.frequency || entry.frequency || "daily",
                            interval_minutes: details.interval_minutes || 30,
                            days_of_week: Array.isArray(details.days_of_week)
                                ? details.days_of_week.map(Number)
                                : [0, 1, 2, 3, 4, 5, 6]
                        }
                    };
                });
            }
        } catch (err) {
            console.error("Scheduler Load Error:", err);
        } finally {
            this.isLoading = false;
        }
    },

    async saveSchedule(entry, btnEl) {
        if (!entry) return;
        const uid = Alpine.store('settings').activeUserId;
        
        let freq = entry.schedule_details.frequency;
        if (freq !== 'interval') {
            freq = (entry.schedule_details?.days_of_week?.length === 7) ? "daily" : "weekly";
        }

        const payload = {
            user_id: uid,
            job_type: entry.job_type || "builder",
            playlist_name: entry.playlist_name || "Scheduled Mix",
            preset_name: entry.preset_name || "",
            quick_playlist_data: entry.quick_playlist_data || null,
            enrichment_data: entry.enrichment_data || null,
            schedule_details: {
                time: entry.schedule_details.time,
                frequency: freq,
                days_of_week: entry.schedule_details.days_of_week,
                interval_minutes: parseInt(entry.schedule_details.interval_minutes) || 30
            },
            create_as_collection: !!entry.create_as_collection
        };

        try {
            let res;
            if (entry.id) {
                res = await post(`api/schedules/${entry.id}`, payload, btnEl, 'PUT');
            } else {
                res = await post('api/schedules', payload, btnEl);
                if (res && res.id) entry.id = res.id;
            }

            if (res && res.status === 'ok') {
                this.schedule = [...this.schedule];
            }
        } catch (err) {
            console.error("Backend Save Error:", err);
        }
    },

    async runNow(id, btnEl) {
        if (!id) return toast("Save the schedule first to generate a Job ID.", false);
        try {
            await post(`api/schedules/${id}/run`, {}, btnEl);
        } catch (err) {
            console.error("Manual run failed:", err);
        }
    },

    async removeEntry(entry, btnEl) {
        if (!entry.id) {
            this.schedule = this.schedule.filter(s => s !== entry);
            return;
        }
        try {
            const res = await post(`api/schedules/${entry.id}`, {}, btnEl, 'DELETE');
            if (res && res.status === 'ok') {
                this.schedule = this.schedule.filter(s => s !== entry);
            }
        } catch (err) {
            console.error("Delete failed:", err);
        }
    },

    addEntry() {
        const uid = Alpine.store('settings').activeUserId;
        const newEntry = {
            id: null,
            _uid: generateUUID(),
            job_type: "builder",
            playlist_name: "New Scheduled Mix",
            preset_name: "",
            user_id: uid,
            create_as_collection: false,
            enrichment_data: { batch_size: 15, timeout: 120 },
            schedule_details: {
                time: "12:00",
                frequency: "daily",
                interval_minutes: 30,
                days_of_week: [0, 1, 2, 3, 4, 5, 6]
            }
        };
        this.schedule = [...this.schedule, newEntry];
        return newEntry._uid;
    },

    toggleDay(entry, dayNum) {
        let days = [...(entry.schedule_details.days_of_week || [])];
        if (days.includes(dayNum)) {
            days = days.filter(d => d !== dayNum);
        } else {
            days.push(dayNum);
        }
        entry.schedule_details.days_of_week = days.sort((a,b) => a - b);
        this.schedule = [...this.schedule];
    }
};