"""
routers/webhooks.py – APIRouter
"""

import logging
from datetime import datetime, timedelta
from fastapi import APIRouter, Request
from typing import Dict, Any

import app_state
from scheduler import scheduler_manager

router = APIRouter()

def trigger_relevant_schedules(user_id: str = None):
    """
    Background worker that iterates through existing schedules and runs them.
    If a user_id is provided by the webhook, it only updates that user's playlists.
    """
    if not app_state.is_configured:
        return

    schedules = scheduler_manager.get_all_schedules()
    triggered_count = 0

    for sched in schedules:
        if sched.get("job_type") == "enrichment":
            continue
            
        if user_id is None or sched.get("user_id") == user_id:
            try:
                logging.info(f"WEBHOOK: Triggering live update for schedule '{sched.get('playlist_name')}'")
                scheduler_manager.run_schedule_now(sched["id"])
                triggered_count += 1
            except Exception as e:
                logging.error(f"WEBHOOK: Failed to run schedule {sched['id']} during live update: {e}")

    logging.info(f"WEBHOOK: Finished live update. {triggered_count} schedule(s) refreshed.")

@router.post("/api/webhook")
async def handle_media_webhook(request: Request):
    """
    Receives JSON payloads from the Emby/Jellyfin Webhook plugin.
    Returns 200 immediately and processes the updates via a debounced background job.
    """
    if not app_state.is_configured:
        return {"status": "ignored", "reason": "App not configured"}
    try:
        payload: Dict[str, Any] = await request.json()
    except Exception:
        return {"status": "ignored", "reason": "Empty or invalid JSON payload"}

    event_type = payload.get("Event", "")
    event_type_lower = event_type.lower()

    if not event_type_lower:
        return {"status": "ignored", "reason": "No Event type provided in payload"}

    user_id = None
    if "User" in payload and isinstance(payload["User"], dict):
        user_id = payload["User"].get("Id")
    elif "UserId" in payload:
        user_id = payload.get("UserId")

    relevant_keywords = [
        "stop",
        "played",
        "userdata",
        "new",
        "added",
        "removed",
        "deleted"
    ]

    if any(keyword in event_type_lower for keyword in relevant_keywords):
        
        run_time = datetime.now() + timedelta(seconds=10)
        job_id = f"webhook_debounce_{user_id}"

        logging.info(f"WEBHOOK: Received '{event_type}'. Scheduling/Delaying rebuild for 10 seconds.")

        scheduler_manager.scheduler.add_job(
            func=trigger_relevant_schedules,
            trigger='date',
            run_date=run_time,
            args=[user_id],
            id=job_id,
            name=f"Debounced Webhook Update for {user_id}",
            replace_existing=True 
        )

        return {"status": "accepted", "message": f"Playlist rebuild queued for {run_time.strftime('%H:%M:%S')}."}

    return {"status": "ignored", "reason": f"Event '{event_type}' does not require playlist updates."}