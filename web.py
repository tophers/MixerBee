#!/usr/bin/env python3
"""
web.py – FastAPI wrapper for MixerBee.
"""
import os
from pathlib import Path
from typing import List, Optional, Dict

from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

import mixerbee_core as core
import scheduler
import gemini_client
from apscheduler.triggers.cron import CronTrigger

app = FastAPI(title="MixerBee API", root_path="/mixerbee")
HERE = Path(__file__).parent

# Correctly mount the entire static directory
app.mount("/static", StaticFiles(directory=HERE / "static"), name="static")

# --- Load Environment ---
login_uid, token = core.authenticate(core.EMBY_USER, core.EMBY_PASS)
HDR = core.auth_headers(token, login_uid)
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

DEFAULT_USER_NAME = os.getenv("FRONTEND_DEFAULT_USER", core.EMBY_USER)
DEFAULT_UID = core.user_id_by_name(DEFAULT_USER_NAME, HDR) or login_uid

# --- Define Models ---
class MovieFinderRequest(BaseModel):
    user_id: str
    filters: dict = {}

class MixedPlaylistRequest(BaseModel):
    user_id: str
    playlist_name: str
    blocks: Optional[List[dict]] = None # Made optional to support collection creation
    create_as_collection: bool = False

class PilotSamplerRequest(BaseModel):
    user_id: str
    playlist_name: str = "Pilot Sampler"
    count: int = 5

class ContinueWatchingRequest(BaseModel):
    user_id: str
    playlist_name: str = "Continue Watching"
    count: int = 10

class ScheduleDetails(BaseModel):
    frequency: str
    time: str
    days_of_week: Optional[List[int]] = Field(None, ge=0, le=6)

class ScheduleRequest(BaseModel):
    playlist_name: str
    user_id: str
    blocks: List[Dict]
    preset_name: str
    schedule_details: ScheduleDetails

class AiPromptRequest(BaseModel):
    prompt: str

class ForgottenFavoritesRequest(BaseModel):
    user_id: str
    playlist_name: str
    count: int = 20

class MovieMarathonRequest(BaseModel):
    user_id: str
    playlist_name: str
    genre: str
    count: int

class MixRequest(BaseModel):
    shows: List[str] = []
    count: int = 5
    playlist: str = "MixerBee Playlist"
    delete: bool = False
    verbose: bool = False
    target_uid: Optional[str] = None

# --- Startup and Shutdown ---
@app.on_event("startup")
def startup_event():
    scheduler.scheduler_manager.start()

@app.on_event("shutdown")
def shutdown_event():
    scheduler.scheduler_manager.scheduler.shutdown()


# --- Endpoints ---
@app.get("/", response_class=HTMLResponse)
def index():
    return (HERE / "templates" / "index.html").read_text()

@app.get("/api/config_status")
def api_config_status():
    return {"is_ai_configured": bool(GEMINI_API_KEY)}

@app.post("/api/create_from_text")
def api_create_from_text(req: AiPromptRequest):
    if not GEMINI_API_KEY:
        raise HTTPException(status_code=501, detail="Gemini API key is not configured on the server.")

    try:
        available_shows = [s['Name'] for s in core.search_series("", HDR)]
        available_genres = [g['Name'] for g in core.get_movie_genres(HDR)]

        blocks = gemini_client.generate_blocks_from_prompt(
            prompt=req.prompt,
            api_key=GEMINI_API_KEY,
            available_shows=available_shows,
            available_genres=available_genres
        )
        return {"status": "ok", "blocks": blocks}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/create_forgotten_favorites")
def api_create_forgotten_favorites(req: ForgottenFavoritesRequest):
    log_messages = []
    result = core.create_forgotten_favorites_playlist(
        user_id=req.user_id,
        playlist_name=req.playlist_name,
        count=req.count,
        hdr=HDR,
        log=log_messages
    )
    return result

@app.post("/api/create_movie_marathon")
def api_create_movie_marathon(req: MovieMarathonRequest):
    log_messages = []
    result = core.create_movie_marathon_playlist(
        user_id=req.user_id,
        playlist_name=req.playlist_name,
        genre=req.genre,
        count=req.count,
        hdr=HDR,
        log=log_messages
    )
    return result

@app.get("/api/users")
def api_users():
    users = core.all_users(HDR)
    return [{"id": u["Id"], "name": u["Name"]} for u in users]

@app.get("/api/default_user")
def api_default_user():
    return {"id": DEFAULT_UID, "name": DEFAULT_USER_NAME}

@app.get("/api/shows")
def api_shows():
    r = core.SESSION.get(
        f"{core.EMBY_URL}/Users/{login_uid}/Items",
        params={"IncludeItemTypes": "Series", "Recursive": "true", "Limit": 1000},
        headers=HDR, timeout=10,
    )
    r.raise_for_status()
    return [{"id": i["Id"], "name": i["Name"]} for i in r.json().get("Items", [])]

@app.get("/api/episode_lookup")
def api_episode_lookup(series_id: str, season: int, episode: int):
    ep_data = core.get_specific_episode(series_id, season, episode, HDR)
    if not ep_data:
        raise HTTPException(status_code=404, detail="Specific episode not found.")
    return {"name": ep_data.get("Name", "Unknown Episode")}

@app.get("/api/shows/{series_id}/first_unwatched")
def api_get_first_unwatched(series_id: str, user_id: str):
    ep_data = core.get_first_unwatched_episode(series_id, user_id, HDR)
    if not ep_data:
        raise HTTPException(status_code=404, detail="Could not find an unwatched episode.")
    return ep_data

@app.get("/api/shows/{series_id}/random_unwatched")
def api_get_random_unwatched(series_id: str, user_id: str):
    ep_data = core.get_random_unwatched_episode(series_id, user_id, HDR)
    if not ep_data:
        raise HTTPException(status_code=404, detail="Could not find a random episode.")
    return ep_data

@app.get("/api/users/{user_id}/playlists")
def api_get_playlists(user_id: str):
    playlists = core.get_playlists(user_id, HDR)
    return playlists

@app.get("/api/movie_genres")
def api_movie_genres():
    return core.get_movie_genres(HDR)

@app.get("/api/movie_libraries")
def api_movie_libraries():
    return core.get_movie_libraries(HDR)

@app.post("/api/mix")
def api_mix(req: MixRequest):
    """
    Legacy endpoint for deleting playlists from the 'Manage Playlists' modal.
    The creation part of this is no longer used by the UI.
    """
    try:
        # We only expect this to be used for deletion from the modal now.
        if req.delete:
            return core.mix(
                shows=[],
                count=0,
                playlist=req.playlist,
                delete=True,
                verbose=False,
                target_uid=req.target_uid,
            )
        # Should not be reached from the current UI
        raise HTTPException(400, "This endpoint is for deletion only.")
    except Exception as e:
        raise HTTPException(400, str(e))

@app.post("/api/movies/preview_count")
def api_movies_preview_count(req: MovieFinderRequest):
    try:
        filters = req.filters.copy()
        # Ensure we check all movies, regardless of duration or limit, for the count
        filters['duration_minutes'] = None
        filters['limit'] = None
        found_movies = core.find_movies(user_id=req.user_id, filters=filters, hdr=HDR)
        return {"count": len(found_movies)}
    except Exception as e:
        raise HTTPException(400, str(e))

@app.post("/api/create_mixed_playlist")
def api_create_mixed_playlist(req: MixedPlaylistRequest):
    if req.create_as_collection:
        if not req.blocks or len(req.blocks) != 1 or req.blocks[0].get("type") != "movie":
            raise HTTPException(400, "Collections can only be created from a single movie block.")
        
        movie_filters = req.blocks[0].get("filters", {})
        return core.create_movie_collection(
            user_id=req.user_id,
            collection_name=req.playlist_name,
            filters=movie_filters,
            hdr=HDR
        )
    else:
        # Fallback to existing static playlist/mixed content logic
        if not req.blocks:
             raise HTTPException(400, "No blocks provided for playlist creation.")
        return core.create_mixed_playlist(
            user_id=req.user_id,
            playlist_name=req.playlist_name,
            blocks=req.blocks,
            hdr=HDR
        )

@app.post("/api/create_pilot_sampler")
def api_create_pilot_sampler(req: PilotSamplerRequest):
    log_messages = []
    result = core.create_pilot_sampler_playlist(
        user_id=req.user_id,
        playlist_name=req.playlist_name,
        count=req.count,
        hdr=HDR,
        log=log_messages
    )
    return result

@app.post("/api/create_continue_watching_playlist")
def api_create_continue_watching_playlist(req: ContinueWatchingRequest):
    log_messages = []
    result = core.create_continue_watching_playlist(
        user_id=req.user_id,
        playlist_name=req.playlist_name,
        count=req.count,
        hdr=HDR,
        log=log_messages
    )
    return result

@app.get("/api/schedules")
def api_get_schedules():
    return scheduler.scheduler_manager.get_all_schedules()

@app.post("/api/schedules")
def api_create_schedule(req: ScheduleRequest):
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

        schedule_data_to_save = req.dict()
        schedule_data_to_save['crontab'] = crontab

        schedule_id = scheduler.scheduler_manager.add_schedule(schedule_data_to_save)
        return {"status": "ok", "log": ["Schedule created successfully."], "id": schedule_id}

    except ValueError as e:
        raise HTTPException(status_code=400, detail=f"Invalid schedule format: {e}")

@app.delete("/api/schedules/{schedule_id}")
def api_delete_schedule(schedule_id: str):
    scheduler.scheduler_manager.remove_schedule(schedule_id)
    return {"status": "ok", "log": ["Schedule deleted."]}
