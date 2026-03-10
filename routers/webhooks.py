"""
routers/webhooks.py – APIRouter for handling live events from Emby/Jellyfin
"""

import logging
from fastapi import APIRouter, BackgroundTasks, Request
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
        # If the webhook gave us a specific user, only update their stuff to save resources.
        if user_id is None or sched.get("user_id") == user_id:
            try:
                logging.info(f"WEBHOOK: Triggering live update for schedule '{sched.get('playlist_name')}'")
                scheduler_manager.run_schedule_now(sched["id"])
                triggered_count += 1
            except Exception as e:
                logging.error(f"WEBHOOK: Failed to run schedule {sched['id']} during live update: {e}")

    logging.info(f"WEBHOOK: Finished live update. {triggered_count} schedule(s) refreshed.")


@router.post("/api/webhook")
async def handle_media_webhook(request: Request, background_tasks: BackgroundTasks):
    """
    Receives JSON payloads from the Emby/Jellyfin Webhook plugin.
    Returns 200 immediately and processes the updates in the background.
    """
    if not app_state.is_configured:
        return {"status": "ignored", "reason": "App not configured"}

    try:
        payload: Dict[str, Any] = await request.json()
    except Exception:
        payload = {}

    # Emby Webhook Plugin usually sends the event type in "Event"
    event_type = payload.get("Event", "")
    event_type_lower = event_type.lower()
    
    # Extract User ID if it's a user-specific event (like PlaybackStop)
    user_id = None
    if "User" in payload and isinstance(payload["User"], dict):
        user_id = payload["User"].get("Id")
    elif "UserId" in payload:
        user_id = payload.get("UserId")

    # We use lowercase keywords to safely catch both Emby and Jellyfin event names
    # e.g. "stop" catches "playback.stop" (Emby) and "PlaybackStop" (Jellyfin)
    relevant_keywords = [
        "stop",       # Playback Stop
        "played",     # Mark Played / Mark Unplayed
        "userdata",   # User Data Changed (Jellyfin equivalent)
        "new",        # New Media Added (Emby: library.new)
        "added",      # New Media Added (Jellyfin: ItemAdded)
        "removed",    # Media Removed (Jellyfin: ItemRemoved)
        "deleted"     # Media Removed (Emby: library.deleted)
    ]

    # If the payload matches a keyword, or is empty (a test ping), we process it
    if not event_type_lower or any(keyword in event_type_lower for keyword in relevant_keywords):
        logging.info(f"WEBHOOK: Received relevant event '{event_type}'. Queuing background refresh.")
        
        # Add the rebuild process to FastAPI's background queue
        background_tasks.add_task(trigger_relevant_schedules, user_id)
        
        return {"status": "accepted", "message": "Playlist rebuild queued."}

    return {"status": "ignored", "reason": f"Event '{event_type}' does not require playlist updates."}