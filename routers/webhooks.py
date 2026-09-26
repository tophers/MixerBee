"""
routers/webhooks.py – APIRouter
"""

import secrets
import time
from datetime import datetime, timedelta
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from typing import Dict, Any, Optional

import app_state
import database
from scheduler import scheduler_manager
from app.logger import get_logger

logger = get_logger("MixerBee.Webhooks")
router = APIRouter()

def classify_webhook_event(payload: Dict[str, Any]) -> Optional[str]:
    """
    Classifies an incoming Emby/Jellyfin webhook event into a normalized category:
    - 'watch': Playback completion, mark played/unplayed, rating, userdata changes.
    - 'library': New/added/created items, removed/deleted items.
    Returns None if the event is unhandled or ignored (e.g. playback paused/uncompleted).
    """
    event_type = payload.get("Event", "")
    event_type_lower = event_type.lower()
    if not event_type_lower:
        return None

    if event_type_lower == "playback.stop":
        played_to_completion = payload.get("PlaybackInfo", {}).get("PlayedToCompletion", False)
        if not played_to_completion:
            return None
        return "watch"

    if any(k in event_type_lower for k in ["played", "userdata", "rating", "markplayed", "scrobble"]):
        return "watch"

    if any(k in event_type_lower for k in ["new", "added", "created", "removed", "deleted", "itemadded"]):
        return "library"

    return None

import threading

_webhook_context = threading.local()

def get_current_webhook_category() -> Optional[str]:
    return getattr(_webhook_context, "category", None)

def trigger_relevant_schedules(user_id: str = None, target_media_type: str = None, connection_id: str = None, event_category: str = "watch"):
    if not connection_id:
        return

    schedules = scheduler_manager.get_all_schedules()
    triggered_count = 0

    for sched in schedules:
        if sched.get("connection_id") != connection_id or sched.get("job_type") == "enrichment":
            continue

        if user_id is None or sched.get("user_id") == user_id:
            try:
                logger.info(f"Triggering live update ({event_category}) for schedule '{sched.get('playlist_name')}'")
                _webhook_context.category = event_category
                try:
                    scheduler_manager.run_schedule_now(sched["id"])
                finally:
                    _webhook_context.category = None
                triggered_count += 1
            except Exception as e:
                logger.error(f"Failed to queue schedule {sched['id']} during live update: {e}")

    logger.info(f"Finished live update. {triggered_count} schedule(s) refreshed.")

@router.post("/api/webhook")
async def legacy_webhook():
    return JSONResponse(status_code=410, content={'detail': 'Use the connection-specific webhook URL from Settings.'})


@router.post("/api/webhook/{connection_id}")
async def handle_media_webhook(connection_id: str, request: Request):
    with database.get_db_connection() as conn:
        row = conn.execute('SELECT webhook_secret FROM media_connections WHERE id=? AND owner_id IS NOT NULL', (connection_id,)).fetchone()
    supplied = request.query_params.get('token') or request.headers.get('x-mixerbee-webhook-secret', '')
    if not row or not row['webhook_secret'] or not secrets.compare_digest(supplied, row['webhook_secret']):
        return JSONResponse(status_code=401, content={'status': 'rejected', 'reason': 'Missing or invalid webhook token.'})

    try:
        payload: Dict[str, Any] = await request.json()
    except Exception as e:
        logger.warning(f"Failed to parse JSON. Error: {e}")
        return {"status": "ignored", "reason": "Empty or invalid JSON payload"}

    event_type = payload.get("Event", "")
    if not event_type:
        return {"status": "ignored", "reason": "No Event type provided in payload"}

    # A valid authenticated media-server event proves that the current URL is
    # installed and reachable, even if this particular event does not rebuild a list.
    now = time.time()
    with database.get_db_connection() as conn:
        conn.execute('''UPDATE media_connections SET webhook_last_received_at=?,
            webhook_verified_at=? WHERE id=?''', (now, now, connection_id))
        conn.commit()

    category = classify_webhook_event(payload)
    if not category:
        return {"status": "ignored", "reason": f"Event '{event_type}' does not require playlist updates or was paused."}

    user_id = None
    if "User" in payload and isinstance(payload["User"], dict):
        user_id = payload["User"].get("Id")
    elif "UserId" in payload:
        user_id = payload.get("UserId")

    item_type = payload.get("Item", {}).get("Type", "")
    target_media_type = None
    if item_type in ["Episode", "Series", "Season"]:
        target_media_type = "tv"
    elif item_type == "Movie":
        target_media_type = "movie"
    elif item_type in ["Audio", "MusicAlbum", "MusicArtist"]:
        target_media_type = "music"

    logger.info(f"Parsed Event='{event_type}', Category='{category}', UserID='{user_id}', TargetType='{target_media_type}'")

    debounce_seconds = app_state.WEBHOOK_DEBOUNCE_SECONDS
    run_time = datetime.now() + timedelta(seconds=debounce_seconds)
    # Debounce preserves category so watch and library events each trigger appropriately
    job_id = f"webhook_debounce_{connection_id}_{user_id}_{category}"

    logger.info(f"Event matches '{category}' category. Scheduling debounced rebuild in {debounce_seconds}s.")

    scheduler_manager.scheduler.add_job(
        func=trigger_relevant_schedules,
        trigger='date',
        run_date=run_time,
        args=[user_id, target_media_type, connection_id, category],
        id=job_id,
        name=f"Debounced {category.capitalize()} Update for {user_id}",
        replace_existing=True 
    )

    return {"status": "accepted", "message": f"{category.capitalize()} update queued for {run_time.strftime('%H:%M:%S')}."}
