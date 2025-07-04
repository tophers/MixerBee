import json
import logging
import uuid
from pathlib import Path
from typing import Dict, List, Optional, Any
from datetime import datetime
import threading

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.jobstores.base import JobLookupError

import app as core
import app.items as items_api

# Configure logging for the scheduler
logging.basicConfig()
logging.getLogger('apscheduler').setLevel(logging.INFO)

SCHEDULES_FILE = Path(__file__).parent / "schedules.json"
_schedules_lock = threading.Lock()

QUICK_PLAYLIST_MAP = {
    "continue_watching": items_api.create_continue_watching_playlist,
    "pilot_sampler": items_api.create_pilot_sampler_playlist,
    "forgotten_favorites": items_api.create_forgotten_favorites_playlist,
}


def update_schedule_last_run(schedule_id: str, last_run_info: Dict):
    """Safely updates the last_run status for a specific schedule."""
    with _schedules_lock:
        try:
            if not SCHEDULES_FILE.exists():
                return
            schedules = json.loads(SCHEDULES_FILE.read_text())
            if schedule_id in schedules:
                schedules[schedule_id]['last_run'] = last_run_info
                SCHEDULES_FILE.write_text(json.dumps(schedules, indent=4))
        except (IOError, json.JSONDecodeError) as e:
            print(f"SCHEDULER: Error updating last run status for {schedule_id}: {e}")

def run_playlist_job(**schedule_data) -> Dict:
    """
    The function that is called to build a playlist.
    Returns a dictionary with the result status and log.
    """
    schedule_id = schedule_data.get("id")
    user_id = schedule_data.get("user_id")
    playlist_name = schedule_data.get("playlist_name")
    job_type = schedule_data.get("job_type", "builder")
    log_messages = []

    if not all([user_id, playlist_name]):
        msg = f"SCHEDULER: Job '{schedule_id}' is missing required data. Aborting."
        logging.error(msg)
        return {"status": "error", "log": [msg]}

    print(f"SCHEDULER: Running job '{schedule_id}' for playlist '{playlist_name}' (Type: {job_type}) for user {user_id}")
    result = {}

    try:
        _, token = core.authenticate(core.EMBY_USER, core.EMBY_PASS, core.EMBY_URL)
        hdr = core.auth_headers(token, user_id=user_id)

        if job_type == "builder":
            blocks = schedule_data.get("blocks", [])
            if not blocks:
                raise ValueError("Scheduled builder job has no blocks.")
            result = core.create_mixed_playlist(
                user_id=user_id, playlist_name=playlist_name, blocks=blocks, hdr=hdr, log=log_messages
            )
        elif job_type == "quick_playlist":
            quick_playlist_data = schedule_data.get("quick_playlist_data", {})
            quick_playlist_type = quick_playlist_data.get("quick_playlist_type")
            func_to_call = QUICK_PLAYLIST_MAP.get(quick_playlist_type)
            if not func_to_call:
                raise ValueError(f"Unknown quick_playlist_type '{quick_playlist_type}'")
            options = quick_playlist_data.get("options", {})
            result = func_to_call(
                user_id=user_id, playlist_name=playlist_name, hdr=hdr, log=log_messages, **options
            )
        
        final_log = result.get("log", ["No log messages."])
        final_status = result.get("status", "error")
        logging.info(f"SCHEDULER: Job '{schedule_id}' for '{playlist_name}' completed with status: {final_status.upper()}.")
        
    except Exception as e:
        error_message = f"CRITICAL ERROR running job '{schedule_id}' for playlist '{playlist_name}': {e}"
        logging.error(f"SCHEDULER: {error_message}", exc_info=True)
        result = {"status": "error", "log": [error_message]}

    return result


def scheduled_job_wrapper(**schedule_data):
    """A wrapper for APScheduler to ensure last_run is always updated for scheduled runs."""
    result = run_playlist_job(**schedule_data)
    schedule_id = schedule_data.get("id")
    if schedule_id:
        last_run_info = {
            "timestamp": datetime.now().isoformat(),
            "status": result.get("status", "error"),
            "log": result.get("log", ["An unknown error occurred."])
        }
        update_schedule_last_run(schedule_id, last_run_info)


class Scheduler:
    def __init__(self):
        self.scheduler = BackgroundScheduler(daemon=True)
        self.schedules = self._load_schedules()

    def _load_schedules(self) -> Dict[str, Dict]:
        """Loads schedule definitions from the JSON file."""
        with _schedules_lock:
            if not SCHEDULES_FILE.exists():
                return {}
            try:
                with open(SCHEDULES_FILE, 'r') as f:
                    schedules = json.load(f)
                    return schedules if isinstance(schedules, dict) else {}
            except (json.JSONDecodeError, IOError) as e:
                print(f"SCHEDULER: Error loading schedules file: {e}. Starting fresh.")
                return {}

    def _save_schedules(self):
        """Saves the current schedule definitions to the JSON file."""
        with _schedules_lock:
            with open(SCHEDULES_FILE, 'w') as f:
                json.dump(self.schedules, f, indent=4)

    def run_schedule_now(self, schedule_id: str) -> Optional[Dict]:
        """Runs a specific job immediately and updates its last_run status."""
        schedule_data = self.schedules.get(schedule_id)
        if not schedule_data:
            return None

        result = run_playlist_job(**schedule_data)

        last_run_info = {
            "timestamp": datetime.now().isoformat(),
            "status": result.get("status", "error"),
            "log": result.get("log", ["An unknown error occurred."])
        }
        update_schedule_last_run(schedule_id, last_run_info)
        
        return {"status": "ok", "log": [f"Job '{schedule_id}' triggered and completed."]}

    def start(self):
        """Starts the scheduler and re-adds all saved jobs from the JSON file."""
        for schedule_id, schedule_data in self.schedules.items():
            if 'crontab' in schedule_data:
                self.scheduler.add_job(
                    func=scheduled_job_wrapper,
                    trigger=CronTrigger.from_crontab(schedule_data['crontab']),
                    kwargs=schedule_data,
                    id=schedule_id,
                    name=schedule_data.get('playlist_name', 'Unnamed Schedule'),
                    replace_existing=True
                )
        self.scheduler.start()
        logging.info("Scheduler started with JSON-based job definitions.")

    def add_schedule(self, schedule_data: Dict) -> str:
        """Adds a new schedule to the scheduler and saves it."""
        schedule_id = str(uuid.uuid4())
        schedule_data['id'] = schedule_id

        self.schedules[schedule_id] = schedule_data

        self.scheduler.add_job(
            func=scheduled_job_wrapper,
            trigger=CronTrigger.from_crontab(schedule_data['crontab']),
            kwargs=schedule_data,
            id=schedule_id,
            name=schedule_data.get('playlist_name', 'Unnamed Schedule')
        )
        self._save_schedules()
        return schedule_id

    def remove_schedule(self, schedule_id: str):
        """Removes a schedule from the scheduler and the saved file."""
        if schedule_id in self.schedules:
            try:
                self.scheduler.remove_job(schedule_id)
            except JobLookupError:
                print(f"SCHEDULER: Job {schedule_id} not found in running scheduler, removing from storage anyway.")
                pass
            
            del self.schedules[schedule_id]
            self._save_schedules()

    def get_all_schedules(self) -> List[Dict]:
        """Returns a list of all saved schedules from the JSON file."""
        # The JSON file is the single source of truth for the UI list.
        all_schedules = self._load_schedules()
        schedules_list = []
        for schedule_id, schedule_data in all_schedules.items():
            # Ensure the schedule data has an 'id' for the frontend.
            if 'id' not in schedule_data:
                schedule_data['id'] = schedule_id
            schedules_list.append(schedule_data)
        return schedules_list


scheduler_manager = Scheduler()