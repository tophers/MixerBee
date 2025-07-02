import json
import logging
import uuid
from pathlib import Path
from typing import Dict, List
from datetime import datetime
import threading

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.jobstores.base import JobLookupError

import app as core

# Configure logging for the scheduler
logging.basicConfig()
logging.getLogger('apscheduler').setLevel(logging.INFO)

SCHEDULES_FILE = Path(__file__).parent / "schedules.json"
_schedules_lock = threading.Lock() # To prevent race conditions when updating the file


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

def run_playlist_job(**schedule_data):
    """The function that is called by the scheduler to build a playlist."""
    schedule_id = schedule_data.get("id")
    user_id = schedule_data.get("user_id")
    playlist_name = schedule_data.get("playlist_name")
    blocks = schedule_data.get("blocks")
    
    print(f"SCHEDULER: Running job '{schedule_id}' for playlist '{playlist_name}' for user {user_id}")
    result = {}
    
    try:
        # We need to get a fresh token
        _, token = core.authenticate(core.EMBY_USER, core.EMBY_PASS)
        hdr = core.auth_headers(token, user_id=user_id)

        result = core.create_mixed_playlist(
            user_id=user_id,
            playlist_name=playlist_name,
            blocks=blocks,
            hdr=hdr
        )
        
        if result.get("status") == "ok":
            print(f"SCHEDULER: Job '{schedule_id}' for '{playlist_name}' completed with status: OK.")
        else:
            print(f"SCHEDULER: Job '{schedule_id}' for '{playlist_name}' completed with status: {result.get('status', 'unknown_error')}.")
            print("--- Job Details ---")
            for line in result.get("log", ["No log messages returned."]):
                print(f"  > {line}")
            print("--- End of Job ---")

    except Exception as e:
        error_message = f"CRITICAL ERROR running job '{schedule_id}' for playlist '{playlist_name}': {e}"
        print(f"SCHEDULER: {error_message}")
        result = {"status": "error", "log": [error_message]}

    finally:
        # Always record the outcome of the run
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
                    return json.load(f)
            except (json.JSONDecodeError, IOError) as e:
                print(f"SCHEDULER: Error loading schedules file: {e}. Starting fresh.")
                return {}

    def _save_schedules(self):
        """Saves the current schedule definitions to the JSON file."""
        with _schedules_lock:
            with open(SCHEDULES_FILE, 'w') as f:
                json.dump(self.schedules, f, indent=4)

    def start(self):
        """Starts the scheduler and re-adds all saved jobs."""
        for schedule_id, schedule_data in self.schedules.items():
            if 'crontab' in schedule_data:
                # Pass the full schedule data, including its own ID, to the job
                job_kwargs = schedule_data.copy()
                job_kwargs['id'] = schedule_id
                
                self.scheduler.add_job(
                    func=run_playlist_job,
                    trigger=CronTrigger.from_crontab(schedule_data['crontab']),
                    kwargs=job_kwargs,
                    id=schedule_id,
                    name=schedule_data.get('playlist_name', 'Unnamed Schedule'),
                    replace_existing=True
                )
        self.scheduler.start()

    def add_schedule(self, schedule_data: Dict) -> str:
        """Adds a new schedule to the scheduler and saves it."""
        schedule_id = str(uuid.uuid4())
        
        job_kwargs = schedule_data.copy()
        job_kwargs['id'] = schedule_id

        self.schedules[schedule_id] = schedule_data

        self.scheduler.add_job(
            func=run_playlist_job,
            trigger=CronTrigger.from_crontab(job_kwargs['crontab']),
            kwargs=job_kwargs,
            id=schedule_id,
            name=job_kwargs.get('playlist_name', 'Unnamed Schedule')
        )
        self._save_schedules()
        return schedule_id

    def remove_schedule(self, schedule_id: str):
        """Removes a schedule from the scheduler and the saved file."""
        if schedule_id in self.schedules:
            try:
                self.scheduler.remove_job(schedule_id)
            except JobLookupError:
                print(f"SCHEDULER: Job {schedule_id} not found in running scheduler, removing from storage.")
                pass

            del self.schedules[schedule_id]
            self._save_schedules()

    def get_all_schedules(self) -> List[Dict]:
        """Returns a list of all saved schedules with their IDs."""
        schedules_list = []
        # We now read from the file to get the most up-to-date info, including `last_run`
        all_schedules = self._load_schedules()
        for schedule_id, schedule_data in all_schedules.items():
            schedule_data['id'] = schedule_id
            schedules_list.append(schedule_data)
        return schedules_list


scheduler_manager = Scheduler()