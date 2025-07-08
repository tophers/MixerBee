from fastapi import APIRouter, HTTPException
from fastapi.responses import JSONResponse
from apscheduler.triggers.cron import CronTrigger

import models
import scheduler
import app_state

router = APIRouter()

@router.get("/api/schedules")
def api_get_schedules():
    if not app_state.is_configured: return []
    schedules = scheduler.scheduler_manager.get_all_schedules()
    cache_headers = {
        "Cache-Control": "no-cache, no-store, must-revalidate",
        "Pragma": "no-cache",
        "Expires": "0",
    }
    return JSONResponse(content=schedules, headers=cache_headers)

@router.post("/api/schedules")
def api_create_schedule(req: models.ScheduleRequest):
    if not app_state.is_configured: raise HTTPException(status_code=400, detail="Not configured")
    try:
        hour, minute = req.schedule_details.time.split(':')

        if req.schedule_details.frequency == "weekly":
            if not req.schedule_details.days_of_week:
                raise ValueError("days_of_week must be provided for weekly frequency.")
            days = ",".join(map(str, req.schedule_details.days_of_week))
            crontab = f"{minute} {hour} * * {days}"
        else: # Daily
            crontab = f"{minute} {hour} * * *"

        CronTrigger.from_crontab(crontab)

        schedule_data_to_save = req.dict(exclude_none=True)
        schedule_data_to_save['crontab'] = crontab

        schedule_id = scheduler.scheduler_manager.add_schedule(schedule_data_to_save)
        return {"status": "ok", "log": ["Schedule created successfully."], "id": schedule_id}

    except ValueError as e:
        raise HTTPException(status_code=400, detail=f"Invalid schedule format: {e}")

@router.post("/api/schedules/{schedule_id}/run")
def api_run_schedule_now(schedule_id: str):
    if not app_state.is_configured: raise HTTPException(status_code=400, detail="Not configured")
    result = scheduler.scheduler_manager.run_schedule_now(schedule_id)
    if not result:
        raise HTTPException(status_code=404, detail="Schedule not found.")
    return result

@router.delete("/api/schedules/{schedule_id}")
def api_delete_schedule(schedule_id: str):
    if not app_state.is_configured: raise HTTPException(status_code=400, detail="Not configured")
    scheduler.scheduler_manager.remove_schedule(schedule_id)
    return {"status": "ok", "log": ["Schedule deleted."]}