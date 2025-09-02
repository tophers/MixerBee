"""
scheduler.py – Manages schedules for MixerBee
"""
import json
import logging
import uuid
from typing import Dict, List, Optional, Any
from datetime import datetime

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.jobstores.base import JobLookupError

import app as core
import app.items as items_api
from app.cache import refresh_cache
import app_state
import database

logging.basicConfig()
logging.getLogger('apscheduler').setLevel(logging.INFO)

QUICK_PLAYLIST_MAP = {
    "recently_added": items_api.create_recently_added_playlist,
    "next_up": items_api.create_continue_watching_playlist,
    "pilot_sampler": items_api.create_pilot_sampler_playlist,
    "from_the_vault": items_api.create_forgotten_favorites_playlist,
}
LEGACY_TYPE_MAP = {"continue_watching": "next_up", "forgotten_favorites": "from_the_vault"}

def run_playlist_job(**schedule_data) -> Dict:
    schedule_id, user_id, playlist_name, job_type = schedule_data.get("id"), schedule_data.get("user_id"), schedule_data.get("playlist_name"), schedule_data.get("job_type", "builder")
    log_messages = []
    if not all([user_id, playlist_name]):
        msg = f"SCHEDULER: Job '{schedule_id}' is missing required data. Aborting."
        logging.error(msg)
        return {"status": "error", "log": [msg]}
    print(f"SCHEDULER: Running job '{schedule_id}' for playlist '{playlist_name}' (Type: {job_type}) for user {user_id}")
    result = {}
    try:
        _, token = core.authenticate(core.EMBY_USER, core.EMBY_PASS, core.EMBY_URL, app_state.SERVER_TYPE)
        hdr = core.auth_headers(token, user_id=user_id)

        if job_type == "builder":
            blocks = schedule_data.get("blocks", [])
            if not blocks: raise ValueError("Scheduled builder job has no blocks.")
            result = core.create_mixed_playlist(user_id=user_id, playlist_name=playlist_name, blocks=blocks, hdr=hdr)
        elif job_type == "quick_playlist":
            quick_playlist_data = schedule_data.get("quick_playlist_data", {})
            quick_playlist_type = quick_playlist_data.get("quick_playlist_type")
            func_to_call = QUICK_PLAYLIST_MAP.get(quick_playlist_type)
            if not func_to_call: raise ValueError(f"Unknown quick_playlist_type '{quick_playlist_type}'")
            options = quick_playlist_data.get("options", {})
            result = func_to_call(user_id=user_id, playlist_name=playlist_name, hdr=hdr, log=log_messages, **options)

        final_log, final_status = result.get("log", ["No log messages."]), result.get("status", "error")
        logging.info(f"SCHEDULER: Job '{schedule_id}' for '{playlist_name}' completed with status: {final_status.upper()}.")
    except Exception as e:
        error_message = f"CRITICAL ERROR running job '{schedule_id}' for playlist '{playlist_name}': {e}"
        logging.error(f"SCHEDULER: {error_message}", exc_info=True)
        result = {"status": "error", "log": [error_message]}
    return result

def scheduled_job_wrapper(**schedule_data):
    result = run_playlist_job(**schedule_data)
    if schedule_id := schedule_data.get("id"):
        last_run_info = {"timestamp": datetime.now().isoformat(), "status": result.get("status", "error"), "log": result.get("log", ["An unknown error occurred."])}
        scheduler_manager._update_schedule_last_run(schedule_id, last_run_info)

class Scheduler:
    def __init__(self):
        self.scheduler = BackgroundScheduler(daemon=True)
        self.schedules: Dict[str, Dict] = {}

    def _update_schedule_last_run(self, schedule_id: str, last_run_info: Dict):
        """Safely updates the last_run status in both the DB and in-memory cache."""
        try:
            conn = database.get_db_connection()
            last_run_json = json.dumps(last_run_info)
            conn.execute("UPDATE schedules SET last_run = ? WHERE id = ?", (last_run_json, schedule_id))
            conn.commit()
            conn.close()

            if schedule_id in self.schedules:
                self.schedules[schedule_id]['last_run'] = last_run_info
                logging.info(f"Updated in-memory last_run for schedule {schedule_id}")

        except Exception as e:
            logging.error(f"SCHEDULER: Error updating last run status for {schedule_id} in DB: {e}", exc_info=True)

    def _load_schedules(self) -> Dict[str, Dict]:
        schedules = {}
        try:
            conn = database.get_db_connection()
            rows = conn.execute("SELECT id, playlist_name, user_id, job_type, crontab, config_data, last_run FROM schedules").fetchall()
            conn.close()
            for row in rows:
                schedule_data = dict(row)
                config_data = json.loads(row['config_data']) if row['config_data'] else {}
                last_run = json.loads(row['last_run']) if row['last_run'] else None
                schedule_data.update(config_data)
                schedule_data['config_data'], schedule_data['last_run'] = config_data, last_run
                schedules[row['id']] = schedule_data
            for schedule_id, data in schedules.items():
                if data.get("job_type") == "quick_playlist":
                    qpd = data.get("quick_playlist_data", {})
                    if (old_type := qpd.get("quick_playlist_type")) in LEGACY_TYPE_MAP:
                        new_type = LEGACY_TYPE_MAP[old_type]
                        data["quick_playlist_data"]["quick_playlist_type"] = new_type
                        logging.info(f"Migrated legacy schedule type '{old_type}' to '{new_type}' for job {schedule_id}.")
                        self._update_schedule_config_in_db(schedule_id, data)
            return schedules
        except Exception as e:
            logging.error(f"SCHEDULER: Error loading schedules from database: {e}", exc_info=True)
            return {}

    def _update_schedule_config_in_db(self, schedule_id, schedule_data):
        try:
            conn = database.get_db_connection()
            config_payload = {"preset_name": schedule_data.get("preset_name"), "blocks": schedule_data.get("blocks"), "quick_playlist_data": schedule_data.get("quick_playlist_data"), "schedule_details": schedule_data.get("schedule_details")}
            conn.execute("UPDATE schedules SET config_data = ? WHERE id = ?", (json.dumps(config_payload), schedule_id))
            conn.commit()
            conn.close()
        except Exception as e:
            logging.error(f"Failed to update schedule config in DB for {schedule_id}: {e}", exc_info=True)

    def run_schedule_now(self, schedule_id: str) -> Optional[Dict]:
        if not (schedule_data := self.schedules.get(schedule_id)): return None
        result = run_playlist_job(**schedule_data)
        last_run_info = {"timestamp": datetime.now().isoformat(), "status": result.get("status", "error"), "log": result.get("log", ["An unknown error occurred."])}
        self._update_schedule_last_run(schedule_id, last_run_info)
        return {"status": "ok", "log": [f"Job '{schedule_id}' triggered and completed."]}

    def start(self):
        # Add a recurring job to refresh the cache every N minutes, based on the .env file.
        self.scheduler.add_job(
            func=refresh_cache,
            trigger='interval',
            minutes=app_state.CACHE_REFRESH_MINUTES, # Use the variable from app_state
            id='cache_refresh_job',
            name='Refresh Library Data Cache',
            replace_existing=True
        )

        # Load and start existing playlist schedule jobs
        self.schedules = self._load_schedules()
        for schedule_id, schedule_data in self.schedules.items():
            if 'crontab' in schedule_data:
                self.scheduler.add_job(func=scheduled_job_wrapper, trigger=CronTrigger.from_crontab(schedule_data['crontab']), kwargs=schedule_data, id=schedule_id, name=schedule_data.get('playlist_name', 'Unnamed Schedule'), replace_existing=True)

        if not self.scheduler.running:
            self.scheduler.start()

        job_count = len(self.schedules)
        total_jobs = len(self.scheduler.get_jobs())
        logging.info(f"Scheduler started with {job_count} user schedule(s) and {total_jobs - job_count} system job(s).")


    def add_schedule(self, schedule_data: Dict) -> str:
        schedule_id = str(uuid.uuid4())
        schedule_data['id'] = schedule_id
        try:
            conn = database.get_db_connection()
            config_payload = {"preset_name": schedule_data.get("preset_name"), "blocks": schedule_data.get("blocks"), "quick_playlist_data": schedule_data.get("quick_playlist_data"), "schedule_details": schedule_data.get("schedule_details")}
            conn.execute("INSERT INTO schedules (id, playlist_name, user_id, job_type, crontab, config_data) VALUES (?, ?, ?, ?, ?, ?)", (schedule_id, schedule_data.get("playlist_name"), schedule_data.get("user_id"), schedule_data.get("job_type"), schedule_data.get("crontab"), json.dumps(config_payload)))
            conn.commit()
            conn.close()
        except Exception as e:
            logging.error(f"Failed to save schedule {schedule_id} to database: {e}", exc_info=True)
            return None
        self.schedules[schedule_id] = schedule_data
        self.scheduler.add_job(func=scheduled_job_wrapper, trigger=CronTrigger.from_crontab(schedule_data['crontab']), kwargs=schedule_data, id=schedule_id, name=schedule_data.get('playlist_name', 'Unnamed Schedule'))
        return schedule_id

    def remove_schedule(self, schedule_id: str):
        if schedule_id in self.schedules:
            try:
                self.scheduler.remove_job(schedule_id)
            except JobLookupError:
                logging.warning(f"SCHEDULER: Job {schedule_id} not found, removing from storage anyway.")
            del self.schedules[schedule_id]
            try:
                conn = database.get_db_connection()
                conn.execute("DELETE FROM schedules WHERE id = ?", (schedule_id,))
                conn.commit()
                conn.close()
            except Exception as e:
                 logging.error(f"Failed to delete schedule {schedule_id} from database: {e}", exc_info=True)

    def get_all_schedules(self) -> List[Dict]:
        if not self.schedules and self.scheduler.running:
             self.schedules = self._load_schedules()
        return list(self.schedules.values())

scheduler_manager = Scheduler()