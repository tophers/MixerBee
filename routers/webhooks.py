"""
routers/webhooks.py – APIRouter
"""

from datetime import datetime, timedelta
from fastapi import APIRouter, Request
from typing import Dict, Any, Set

import app_state
from scheduler import scheduler_manager
from app.logger import get_logger

logger = get_logger("MixerBee.Webhooks")
router = APIRouter()

def _get_schedule_media_types(sched: Dict[str, Any]) -> Set[str]:
    """Analyzes a schedule to determine what media types it manages (tv, movie, music)."""
    types = set()
    job_type = sched.get("job_type")
    
    if job_type == "builder":
        blocks = sched.get("blocks") or []
        for b in blocks:
            t = b.get("type")
            if t == "vibe":
                t = b.get("vibe_type")
            if t:
                types.add(t)
                
    elif job_type == "quick_playlist":
        qp_type = sched.get("quick_playlist_data", {}).get("quick_playlist_type")
        if qp_type in ["recently_added"]: 
            types.update(["movie", "tv"])
        elif qp_type in ["next_up", "pilot_sampler"]: 
            types.add("tv")
        elif qp_type in ["from_the_vault", "genre_roulette"]: 
            types.add("movie")
        elif qp_type in ["artist_spotlight", "album_roulette", "genre_sampler"]: 
            types.add("music")
            
    return types

def trigger_relevant_schedules(user_id: str = None, target_media_type: str = None):
    if not app_state.is_configured:
        return

    schedules = scheduler_manager.get_all_schedules()
    triggered_count = 0

    for sched in schedules:
        if sched.get("job_type") == "enrichment":
            continue
            
        if user_id is None or sched.get("user_id") == user_id:
            if target_media_type:
                sched_types = _get_schedule_media_types(sched)
                if sched_types and target_media_type not in sched_types:
                    logger.info(f"Skipping schedule '{sched.get('playlist_name')}' (Type {sched_types} does not match event '{target_media_type}')")
                    continue
                    
            try:
                logger.info(f"Triggering live update for schedule '{sched.get('playlist_name')}'")
                scheduler_manager.run_schedule_now(sched["id"])
                triggered_count += 1
            except Exception as e:
                logger.error(f"Failed to run schedule {sched['id']} during live update: {e}")

    logger.info(f"Finished live update. {triggered_count} schedule(s) refreshed.")

@router.post("/api/webhook")
async def handle_media_webhook(request: Request):
    user_agent = request.headers.get("user-agent", "UNKNOWN").lower()

    if not app_state.is_configured:
        return {"status": "ignored", "reason": "App not configured"}

    try:
        payload: Dict[str, Any] = await request.json()
    except Exception as e:
        logger.warning(f"Failed to parse JSON. Error: {e}")
        return {"status": "ignored", "reason": "Empty or invalid JSON payload"}

    event_type = payload.get("Event", "")
    event_type_lower = event_type.lower()

    if not event_type_lower:
        return {"status": "ignored", "reason": "No Event type provided in payload"}

    if event_type_lower == "playback.stop":
        played_to_completion = payload.get("PlaybackInfo", {}).get("PlayedToCompletion", False)
        if not played_to_completion:
            logger.info("playback.stop received, but PlayedToCompletion is False (User paused). Ignoring to prevent thrashing.")
            return {"status": "ignored", "reason": "Playback stopped before completion."}

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

    logger.info(f"Parsed Event='{event_type}', UserID='{user_id}', TargetType='{target_media_type}'")

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
        job_id = f"webhook_debounce_{user_id}_{target_media_type or 'all'}"

        logger.info(f"Event matches triggers! Scheduling debounce rebuild for 10s from now.")

        scheduler_manager.scheduler.add_job(
            func=trigger_relevant_schedules,
            trigger='date',
            run_date=run_time,
            args=[user_id, target_media_type],
            id=job_id,
            name=f"Debounced Webhook Update for {user_id} ({target_media_type or 'all'})",
            replace_existing=True 
        )

        return {"status": "accepted", "message": f"Playlist rebuild queued for {run_time.strftime('%H:%M:%S')}."}

    return {"status": "ignored", "reason": f"Event '{event_type}' does not require playlist updates."}