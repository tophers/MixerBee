import json
import logging
import uuid
from pathlib import Path
from typing import Dict, List

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.jobstores.base import JobLookupError

import mixerbee_core as core

# Configure logging for the scheduler
logging.basicConfig()
logging.getLogger('apscheduler').setLevel(logging.INFO)

SCHEDULES_FILE = Path(__file__).parent / "schedules.json"

def run_playlist_job(user_id: str, playlist_name: str, blocks: List[Dict]):
    """The function that is called by the scheduler to build a playlist."""
    print(f"SCHEDULER: Running job for playlist '{playlist_name}' for user {user_id}")
    result = {}
    try:
        # We need to get a fresh token
        _, token = core.authenticate(core.EMBY_USER, core.EMBY_PASS)
        hdr = core.auth_headers(token, user_id=user_id)

        # Call the core function and capture its return value
        result = core.create_mixed_playlist(
            user_id=user_id,
            playlist_name=playlist_name,
            blocks=blocks,
            hdr=hdr
        )
        
        if result.get("status") == "ok":
            print(f"SCHEDULER: Job for '{playlist_name}' completed with status: OK.")
        else:
            print(f"SCHEDULER: Job for '{playlist_name}' completed with status: {result.get('status', 'unknown_error')}.")
        
        print("--- Job Details ---")
        for line in result.get("log", ["No log messages returned."]):
            print(f"  > {line}")
        print("--- End of Job ---")

    except Exception as e:
        print(f"SCHEDULER: CRITICAL ERROR running job for playlist '{playlist_name}': {e}")


class Scheduler:
    def __init__(self):
        self.scheduler = BackgroundScheduler(daemon=True)
        self.schedules = self._load_schedules()

    def _load_schedules(self) -> Dict[str, Dict]:
        """Loads schedule definitions from the JSON file."""
        if not SCHEDULES_FILE.exists():
            return {}
        with open(SCHEDULES_FILE, 'r') as f:
            return json.load(f)

    def _save_schedules(self):
        """Saves the current schedule definitions to the JSON file."""
        with open(SCHEDULES_FILE, 'w') as f:
            json.dump(self.schedules, f, indent=4)

    def start(self):
        """Starts the scheduler and re-adds all saved jobs."""
        for schedule_id, schedule_data in self.schedules.items():
            if 'crontab' in schedule_data:
                self.scheduler.add_job(
                    func=run_playlist_job,
                    trigger=CronTrigger.from_crontab(schedule_data['crontab']),
                    args=[schedule_data['user_id'], schedule_data['playlist_name'], schedule_data['blocks']],
                    id=schedule_id,
                    name=schedule_data['playlist_name'],
                    replace_existing=True
                )
        self.scheduler.start()

    def add_schedule(self, schedule_data: Dict) -> str:
        """Adds a new schedule to the scheduler and saves it."""
        schedule_id = str(uuid.uuid4())
        self.schedules[schedule_id] = schedule_data
        self.scheduler.add_job(
            func=run_playlist_job,
            trigger=CronTrigger.from_crontab(schedule_data['crontab']),
            args=[schedule_data['user_id'], schedule_data['playlist_name'], schedule_data['blocks']],
            id=schedule_id,
            name=schedule_data['playlist_name']
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
        return [{"id": sid, **sdata} for sid, sdata in self.schedules.items()]


scheduler_manager = Scheduler()