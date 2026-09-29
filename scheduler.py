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
from app.cache import refresh_all_caches
import app_state
import database
from routers.dependencies import get_auth_data
from app.logger import get_logger

logger = get_logger("MixerBee.Scheduler")

import logging
logging.getLogger('apscheduler').setLevel(logging.INFO if app_state.VERBOSE_LOGGING else logging.WARNING)

from quick_playlist_registry import QUICK_PLAYLIST_MAP
LEGACY_TYPE_MAP = {"continue_watching": "next_up", "forgotten_favorites": "from_the_vault"}

def run_playlist_job(**schedule_data) -> Dict:
    if "schedule_data" in schedule_data and isinstance(schedule_data["schedule_data"], dict):
        nested = schedule_data.pop("schedule_data")
        schedule_data = {**nested, **schedule_data}

    schedule_id = schedule_data.get("id") or schedule_data.get("schedule_id")
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
        connection_id = schedule_data.get("connection_id")
        if not connection_id:
            raise ValueError("Schedule has no assigned connection. Recreate it under the intended account.")
        # Policy first, before the media server is contacted: a suspended enrichment run
        # should cost nothing and must not report a connection error. The schedule and its
        # enabled flag are left alone, so no failure notification is produced and the next
        # occurrence is normal once AI is turned back on.
        if job_type == "enrichment":
            from app.ai_policy import generative_available
            if not generative_available(connection_id):
                msg = (f"Enrichment job skipped for connection {connection_id}: AI features are "
                       "unavailable for this account. The schedule is suspended, not deleted.")
                logger.info(msg)
                return {"status": "ok", "skipped": True, "suspended": True, "log": [msg]}

        media = schedule_data.get("media")
        if not media:
            auth_data = get_auth_data(connection_id)
            media = auth_data["media"].require_user(user_id)


        if job_type == "enrichment":
            from app.ai.enrichment_manager import enrichment_guard
            enrich_data = schedule_data.get("enrichment_data", {})
            batch_size = enrich_data.get("batch_size", 15)
            timeout = enrich_data.get("timeout", 120)

            with enrichment_guard(connection_id) as acquired:
                if not acquired:
                    msg = f"Enrichment job skipped for connection {connection_id}: another enrichment process is currently running."
                    logger.warning(msg)
                    return {"status": "ok", "skipped": True, "log": [msg]}

                from app.ai import process_enrichment_queue
                result = process_enrichment_queue(batch_size=batch_size, timeout=timeout, media=media)
            
        else:
            import preset_manager as pm
            from routers.builder import _get_random_movie_block, _get_random_tv_block


            if job_type == "builder":
                blocks = schedule_data.get("blocks")
                preset_id = schedule_data.get("preset_id")
                preset_name = schedule_data.get("preset_name")
                mix_options = schedule_data.get("mix_options")

                if not blocks and preset_id:
                    record = pm.preset_manager.get_preset_by_id(preset_id, connection_id)
                    if not record:
                        msg = f"The preset assigned to job '{schedule_id}' no longer exists. Reassign the schedule."
                        logger.error(msg)
                        return {"status": "error", "log": [msg]}
                    blocks = record['data']
                    preset_name = record['name']
                    if not mix_options and record.get('mix_options'):
                        mix_options = record['mix_options']
                    logger.info("Resolved blocks for job %s from preset ID %s ('%s')", schedule_id, preset_id, preset_name)
                elif not blocks and preset_name:
                    # Compatibility for jobs created before preset IDs were introduced.
                    record = pm.preset_manager.get_preset_by_name(preset_name, connection_id)
                    if not record:
                        msg = f"Preset '{preset_name}' assigned to job '{schedule_id}' no longer exists. Reassign the schedule."
                        logger.error(msg)
                        return {"status": "error", "log": [msg]}
                    blocks = record['data']
                    if not mix_options and record.get('mix_options'):
                        mix_options = record['mix_options']
                    logger.info(f"Resolved legacy job {schedule_id} from preset '{preset_name}'")
                elif preset_id and not mix_options:
                    record = pm.preset_manager.get_preset_by_id(preset_id, connection_id)
                    if record and record.get('mix_options'):
                        mix_options = record['mix_options']

                if not blocks:
                    logger.info(f"No blocks found for job {schedule_id}.")
                    
                    potential_options = [b for b in [_get_random_movie_block(media), _get_random_tv_block(media)] if b is not None]
                    
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
                        media=media
                    )
                else:
                    trigger_src = schedule_data.get("trigger_source", "clock")
                    result = core.create_mixed_playlist(
                        user_id=user_id,
                        playlist_name=playlist_name,
                        blocks=blocks,
                        media=media,
                        mix_options=mix_options,
                        trigger_source=trigger_src,
                        schedule_id=schedule_id,
                        preset_id=preset_id
                    )

            elif job_type == "quick_playlist":
                quick_playlist_data = schedule_data.get("quick_playlist_data", {})
                quick_playlist_type = quick_playlist_data.get("quick_playlist_type")
                func_to_call = QUICK_PLAYLIST_MAP.get(quick_playlist_type)

                if not func_to_call:
                    raise ValueError(f"Unknown quick_playlist_type '{quick_playlist_type}'")

                options = dict(quick_playlist_data.get("options", {}))
                if quick_playlist_type == "album_roulette":
                    if not options.get("album_id") or options.get("album_id") == "random":
                        rand_album = core.get_random_album(media)
                        if rand_album and (rand_album.get("Id") or rand_album.get("id")):
                            options["album_id"] = rand_album.get("Id") or rand_album.get("id")
                            if playlist_name in ("New Scheduled Mix", "Scheduled Auto Playlist", "Album Roulette"):
                                playlist_name = f"Album: {rand_album.get('Name') or rand_album.get('name')}"
                        else:
                            msg = "No albums found in library for Album Roulette."
                            logger.error(msg)
                            return {"status": "error", "log": [msg]}

                result = func_to_call(user_id=user_id, playlist_name=playlist_name, media=media, log=log_messages, **options)


        final_log = result.get("log", ["No log messages returned from build process."])
        final_status = result.get("status", "error")
        logger.info(f"Job '{schedule_id}' for '{playlist_name}' completed with status: {final_status.upper()}.")

    except Exception as e:
        error_message = f"CRITICAL ERROR running job '{schedule_id}': {e}"
        logger.error(error_message, exc_info=True)
        result = {"status": "error", "log": [error_message]}

    return result

# Cap on back-to-back reruns triggered by requests that arrive while a schedule is
# Cap on back-to-back reruns triggered by requests that arrive while a schedule is
# already running, so a heavy burst of webhook events can't loop indefinitely.
MAX_RERUN_PASSES = 3

def is_automatic_run_allowed(schedule: Dict, source: str, now: Optional[datetime] = None) -> bool:
    """
    Unified policy check for whether an execution triggered by `source` is permitted.
    Manual runs ("manual") are always permitted even if paused/snoozed.
    """
    if source == "manual":
        return True
    if schedule.get("enabled", True) is False:
        return False

    snoozed_until_str = schedule.get("snoozed_until")
    if snoozed_until_str:
        try:
            from datetime import timezone
            now_dt = now or datetime.now(timezone.utc)
            if now_dt.tzinfo is None:
                now_dt = now_dt.replace(tzinfo=timezone.utc)
            snooze_dt = datetime.fromisoformat(snoozed_until_str.replace("Z", "+00:00"))
            if snooze_dt.tzinfo is None:
                snooze_dt = snooze_dt.replace(tzinfo=timezone.utc)
            if now_dt < snooze_dt:
                return False
        except Exception:
            pass

    trigger_sources = schedule.get("trigger_sources")
    if trigger_sources is not None and isinstance(trigger_sources, list):
        if source not in trigger_sources:
            return False

    return True

def _run_once_and_record(schedule_data: Dict, schedule_id: Optional[str]):
    result = run_playlist_job(**schedule_data)
    if schedule_id:
        last_run_info = {
            "timestamp": datetime.now().isoformat(),
            "status": result.get("status", "error"),
            "log": result.get("log", ["An unknown error occurred."])
        }
        scheduler_manager._update_schedule_last_run(schedule_id, last_run_info)

def _schedule_exists_in_db(schedule_id: str) -> bool:
    """Authoritative existence check for a schedule about to run.

    APScheduler holds its jobs in memory, and the dispatched kwargs are a snapshot
    taken when the job was added. Neither notices a schedule deleted from the database
    (directly, or by a backup restore) once a run has already been handed to a pool
    thread, so the run must confirm its schedule is still real before building.
    """
    try:
        with database.get_db_connection() as conn:
            row = conn.execute("SELECT 1 FROM schedules WHERE id = ?", (schedule_id,)).fetchone()
        return row is not None
    except Exception as e:
        # A database problem is not evidence the schedule was deleted; let the run proceed.
        logger.warning("Could not verify schedule %s before running: %s", schedule_id, e)
        return True


def _cancel_orphaned_jobs(schedule_id: str):
    """Drop APScheduler jobs left behind for a schedule that no longer exists."""
    for job_id in (schedule_id, f"run_{schedule_id}"):
        try:
            scheduler_manager.scheduler.remove_job(job_id)
            logger.info("Removed orphaned job %s for deleted schedule %s", job_id, schedule_id)
        except JobLookupError:
            pass
        except Exception:
            pass


def scheduled_job_wrapper(**schedule_data):
    schedule_id = schedule_data.get("id")
    source = schedule_data.get("trigger_source", "clock")

    # Cron runs, webhook-triggered runs, and manual "Run Now" runs all funnel through
    # here, so guarding on the schedule id here is enough to keep any two runs of the
    # same schedule from executing (and clobbering create_playlist) at the same time.
    if not schedule_id:
        logger.warning("scheduled_job_wrapper received schedule data with no 'id'; running unguarded.")
        _run_once_and_record(schedule_data, None)
        return

    if not _schedule_exists_in_db(schedule_id):
        logger.warning(
            "Skipping run for schedule '%s': it no longer exists in the database.", schedule_id
        )
        scheduler_manager.schedules.pop(schedule_id, None)
        _cancel_orphaned_jobs(schedule_id)
        return

    # Execution-time policy recheck:
    current_schedule = scheduler_manager.schedules.get(schedule_id, schedule_data)
    if not is_automatic_run_allowed(current_schedule, source):
        logger.info(
            f"Execution skipped for schedule '{schedule_id}': automatic run not allowed for source '{source}' "
            f"(enabled={current_schedule.get('enabled', True)}, snoozed_until={current_schedule.get('snoozed_until')})."
        )
        return

    lock = scheduler_manager._get_schedule_lock(schedule_id)
    if not lock.acquire(blocking=False):
        scheduler_manager._mark_rerun_pending(schedule_id)
        logger.info(f"Schedule '{schedule_id}' is already running; queued a rerun instead of overlapping.")
        return

    try:
        current_data = schedule_data
        for pass_num in range(1, MAX_RERUN_PASSES + 1):
            if pass_num > 1:
                if not _schedule_exists_in_db(schedule_id):
                    logger.warning(
                        "Aborting pending rerun for '%s': schedule was deleted mid-run.", schedule_id
                    )
                    break
                # Recheck policy before queued rerun pass
                current_data = scheduler_manager.schedules.get(schedule_id, current_data)
                if not is_automatic_run_allowed(current_data, source):
                    logger.info(f"Aborting pending rerun for '{schedule_id}': schedule state changed to paused/snoozed.")
                    break

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


def vibe_index_catchup_job():
    """Retry any vibe index that has not succeeded in this process.

    A media server that was unreachable at startup used to leave its vibe index
    unbuilt until a restart, because indexing was startup-only work.

    This runs as its own APScheduler job rather than inside the cache refresh:
    max_instances defaults to 1 per job, so an initial index of a large library --
    minutes of embedding -- would otherwise make every cache refresh fire in that
    window be rejected as "maximum number of running instances reached".
    """
    try:
        from app.ai.vector_store import connection_needs_index, ensure_library_indexed
        from connections import all_media_clients
    except Exception as e:
        logger.warning("Skipping semantic index catch-up: %s", e)
        return

    for media in all_media_clients():
        try:
            # No provider check: this index serves Echo blocks and similarity search on
            # every usable connection, configured for AI or not.
            if connection_needs_index(media.connection.id):
                logger.info("Retrying vibe index for connection %s.", media.connection.id)
                ensure_library_indexed(media.user_id, media)
        except Exception as e:
            logger.warning("Vibe index retry failed for connection %s: %s", media.connection.id, e)


class Scheduler:
    def __init__(self):
        # APScheduler's default misfire_grace_time is 1 second, which silently drops
        # any fire that had to wait longer than that -- e.g. a cron that came due while
        # the container was stopped or the host asleep, or while the executor pool was
        # busy with a long build. coalesce collapses a backlog into a single catch-up run.
        self.scheduler = BackgroundScheduler(
            daemon=True,
            job_defaults={'misfire_grace_time': 300, 'coalesce': True}
        )
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

    @staticmethod
    def _bind_legacy_preset(schedule_data: Dict):
        """Upgrade internal callers that still submit a preset name without its ID."""
        if schedule_data.get('job_type') not in ('builder', 'preset') or schedule_data.get('blocks'):
            schedule_data['preset_id'] = None
            schedule_data['preset_name'] = None
            return schedule_data
        if (not schedule_data.get('preset_id') and schedule_data.get('preset_name')
                and schedule_data.get('connection_id')):
            import preset_manager as pm
            record = pm.preset_manager.get_preset_by_name(
                schedule_data['preset_name'], schedule_data['connection_id']
            )
            if record:
                schedule_data['preset_id'] = record['id']
                schedule_data['preset_name'] = record['name']
        return schedule_data

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
                rows = conn.execute('''SELECT s.id, s.playlist_name, s.user_id, s.job_type, s.crontab,
                    s.config_data, s.last_run, s.connection_id, s.preset_id,
                    p.name AS current_preset_name
                    FROM schedules s LEFT JOIN connection_presets p ON p.id=s.preset_id''').fetchall()

            for row in rows:
                schedule_data = dict(row)
                current_preset_name = schedule_data.pop('current_preset_name')
                config_data = json.loads(row['config_data']) if row['config_data'] else {}
                last_run = json.loads(row['last_run']) if row['last_run'] else None
                config_data.pop("connection_id", None)
                config_data.pop("preset_id", None)
                schedule_data.update(config_data)
                if schedule_data.get('preset_id') and current_preset_name:
                    schedule_data['preset_name'] = current_preset_name
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
        except Exception:
            # Callers must distinguish "no schedules" from "could not read them":
            # treating a failed read as an empty table tears down every live job.
            logger.exception("Error loading schedules from database")
            raise

    def _update_schedule_config_in_db(self, schedule_id, schedule_data):
        try:
            with database.get_db_connection() as conn:
                config_payload = {
                    "preset_name": schedule_data.get("preset_name"),
                    "blocks": schedule_data.get("blocks"),
                    "quick_playlist_data": schedule_data.get("quick_playlist_data"),
                    "enrichment_data": schedule_data.get("enrichment_data"),
                    "schedule_details": schedule_data.get("schedule_details"),
                    "create_as_collection": schedule_data.get("create_as_collection", False),
                    "mix_options": schedule_data.get("mix_options"),
                    "enabled": schedule_data.get("enabled", True),
                    "snoozed_until": schedule_data.get("snoozed_until"),
                    "trigger_sources": schedule_data.get("trigger_sources", ["clock", "watch", "library"]),
                    "timezone": schedule_data.get("timezone"),
                }
                conn.execute("UPDATE schedules SET config_data = ? WHERE id = ?", (json.dumps(config_payload), schedule_id))
                conn.commit()
        except Exception as e:
            logger.error(f"Failed to update schedule config in DB for {schedule_id}: {e}", exc_info=True)

    def enqueue_schedule_run(self, schedule_id: str, source: str = "clock") -> Optional[Dict]:
        if not (schedule_data := self.schedules.get(schedule_id)):
            return None

        if not is_automatic_run_allowed(schedule_data, source):
            logger.info(f"Skipping enqueue for schedule '{schedule_id}': source '{source}' not allowed.")
            return {"status": "skipped", "reason": "not_allowed"}

        job_id = f"run_{schedule_id}"
        job_data = dict(schedule_data)
        job_data["trigger_source"] = source

        try:
            self.scheduler.add_job(
                func=scheduled_job_wrapper,
                trigger='date',
                run_date=datetime.now(),
                kwargs=job_data,
                id=job_id,
                name=f"{source.capitalize()} Run: {schedule_data.get('playlist_name', 'Unnamed Schedule')}",
                replace_existing=True,
                misfire_grace_time=300
            )

            logger.info(f"Successfully queued background run ({source}) for schedule {schedule_id}")
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

    def run_schedule_now(self, schedule_id: str, source: Optional[str] = None) -> Optional[Dict]:
        if source is None:
            try:
                from routers.webhooks import get_current_webhook_category
                webhook_cat = get_current_webhook_category()
                source = webhook_cat if webhook_cat else "manual"
            except Exception:
                source = "manual"
        return self.enqueue_schedule_run(schedule_id, source=source)

    def pause_schedule(self, schedule_id: str) -> bool:
        if schedule_id not in self.schedules:
            return False
        sched = self.schedules[schedule_id]
        sched["enabled"] = False
        self._update_schedule_config_in_db(schedule_id, sched)
        logger.info(f"Paused schedule {schedule_id}")
        return True

    def resume_schedule(self, schedule_id: str) -> bool:
        if schedule_id not in self.schedules:
            return False
        sched = self.schedules[schedule_id]
        sched["enabled"] = True
        sched["snoozed_until"] = None
        self._update_schedule_config_in_db(schedule_id, sched)
        logger.info(f"Resumed schedule {schedule_id}")
        return True

    def snooze_schedule(self, schedule_id: str, minutes: Optional[int] = 60, until: Optional[str] = None) -> bool:
        if schedule_id not in self.schedules:
            return False
        sched = self.schedules[schedule_id]
        from datetime import timezone, timedelta
        if until:
            snooze_until_iso = until
        else:
            mins = minutes if (minutes and minutes > 0) else 60
            snooze_until_iso = (datetime.now(timezone.utc) + timedelta(minutes=mins)).isoformat()
        sched["snoozed_until"] = snooze_until_iso
        self._update_schedule_config_in_db(schedule_id, sched)
        logger.info(f"Snoozed schedule {schedule_id} until {snooze_until_iso}")
        return True

    def _install_job(self, schedule_id: str, schedule_data: Dict) -> bool:
        """Add or replace the APScheduler job for one schedule.

        Returns True when the schedule is now scheduled. A schedule with no trigger or
        no verified connection is left inactive, and any job it previously had is
        removed so a stale trigger cannot keep firing.
        """
        trigger = self._get_trigger(schedule_data)
        if not schedule_data.get("connection_id"):
            logger.warning("Schedule %s has no verified connection; leaving it inactive.", schedule_id)
        if trigger and schedule_data.get("connection_id"):
            self.scheduler.add_job(
                func=scheduled_job_wrapper,
                trigger=trigger,
                kwargs=schedule_data,
                id=schedule_id,
                name=schedule_data.get('playlist_name', 'Unnamed Schedule'),
                replace_existing=True
            )
            return True

        try:
            self.scheduler.remove_job(schedule_id)
        except JobLookupError:
            pass
        return False

    def reload_schedules(self) -> Dict[str, Dict]:
        """Re-read every schedule from the database and resync APScheduler to match.

        _load_schedules() is a pure read: on its own it changes neither self.schedules
        nor the live jobs. A backup restore rewrites the schedules table underneath a
        running scheduler, so without this resync deleted schedules keep their in-memory
        jobs and restored ones never get a job until the process restarts.
        """
        try:
            new_schedules = self._load_schedules()
        except Exception:
            logger.error(
                "Schedule reload aborted; keeping the %d schedule(s) already loaded.",
                len(self.schedules)
            )
            return self.schedules

        previous_ids = set(self.schedules)
        self.schedules = new_schedules

        for stale_id in previous_ids - set(new_schedules):
            for job_id in (stale_id, f"run_{stale_id}"):
                try:
                    self.scheduler.remove_job(job_id)
                except JobLookupError:
                    pass
            with self._schedule_locks_guard:
                self._schedule_locks.pop(stale_id, None)
                self._rerun_pending.pop(stale_id, None)
            logger.info("Reload dropped schedule %s and its jobs.", stale_id)

        active = 0
        for schedule_id, schedule_data in new_schedules.items():
            if self._install_job(schedule_id, schedule_data):
                active += 1

        logger.info(
            "Reloaded %d schedule(s) from the database (%d active, %d removed).",
            len(new_schedules), active, len(previous_ids - set(new_schedules))
        )
        return new_schedules

    def start(self):
        self.scheduler.add_job(
            func=refresh_all_caches,
            trigger='interval',
            minutes=app_state.CACHE_REFRESH_MINUTES,
            id='cache_refresh_job',
            name='Refresh Library Data Cache',
            replace_existing=True
        )

        self.scheduler.add_job(
            func=vibe_index_catchup_job,
            trigger='interval',
            minutes=app_state.CACHE_REFRESH_MINUTES,
            id='vibe_index_catchup_job',
            name='Retry Unbuilt Vibe Indexes',
            replace_existing=True
        )

        try:
            self.schedules = self._load_schedules()
        except Exception:
            # Boot must not fail on an unreadable schedules table. get_all_schedules()
            # retries the read on the next API call.
            logger.error("Starting with no schedules loaded: the table could not be read.")
            self.schedules = {}

        from datetime import timezone
        now_utc = datetime.now(timezone.utc)

        for schedule_id, schedule_data in self.schedules.items():
            # Startup reconciliation: check if snooze has expired
            snoozed_until = schedule_data.get("snoozed_until")
            if snoozed_until:
                try:
                    snooze_dt = datetime.fromisoformat(snoozed_until.replace("Z", "+00:00"))
                    if snooze_dt.tzinfo is None:
                        snooze_dt = snooze_dt.replace(tzinfo=timezone.utc)
                    if now_utc >= snooze_dt:
                        schedule_data["snoozed_until"] = None
                        self._update_schedule_config_in_db(schedule_id, schedule_data)
                        logger.info(f"Reconciled expired snooze for schedule {schedule_id}.")
                except Exception:
                    pass

            self._install_job(schedule_id, schedule_data)

        if not self.scheduler.running:
            self.scheduler.start()

        job_count = sum(bool(s.get("connection_id")) for s in self.schedules.values())
        total_jobs = len(self.scheduler.get_jobs())
        logger.info(f"Scheduler started with {job_count} user schedule(s) and {total_jobs - job_count} system job(s).")


    def add_schedule(self, schedule_data: Dict) -> str:
        schedule_id = str(uuid.uuid4())
        schedule_data['id'] = schedule_id
        if not schedule_data.get('connection_id'):
            raise ValueError('A schedule requires a saved connection.')
        self._bind_legacy_preset(schedule_data)
        try:
            with database.get_db_connection() as conn:
                config_payload = {
                    "preset_name": schedule_data.get("preset_name"),
                    "blocks": schedule_data.get("blocks"),
                    "quick_playlist_data": schedule_data.get("quick_playlist_data"),
                    "enrichment_data": schedule_data.get("enrichment_data"),
                    "schedule_details": schedule_data.get("schedule_details"),
                    "create_as_collection": schedule_data.get("create_as_collection", False),
                    "mix_options": schedule_data.get("mix_options"),
                    "enabled": schedule_data.get("enabled", True),
                    "snoozed_until": schedule_data.get("snoozed_until"),
                    "trigger_sources": schedule_data.get("trigger_sources", ["clock", "watch", "library"]),
                    "timezone": schedule_data.get("timezone"),
                }
                conn.execute(
                    "INSERT INTO schedules (id, playlist_name, user_id, job_type, crontab, config_data, connection_id, preset_id) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                    (schedule_id, schedule_data.get("playlist_name"), schedule_data.get("user_id"), schedule_data.get("job_type"), schedule_data.get("crontab", ""), json.dumps(config_payload), schedule_data["connection_id"], schedule_data.get("preset_id"))
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
        if schedule_data.get("connection_id") != self.schedules[schedule_id].get("connection_id"):
            return False
        self._bind_legacy_preset(schedule_data)
        try:
            with database.get_db_connection() as conn:
                config_payload = {
                    "preset_name": schedule_data.get("preset_name"),
                    "blocks": schedule_data.get("blocks"),
                    "quick_playlist_data": schedule_data.get("quick_playlist_data"),
                    "enrichment_data": schedule_data.get("enrichment_data"),
                    "schedule_details": schedule_data.get("schedule_details"),
                    "create_as_collection": schedule_data.get("create_as_collection", False),
                    "mix_options": schedule_data.get("mix_options"),
                    "enabled": schedule_data.get("enabled", True),
                    "snoozed_until": schedule_data.get("snoozed_until"),
                    "trigger_sources": schedule_data.get("trigger_sources", ["clock", "watch", "library"]),
                    "timezone": schedule_data.get("timezone"),
                }
                conn.execute(
                    """
                    UPDATE schedules
                    SET playlist_name = ?, user_id = ?, job_type = ?, crontab = ?, config_data = ?, preset_id = ?
                    WHERE id = ?
                    """,
                    (
                        schedule_data.get("playlist_name"),
                        schedule_data.get("user_id"),
                        schedule_data.get("job_type"),
                        schedule_data.get("crontab", ""),
                        json.dumps(config_payload),
                        schedule_data.get("preset_id"),
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
            try:
                self.schedules = self._load_schedules()
            except Exception:
                logger.error("Could not load schedules for this request.")
        return list(self.schedules.values())

scheduler_manager = Scheduler()
