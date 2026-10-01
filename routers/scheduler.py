"""
routers/scheduler.py – APIRouter
"""

from fastapi import APIRouter, HTTPException, Depends
from fastapi.responses import JSONResponse
from apscheduler.triggers.cron import CronTrigger

import models
import scheduler
from preset_manager import preset_manager
from app import ai_policy
from .dependencies import (get_current_auth_headers, media_for_user, require_collection_permission,
                          require_generative_ai)

router = APIRouter()


def bind_schedule_preset(schedule_data, connection_id):
    """Resolve a submitted preset to its immutable ID within this connection."""
    if schedule_data.get('job_type') not in ('builder', 'preset') or schedule_data.get('blocks'):
        schedule_data['preset_id'] = None
        schedule_data['preset_name'] = None
        return schedule_data
    preset_id = schedule_data.get('preset_id')
    preset_name = schedule_data.get('preset_name')
    record = (preset_manager.get_preset_by_id(preset_id, connection_id) if preset_id
              else preset_manager.get_preset_by_name(preset_name, connection_id) if preset_name else None)
    if (preset_id or preset_name) and not record:
        raise ValueError('The selected preset does not exist in this media connection.')
    if record:
        schedule_data['preset_id'] = record['id']
        schedule_data['preset_name'] = record['name']
    else:
        schedule_data['preset_id'] = None
        schedule_data['preset_name'] = None
    return schedule_data

@router.get("/api/schedules")
def api_get_schedules(auth_deps: dict = Depends(get_current_auth_headers)):
    schedules = [s for s in scheduler.scheduler_manager.get_all_schedules() if s.get("connection_id") == auth_deps["connection_id"]]
    # Enrichment schedules and their enabled flags are kept, never deleted. While AI is
    # unavailable they are held back from the list and reported as a count instead, so
    # the Scheduler shows no controls the account cannot use and the user does not have
    # to rebuild them after re-enabling.
    if not ai_policy.generative_available(auth_deps["connection_id"]):
        schedules = [s for s in schedules if s.get("job_type") != "enrichment"]
    # Copies, so the runtime fields never leak into the stored schedule config.
    schedules = [{**s, **scheduler.scheduler_manager.get_run_state(s.get("id"))} for s in schedules]
    cache_headers = {
        "Cache-Control": "no-cache, no-store, must-revalidate",
        "Pragma": "no-cache",
        "Expires": "0",
    }
    return JSONResponse(content=schedules, headers=cache_headers)

@router.post("/api/schedules")
def api_create_schedule(req: models.ScheduleRequest, auth_deps: dict = Depends(get_current_auth_headers)):
    try:
        crontab = ""
        if req.schedule_details.frequency == "interval":
            if not req.schedule_details.interval_minutes or req.schedule_details.interval_minutes < 1:
                raise ValueError("Interval minutes must be at least 1.")
            crontab = f"interval:{req.schedule_details.interval_minutes}"
        else:
            hour, minute = req.schedule_details.time.split(':')
            if req.schedule_details.frequency == "weekly":
                if not req.schedule_details.days_of_week:
                    raise ValueError("days_of_week must be provided for weekly frequency.")
                days = ",".join(map(str, req.schedule_details.days_of_week))
                crontab = f"{minute} {hour} * * {days}"
            else:
                crontab = f"{minute} {hour} * * *"
            
            CronTrigger.from_crontab(crontab)

        media = media_for_user(auth_deps, req.user_id)
        if req.create_as_collection:
            require_collection_permission(media)
        if req.job_type == "enrichment":
            # Creating or editing an enrichment job is setting up AI work, so it needs
            # the same policy as running it.
            require_generative_ai(auth_deps)
        if req.job_type == "quick_playlist":
            if not req.quick_playlist_data:
                raise ValueError("quick_playlist_data is required for quick_playlist job type.")
            qp_type = req.quick_playlist_data.quick_playlist_type
            if qp_type not in scheduler.QUICK_PLAYLIST_MAP:
                raise ValueError(f"Unknown or unschedulable quick playlist type: '{qp_type}'.")

        schedule_data_to_save = req.model_dump(exclude_none=True)
        schedule_data_to_save["connection_id"] = auth_deps["connection_id"]
        schedule_data_to_save['crontab'] = crontab
        bind_schedule_preset(schedule_data_to_save, auth_deps["connection_id"])

        schedule_id = scheduler.scheduler_manager.add_schedule(schedule_data_to_save)
        if not schedule_id:
            raise HTTPException(status_code=500, detail="Failed to save schedule.")
        return {"status": "ok", "log": ["Schedule created successfully."], "id": schedule_id}

    except ValueError as e:
        raise HTTPException(status_code=400, detail=f"Invalid schedule format: {e}")

@router.put("/api/schedules/{schedule_id}")
def api_update_schedule(schedule_id: str, req: models.ScheduleRequest, auth_deps: dict = Depends(get_current_auth_headers)):
    existing = scheduler.scheduler_manager.schedules.get(schedule_id)
    if not existing or existing.get("connection_id") != auth_deps["connection_id"]:
        raise HTTPException(404, "Schedule not found.")
    try:
        crontab = ""
        if req.schedule_details.frequency == "interval":
            if not req.schedule_details.interval_minutes or req.schedule_details.interval_minutes < 1:
                raise ValueError("Interval minutes must be at least 1.")
            crontab = f"interval:{req.schedule_details.interval_minutes}"
        else:
            hour, minute = req.schedule_details.time.split(':')
            if req.schedule_details.frequency == "weekly":
                if not req.schedule_details.days_of_week:
                    raise ValueError("days_of_week must be provided for weekly frequency.")
                days = ",".join(map(str, req.schedule_details.days_of_week))
                crontab = f"{minute} {hour} * * {days}"
            else:
                crontab = f"{minute} {hour} * * *"
            
            CronTrigger.from_crontab(crontab)

        media = media_for_user(auth_deps, req.user_id)
        if req.create_as_collection:
            require_collection_permission(media)
        if req.job_type == "enrichment":
            # Creating or editing an enrichment job is setting up AI work, so it needs
            # the same policy as running it.
            require_generative_ai(auth_deps)
        if req.job_type == "quick_playlist":
            if not req.quick_playlist_data:
                raise ValueError("quick_playlist_data is required for quick_playlist job type.")
            qp_type = req.quick_playlist_data.quick_playlist_type
            if qp_type not in scheduler.QUICK_PLAYLIST_MAP:
                raise ValueError(f"Unknown or unschedulable quick playlist type: '{qp_type}'.")

        schedule_data_to_save = req.model_dump(exclude_none=True)
        schedule_data_to_save["connection_id"] = auth_deps["connection_id"]
        schedule_data_to_save['crontab'] = crontab
        bind_schedule_preset(schedule_data_to_save, auth_deps["connection_id"])

        success = scheduler.scheduler_manager.update_schedule(schedule_id, schedule_data_to_save)
        if not success:
            raise HTTPException(status_code=404, detail="Schedule not found or update failed.")

        return {"status": "ok", "log": ["Schedule updated successfully."]}

    except ValueError as e:
        raise HTTPException(status_code=400, detail=f"Invalid schedule format: {e}")

@router.post("/api/schedules/{schedule_id}/run")
def api_run_schedule_now(schedule_id: str, auth_deps: dict = Depends(get_current_auth_headers)):
    existing = scheduler.scheduler_manager.schedules.get(schedule_id)
    if not existing or existing.get("connection_id") != auth_deps["connection_id"]:
        raise HTTPException(404, "Schedule not found.")
    result = scheduler.scheduler_manager.run_schedule_now(schedule_id)
    if not result:
        raise HTTPException(status_code=404, detail="Schedule not found.")
    return result

@router.delete("/api/schedules/{schedule_id}")
def api_delete_schedule(schedule_id: str, auth_deps: dict = Depends(get_current_auth_headers)):
    existing = scheduler.scheduler_manager.schedules.get(schedule_id)
    if not existing or existing.get("connection_id") != auth_deps["connection_id"]:
        raise HTTPException(404, "Schedule not found.")
    scheduler.scheduler_manager.remove_schedule(schedule_id)
    return {"status": "ok", "log": ["Schedule deleted."]}

@router.post("/api/schedules/{schedule_id}/pause")
def api_pause_schedule(schedule_id: str, auth_deps: dict = Depends(get_current_auth_headers)):
    existing = scheduler.scheduler_manager.schedules.get(schedule_id)
    if not existing or existing.get("connection_id") != auth_deps["connection_id"]:
        raise HTTPException(404, "Schedule not found.")
    success = scheduler.scheduler_manager.pause_schedule(schedule_id)
    if not success:
        raise HTTPException(500, "Failed to pause schedule.")
    return {"status": "ok", "message": "Schedule paused."}

@router.post("/api/schedules/{schedule_id}/resume")
def api_resume_schedule(schedule_id: str, auth_deps: dict = Depends(get_current_auth_headers)):
    existing = scheduler.scheduler_manager.schedules.get(schedule_id)
    if not existing or existing.get("connection_id") != auth_deps["connection_id"]:
        raise HTTPException(404, "Schedule not found.")
    success = scheduler.scheduler_manager.resume_schedule(schedule_id)
    if not success:
        raise HTTPException(500, "Failed to resume schedule.")
    return {"status": "ok", "message": "Schedule resumed."}

@router.post("/api/schedules/{schedule_id}/snooze")
def api_snooze_schedule(schedule_id: str, req: models.SnoozeRequest, auth_deps: dict = Depends(get_current_auth_headers)):
    existing = scheduler.scheduler_manager.schedules.get(schedule_id)
    if not existing or existing.get("connection_id") != auth_deps["connection_id"]:
        raise HTTPException(404, "Schedule not found.")
    success = scheduler.scheduler_manager.snooze_schedule(schedule_id, minutes=req.minutes, until=req.until)
    if not success:
        raise HTTPException(500, "Failed to snooze schedule.")
    return {"status": "ok", "message": "Schedule snoozed."}

