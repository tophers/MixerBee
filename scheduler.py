"""
scheduler.py – Manages schedules
"""

import json
import uuid
import random
import threading
from typing import Dict, List, Optional, Any
from datetime import datetime

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger
from apscheduler.jobstores.base import JobLookupError

import app as core
import app.items as items_api
from app.cache import refresh_cache
import app_state
import database
from routers.dependencies import get_current_auth_headers
from app.logger import get_logger

logger = get_logger("MixerBee.Scheduler")

import logging
logging.getLogger('apscheduler').setLevel(logging.INFO if app_state.VERBOSE_LOGGING else logging.WARNING)

QUICK_PLAYLIST_MAP = {
    "recently_added": items_api.create_recently_added_playlist,
    "next_up": items_api.create_continue_watching_playlist,
    "pilot_sampler": items_api.create_pilot_sampler_playlist,
    "from_the_vault": items_api.create_forgotten_favorites_playlist,
    "top_community_unwatched": items_api.create_top_community_unwatched_playlist,
    "top_critic_unwatched": items_api.create_top_critic_unwatched_playlist,
}
LEGACY_TYPE_MAP = {"continue_watching": "next_up", "forgotten_favorites": "from_the_vault"}

def run_playlist_job(**schedule_data) -> Dict:
    schedule_id = schedule_data.get("id")
    user_id = schedule_data.get("user_id")
    playlist_name = schedule_data.get("playlist_name")

    raw_type = schedule_data.get("job_type", "builder")
    job_type = "builder" if raw_type == "preset" else raw_type

    log_messages = []
    if not all([user_id, playlist_name]):
        msg = f"Job '{schedule_id}' is missing required data (User or Playlist Name). Aborting."
        logger.error(msg)
        return {"status": "error", "log": [msg]}

    logger.info(f"Running job '{schedule_id}' for playlist '{playlist_name}' (Type: {job_type}) for user {user_id}")
    result = {}

    try:
        if job_type == "enrichment":
            from app.ai import process_enrichment_queue
            enrich_data = schedule_data.get("enrichment_data", {})
            batch_size = enrich_data.get("batch_size", 15)
            timeout = enrich_data.get("timeout", 120)
            
            result = process_enrichment_queue(batch_size=batch_size, timeout=timeout)
            
        else:
            import preset_manager as pm
            from routers.builder import _get_random_movie_block, _get_random_tv_block

            auth_data = get_current_auth_headers(None)
            hdr = core.auth_headers(auth_data["token"], user_id=user_id)

            if job_type == "builder":
                blocks = schedule_data.get("blocks")
                preset_name = schedule_data.get("preset_name")

                if not blocks and preset_name:
                    all_presets = pm.preset_manager.get_all_presets()
                    blocks = all_presets.get(preset_name)
                    if blocks:
                        logger.info(f"Resolved blocks for job {schedule_id} from preset '{preset_name}'")

                if not blocks:
                    logger.info(f"No blocks found for job {schedule_id}.")
                    
                    potential_options = [b for b in [_get_random_movie_block(), _get_random_tv_block()] if b is not None]
                    
                    if potential_options:
                        blocks = [random.choice(potential_options)]
                    else:
                        msg = "Could not generate a block; library appears to be empty."
                        logger.error(msg)
                        return {"status": "error", "log": [msg]}

                create_as_collection = schedule_data.get("create_as_collection", False)

                if create_as_collection:
                    if len(blocks) != 1 or blocks[0].get("type") != "movie":
                        msg = "Scheduled collections must consist of exactly one Movie block."
                        logger.error(msg)
                        return {"status": "error", "log": [msg]}

                    result = items_api.create_movie_collection(
                        user_id=user_id,
                        collection_name=playlist_name,
                        filters=blocks[0].get("filters", {}),
                        hdr=hdr
                    )
                else:
                    result = core.create_mixed_playlist(
                        user_id=user_id,
                        playlist_name=playlist_name,
                        blocks=blocks,
                        hdr=hdr
                    )

            elif job_type == "quick_playlist":
                quick_playlist_data = schedule_data.get("quick_playlist_data", {})
                quick_playlist_type = quick_playlist_data.get("quick_playlist_type")
                func_to_call = QUICK_PLAYLIST_MAP.get(quick_playlist_type)

                if not func_to_call:
                    raise ValueError(f"Unknown quick_playlist_type '{quick_playlist_type}'")

                options = quick_playlist_data.get("options", {})
                result = func_to_call(user_id=user_id, playlist_name=playlist_name, hdr=hdr, log=log_messages, **options)

        final_log = result.get("log", ["No log messages returned from build process."])
        final_status = result.get("status", "error")
        logger.info(f"Job '{schedule_id}' for '{playlist_name}' completed with status: {final_status.upper()}.")

    except Exception as e:
        error_message = f"CRITICAL ERROR running job '{schedule_id}': {e}"
        logger.error(error_message, exc_info=True)
        result = {"status": "error", "log": [error_message]}

    return result

# Cap on back-to-back reruns triggered by requests that arrive while a schedule is
# already running, so a heavy burst of webhook events can't loop indefinitely.
MAX_RERUN_PASSES = 3

def _run_once_and_record(schedule_data: Dict, schedule_id: Optional[str]):
    result = run_playlist_job(**schedule_data)
    if schedule_id:
        last_run_info = {
            "timestamp": datetime.now().isoformat(),
            "status": result.get("status", "error"),
            "log": result.get("log", ["An unknown error occurred."])
        }
        scheduler_manager._update_schedule_last_run(schedule_id, last_run_info)

def scheduled_job_wrapper(**schedule_data):
    schedule_id = schedule_data.get("id")

    # Cron runs, webhook-triggered runs, and manual "Run Now" runs all funnel through
    # here, so guarding on the schedule id here is enough to keep any two runs of the
    # same schedule from executing (and clobbering create_playlist) at the same time.
    if not schedule_id:
        logger.warning("scheduled_job_wrapper received schedule data with no 'id'; running unguarded.")
        _run_once_and_record(schedule_data, None)
        return

    lock = scheduler_manager._get_schedule_lock(schedule_id)
    if not lock.acquire(blocking=False):
        scheduler_manager._mark_rerun_pending(schedule_id)
        logger.info(f"Schedule '{schedule_id}' is already running; queued a rerun instead of overlapping.")
        return

    try:
        current_data = schedule_data
        for pass_num in range(1, MAX_RERUN_PASSES + 1):
            _run_once_and_record(current_data, schedule_id)

            if not scheduler_manager._consume_rerun_pending(schedule_id):
                break
            if pass_num == MAX_RERUN_PASSES:
                logger.warning(
                    f"Schedule '{schedule_id}' hit the {MAX_RERUN_PASSES}-pass rerun cap; "
                    "dropping the pending rerun."
                )
                break

            # Pick up any edits saved while this schedule was running instead of
            # rerunning with the (possibly now-stale) data captured at dispatch time.
            current_data = scheduler_manager.schedules.get(schedule_id, current_data)
    finally:
        lock.release()

class Scheduler:
    def __init__(self):
        self.scheduler = BackgroundScheduler(daemon=True)
        self.schedules: Dict[str, Dict] = {}
        # Per-schedule run lock + "a rerun was requested while running" flag, keyed by
        # schedule id. _schedule_locks_guard protects both dicts so concurrent first-time
        # access for the same schedule id can't create two different Lock objects.
        self._schedule_locks: Dict[str, threading.Lock] = {}
        self._rerun_pending: Dict[str, bool] = {}
        self._schedule_locks_guard = threading.Lock()

    def _get_schedule_lock(self, schedule_id: str) -> threading.Lock:
        with self._schedule_locks_guard:
            lock = self._schedule_locks.get(schedule_id)
            if lock is None:
                lock = threading.Lock()
                self._schedule_locks[schedule_id] = lock
            return lock

    def _mark_rerun_pending(self, schedule_id: str):
        with self._schedule_locks_guard:
            self._rerun_pending[schedule_id] = True

    def _consume_rerun_pending(self, schedule_id: str) -> bool:
        with self._schedule_locks_guard:
            pending = self._rerun_pending.get(schedule_id, False)
            self._rerun_pending[schedule_id] = False
        return pending

    def _get_trigger(self, schedule_data: Dict):
        details = schedule_data.get("schedule_details", {})
        frequency = details.get("frequency")
        
        if frequency == "interval":
            mins = details.get("interval_minutes", 30)
            return IntervalTrigger(minutes=mins)
        
        crontab = schedule_data.get("crontab")
        if crontab:
            return CronTrigger.from_crontab(crontab)
        
        return None

    def _update_schedule_last_run(self, schedule_id: str, last_run_info: Dict):
        """Safely updates the last_run status in both the DB and in-memory cache."""
        try:
            with database.get_db_connection() as conn:
                last_run_json = json.dumps(last_run_info)
                conn.execute("UPDATE schedules SET last_run = ? WHERE id = ?", (last_run_json, schedule_id))
                conn.commit()

            if schedule_id in self.schedules:
                self.schedules[schedule_id]['last_run'] = last_run_info

        except Exception as e:
            logger.error(f"Error updating last run status for {schedule_id} in DB: {e}", exc_info=True)

    def _load_schedules(self) -> Dict[str, Dict]:
        schedules = {}
        try:
            with database.get_db_connection() as conn:
                rows = conn.execute("SELECT id, playlist_name, user_id, job_type, crontab, config_data, last_run FROM schedules").fetchall()

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
                        logger.info(f"Migrated legacy schedule type '{old_type}' to '{new_type}' for job {schedule_id}.")
                        self._update_schedule_config_in_db(schedule_id, data)
            return schedules
        except Exception as e:
            logger.error(f"Error loading schedules from database: {e}", exc_info=True)
            return {}

    def _update_schedule_config_in_db(self, schedule_id, schedule_data):
        try:
            with database.get_db_connection() as conn:
                config_payload = {
                    "preset_name": schedule_data.get("preset_name"),
                    "blocks": schedule_data.get("blocks"),
                    "quick_playlist_data": schedule_data.get("quick_playlist_data"),
                    "enrichment_data": schedule_data.get("enrichment_data"),
                    "schedule_details": schedule_data.get("schedule_details"),
                    "create_as_collection": schedule_data.get("create_as_collection", False)
                }
                conn.execute("UPDATE schedules SET config_data = ? WHERE id = ?", (json.dumps(config_payload), schedule_id))
                conn.commit()
        except Exception as e:
            logger.error(f"Failed to update schedule config in DB for {schedule_id}: {e}", exc_info=True)

    def run_schedule_now(self, schedule_id: str) -> Optional[Dict]:
        if not (schedule_data := self.schedules.get(schedule_id)): return None

        # Stable id (not a per-call unique one) so a request that arrives while an
        # earlier one is still queued replaces it instead of stacking alongside it.
        # This only dedupes the *queued* case; the per-schedule lock in
        # scheduled_job_wrapper is what prevents two already-dispatched runs of the
        # same schedule from executing at once.
        job_id = f"run_{schedule_id}"

        try:
            self.scheduler.add_job(
                func=scheduled_job_wrapper,
                trigger='date',
                run_date=datetime.now(),
                kwargs=schedule_data,
                id=job_id,
                name=f"Manual Run: {schedule_data.get('playlist_name', 'Unnamed Schedule')}",
                replace_existing=True,
                # The default executor is a 10-worker thread pool (unconfigured/default
                # in this app); a webhook fan-out queues one of these per schedule, and
                # rebuilds can run 30-60s+ against a large library. A tight grace period
                # would let APScheduler discard a job that's merely waiting for a free
                # worker as "misfired" - silently skipping the exact rebuild this whole
                # change exists to guarantee.
                misfire_grace_time=300
            )
            
            logger.info(f"Successfully queued background run for schedule {schedule_id}")
            return {
                "status": "ok",
                "log": [f"Execution started for '{schedule_data.get('playlist_name', 'Unnamed')}'."]
            }
        except Exception as e:
            logger.error(f"Failed to queue run for {schedule_id}: {e}", exc_info=True)
            return {
                "status": "error",
                "log": [f"Failed to queue background job: {str(e)}"]
            }

    def start(self):
        self.scheduler.add_job(
            func=refresh_cache,
            trigger='interval',
            minutes=app_state.CACHE_REFRESH_MINUTES,
            id='cache_refresh_job',
            name='Refresh Library Data Cache',
            replace_existing=True
        )

        self.schedules = self._load_schedules()
        for schedule_id, schedule_data in self.schedules.items():
            trigger = self._get_trigger(schedule_data)
            if trigger:
                self.scheduler.add_job(
                    func=scheduled_job_wrapper,
                    trigger=trigger,
                    kwargs=schedule_data,
                    id=schedule_id,
                    name=schedule_data.get('playlist_name', 'Unnamed Schedule'),
                    replace_existing=True
                )

        if not self.scheduler.running:
            self.scheduler.start()

        job_count = len(self.schedules)
        total_jobs = len(self.scheduler.get_jobs())
        logger.info(f"Scheduler started with {job_count} user schedule(s) and {total_jobs - job_count} system job(s).")


    def add_schedule(self, schedule_data: Dict) -> str:
        schedule_id = str(uuid.uuid4())
        schedule_data['id'] = schedule_id
        try:
            with database.get_db_connection() as conn:
                config_payload = {
                    "preset_name": schedule_data.get("preset_name"),
                    "blocks": schedule_data.get("blocks"),
                    "quick_playlist_data": schedule_data.get("quick_playlist_data"),
                    "enrichment_data": schedule_data.get("enrichment_data"),
                    "schedule_details": schedule_data.get("schedule_details"),
                    "create_as_collection": schedule_data.get("create_as_collection", False)
                }
                conn.execute(
                    "INSERT INTO schedules (id, playlist_name, user_id, job_type, crontab, config_data) VALUES (?, ?, ?, ?, ?, ?)",
                    (schedule_id, schedule_data.get("playlist_name"), schedule_data.get("user_id"), schedule_data.get("job_type"), schedule_data.get("crontab", ""), json.dumps(config_payload))
                )
                conn.commit()
        except Exception as e:
            logger.error(f"Failed to save schedule {schedule_id} to database: {e}", exc_info=True)
            return None

        self.schedules[schedule_id] = schedule_data
        
        trigger = self._get_trigger(schedule_data)
        self.scheduler.add_job(
            func=scheduled_job_wrapper,
            trigger=trigger,
            kwargs=schedule_data,
            id=schedule_id,
            name=schedule_data.get('playlist_name', 'Unnamed Schedule')
        )
        return schedule_id

    def update_schedule(self, schedule_id: str, schedule_data: Dict) -> bool:
        if schedule_id not in self.schedules:
            logger.warning(f"Attempted to update non-existent schedule {schedule_id}")
            return False
        try:
            with database.get_db_connection() as conn:
                config_payload = {
                    "preset_name": schedule_data.get("preset_name"),
                    "blocks": schedule_data.get("blocks"),
                    "quick_playlist_data": schedule_data.get("quick_playlist_data"),
                    "enrichment_data": schedule_data.get("enrichment_data"),
                    "schedule_details": schedule_data.get("schedule_details"),
                    "create_as_collection": schedule_data.get("create_as_collection", False)
                }
                conn.execute(
                    """
                    UPDATE schedules
                    SET playlist_name = ?, user_id = ?, job_type = ?, crontab = ?, config_data = ?
                    WHERE id = ?
                    """,
                    (
                        schedule_data.get("playlist_name"),
                        schedule_data.get("user_id"),
                        schedule_data.get("job_type"),
                        schedule_data.get("crontab", ""),
                        json.dumps(config_payload),
                        schedule_id
                    )
                )
                conn.commit()

            schedule_data['id'] = schedule_id
            
            trigger = self._get_trigger(schedule_data)
            self.scheduler.add_job(
                func=scheduled_job_wrapper,
                trigger=trigger,
                kwargs=schedule_data,
                id=schedule_id,
                name=schedule_data.get('playlist_name', 'Unnamed Schedule'),
                replace_existing=True
            )

            last_run_data = self.schedules[schedule_id].get('last_run')
            self.schedules[schedule_id] = schedule_data
            if last_run_data:
                self.schedules[schedule_id]['last_run'] = last_run_data

            return True

        except Exception as e:
            logger.error(f"Failed to update schedule {schedule_id}: {e}", exc_info=True)
            return False

    def remove_schedule(self, schedule_id: str):
        if schedule_id in self.schedules:
            try:
                self.scheduler.remove_job(schedule_id)
            except JobLookupError:
                logger.warning(f"Job {schedule_id} not found, removing from storage anyway.")
            try:
                # A queued-but-not-yet-run request from run_schedule_now (manual "Run Now"
                # or a webhook fan-out) uses this deterministic id; without canceling it
                # too, it would fire against a schedule that no longer exists.
                self.scheduler.remove_job(f"run_{schedule_id}")
            except JobLookupError:
                pass
            del self.schedules[schedule_id]
            try:
                with database.get_db_connection() as conn:
                    conn.execute("DELETE FROM schedules WHERE id = ?", (schedule_id,))
                    conn.commit()
            except Exception as e:
                 logger.error(f"Failed to delete schedule {schedule_id} from database: {e}", exc_info=True)

            with self._schedule_locks_guard:
                self._schedule_locks.pop(schedule_id, None)
                self._rerun_pending.pop(schedule_id, None)

    def get_all_schedules(self) -> List[Dict]:
        if not self.schedules and self.scheduler.running:
             self.schedules = self._load_schedules()
        return list(self.schedules.values())

scheduler_manager = Scheduler()