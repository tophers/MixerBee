#!/usr/bin/env python3
"""
web.py – FastAPI wrapper for MixerBee.
"""
import os
import logging
from pathlib import Path
from typing import List, Optional, Dict

from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from dotenv import load_dotenv

import app as core
import scheduler
import gemini_client
from apscheduler.triggers.cron import CronTrigger

app = FastAPI(title="MixerBee API", root_path="/mixerbee")
HERE = Path(__file__).parent

# --- Environment File Path Resolution ---
ENV_PATH = HERE / ".mixerbee.env"
if not ENV_PATH.exists():
    xdg_config_home = os.getenv("XDG_CONFIG_HOME", "~/.config")
    xdg_config_path = Path(xdg_config_home).expanduser() / "mixerbee" / ".env"
    if xdg_config_path.exists():
        ENV_PATH = xdg_config_path
    ENV_PATH.parent.mkdir(parents=True, exist_ok=True)


# Correctly mount the entire static directory
app.mount("/static/js", StaticFiles(directory=HERE / "static/js"), name="js")
app.mount("/static/css", StaticFiles(directory=HERE / "static/css"), name="css")
app.mount("/static/vendor", StaticFiles(directory=HERE / "static/vendor"), name="vendor")
app.mount("/static", StaticFiles(directory=HERE / "static"), name="static_root")


# --- Global State Variables ---
# These will now be managed and can be "hot-swapped"
login_uid, token, HDR, is_configured = None, None, {}, False
DEFAULT_USER_NAME, DEFAULT_UID = None, None
GEMINI_API_KEY = None


def load_and_authenticate():
    """Loads config from .env and authenticates, setting global state."""
    global login_uid, token, HDR, is_configured, DEFAULT_USER_NAME, DEFAULT_UID, GEMINI_API_KEY

    # Use override to ensure it re-reads the file if it has changed
    load_dotenv(ENV_PATH, override=True)
    
    # Reload from os.environ after load_dotenv
    core.EMBY_URL = os.environ.get("EMBY_URL", "").rstrip("/")
    core.EMBY_USER = os.environ.get("EMBY_USER")
    core.EMBY_PASS = os.environ.get("EMBY_PASS")
    GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

    try:
        if not all([core.EMBY_URL, core.EMBY_USER, core.EMBY_PASS]):
            raise ValueError("Missing required Emby credentials in environment.")

        login_uid, token = core.authenticate(core.EMBY_USER, core.EMBY_PASS, core.EMBY_URL)
        HDR = core.auth_headers(token, login_uid)
        
        DEFAULT_USER_NAME = core.EMBY_USER
        DEFAULT_UID = login_uid
        
        is_configured = True
        logging.info("Successfully loaded configuration and authenticated with Emby.")

    except Exception as e:
        login_uid, token, HDR, is_configured = None, None, {}, False
        DEFAULT_USER_NAME, DEFAULT_UID = None, None
        logging.warning(f"Initial configuration load failed: {e}")


# --- Define Models ---
class SettingsRequest(BaseModel):
    emby_url: str
    emby_user: str
    emby_pass: str
    gemini_key: Optional[str] = None

class MovieFinderRequest(BaseModel):
    user_id: str
    filters: dict = {}

class MusicFinderRequest(BaseModel):
    user_id: str
    filters: dict = {}

class MixedPlaylistRequest(BaseModel):
    user_id: str
    playlist_name: str
    blocks: Optional[List[dict]] = None
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

class ArtistSpotlightRequest(BaseModel):
    user_id: str
    playlist_name: str
    artist_id: str
    count: int

class AlbumPlaylistRequest(BaseModel):
    user_id: str
    playlist_name: str
    album_id: str

class MusicGenrePlaylistRequest(BaseModel):
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

class DeleteItemRequest(BaseModel):
    item_id: str
    user_id: str

# --- Startup and Shutdown ---
@app.on_event("startup")
def startup_event():
    """Load config on startup."""
    load_and_authenticate()
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
    return {
        "is_configured": is_configured,
        "is_ai_configured": bool(GEMINI_API_KEY)
    }

@app.post("/api/settings")
def api_save_settings(req: SettingsRequest):
    """Saves connection details and hot-swaps the active configuration."""
    env_content = (
        f'EMBY_URL="{req.emby_url}"\n'
        f'EMBY_USER="{req.emby_user}"\n'
        f'EMBY_PASS="{req.emby_pass}"\n'
    )
    if req.gemini_key:
        env_content += f'GEMINI_API_KEY="{req.gemini_key}"\n'

    try:
        core.authenticate(req.emby_user, req.emby_pass, req.emby_url)
        
        with open(ENV_PATH, "w") as f:
            f.write(env_content)
        
        load_and_authenticate()
        
        return {
            "status": "ok",
            "log": ["Settings saved and applied successfully! The page will now reload."]
        }
    except Exception as e:
        logging.error(f"Failed to save settings: {e}", exc_info=True)
        error_detail = "Could not authenticate with the provided Emby credentials. Please check the URL, username, and password."
        raise HTTPException(status_code=400, detail=error_detail)


@app.post("/api/settings/test")
def api_test_settings():
    """Tests the currently loaded .env configuration."""
    if not is_configured:
        return JSONResponse(
            status_code=400,
            content={"status": "error", "log": ["Application is not configured."]}
        )
    try:
        core.authenticate(core.EMBY_USER, core.EMBY_PASS, core.EMBY_URL)
        return {"status": "ok", "log": ["Emby connection test successful!"]}
    except Exception as e:
        logging.error(f"Failed to test settings: {e}", exc_info=True)
        return JSONResponse(
            status_code=400,
            content={"status": "error", "log": ["Connection test failed. Check .env file and Emby server status."]}
        )

@app.post("/api/create_from_text")
def api_create_from_text(req: AiPromptRequest):
    if not is_configured: raise HTTPException(status_code=400, detail="Not configured")
    if not GEMINI_API_KEY:
        raise HTTPException(status_code=501, detail="Gemini API key is not configured on the server.")

    try:
        available_shows = [s['Name'] for s in core.search_series("", HDR)]
        available_genres = [g['Name'] for g in core.get_movie_genres(login_uid, HDR)]
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
    if not is_configured: raise HTTPException(status_code=400, detail="Not configured")
    log_messages = []
    user_specific_hdr = core.auth_headers(token, req.user_id)
    result = core.create_forgotten_favorites_playlist(
        user_id=req.user_id,
        playlist_name=req.playlist_name,
        count=req.count,
        hdr=user_specific_hdr,
        log=log_messages
    )
    return result

@app.post("/api/create_movie_marathon")
def api_create_movie_marathon(req: MovieMarathonRequest):
    if not is_configured: raise HTTPException(status_code=400, detail="Not configured")
    log_messages = []
    user_specific_hdr = core.auth_headers(token, req.user_id)
    result = core.create_movie_marathon_playlist(
        user_id=req.user_id,
        playlist_name=req.playlist_name,
        genre=req.genre,
        count=req.count,
        hdr=user_specific_hdr,
        log=log_messages
    )
    return result

@app.post("/api/create_artist_spotlight")
def api_create_artist_spotlight(req: ArtistSpotlightRequest):
    if not is_configured: raise HTTPException(status_code=400, detail="Not configured")
    log_messages = []
    user_specific_hdr = core.auth_headers(token, req.user_id)
    result = core.create_artist_spotlight_playlist(
        user_id=req.user_id,
        playlist_name=req.playlist_name,
        artist_id=req.artist_id,
        count=req.count,
        hdr=user_specific_hdr,
        log=log_messages
    )
    return result

@app.post("/api/create_album_playlist")
def api_create_album_playlist(req: AlbumPlaylistRequest):
    if not is_configured: raise HTTPException(status_code=400, detail="Not configured")
    log_messages = []
    user_specific_hdr = core.auth_headers(token, req.user_id)
    result = core.create_album_playlist(
        user_id=req.user_id,
        playlist_name=req.playlist_name,
        album_id=req.album_id,
        hdr=user_specific_hdr,
        log=log_messages
    )
    return result

@app.post("/api/create_music_genre_playlist")
def api_create_music_genre_playlist(req: MusicGenrePlaylistRequest):
    if not is_configured: raise HTTPException(status_code=400, detail="Not configured")
    log_messages = []
    user_specific_hdr = core.auth_headers(token, req.user_id)
    result = core.create_music_genre_playlist(
        user_id=req.user_id,
        playlist_name=req.playlist_name,
        genre=req.genre,
        count=req.count,
        hdr=user_specific_hdr,
        log=log_messages
    )
    return result

@app.post("/api/create_pilot_sampler")
def api_create_pilot_sampler(req: PilotSamplerRequest):
    if not is_configured: raise HTTPException(status_code=400, detail="Not configured")
    log_messages = []
    user_specific_hdr = core.auth_headers(token, req.user_id)
    result = core.create_pilot_sampler_playlist(
        user_id=req.user_id,
        playlist_name=req.playlist_name,
        count=req.count,
        hdr=user_specific_hdr,
        log=log_messages
    )
    return result

@app.post("/api/create_continue_watching_playlist")
def api_create_continue_watching_playlist(req: ContinueWatchingRequest):
    if not is_configured: raise HTTPException(status_code=400, detail="Not configured")
    log_messages = []
    user_specific_hdr = core.auth_headers(token, req.user_id)
    result = core.create_continue_watching_playlist(
        user_id=req.user_id,
        playlist_name=req.playlist_name,
        count=req.count,
        hdr=user_specific_hdr,
        log=log_messages
    )
    return result

@app.get("/api/users")
def api_users():
    if not is_configured: return []
    users = core.all_users(HDR)
    return [{"id": u["Id"], "name": u["Name"]} for u in users]

@app.get("/api/default_user")
def api_default_user():
    if not is_configured: return {"id": None, "name": "Not Configured"}
    return {"id": DEFAULT_UID, "name": DEFAULT_USER_NAME}

@app.get("/api/shows")
def api_shows():
    if not is_configured: return []
    r = core.SESSION.get(
        f"{core.EMBY_URL}/Users/{login_uid}/Items",
        params={"IncludeItemTypes": "Series", "Recursive": "true", "Limit": 1000},
        headers=HDR, timeout=10,
    )
    r.raise_for_status()
    return [{"id": i["Id"], "name": i["Name"]} for i in r.json().get("Items", [])]

@app.get("/api/episode_lookup")
def api_episode_lookup(series_id: str, season: int, episode: int):
    if not is_configured: raise HTTPException(status_code=400, detail="Not configured")
    ep_data = core.get_specific_episode(series_id, season, episode, HDR)
    if not ep_data:
        raise HTTPException(status_code=404, detail="Specific episode not found.")
    return {"name": ep_data.get("Name", "Unknown Episode")}

@app.get("/api/shows/{series_id}/first_unwatched")
def api_get_first_unwatched(series_id: str, user_id: str):
    if not is_configured: raise HTTPException(status_code=400, detail="Not configured")
    user_specific_hdr = core.auth_headers(token, user_id)
    ep_data = core.get_first_unwatched_episode(series_id, user_id, user_specific_hdr)
    if not ep_data:
        raise HTTPException(status_code=404, detail="Could not find an unwatched episode.")
    return ep_data

@app.get("/api/shows/{series_id}/random_unwatched")
def api_get_random_unwatched(series_id: str, user_id: str):
    if not is_configured: raise HTTPException(status_code=400, detail="Not configured")
    user_specific_hdr = core.auth_headers(token, user_id)
    ep_data = core.get_random_unwatched_episode(series_id, user_id, user_specific_hdr)
    if not ep_data:
        raise HTTPException(status_code=404, detail="Could not find a random episode.")
    return ep_data

@app.get("/api/users/{user_id}/playlists")
def api_get_playlists(user_id: str):
    if not is_configured: return []
    user_specific_hdr = core.auth_headers(token, user_id)
    playlists = core.get_playlists(user_id, user_specific_hdr)
    return playlists

@app.get("/api/movie_genres")
def api_movie_genres():
    if not is_configured: return []
    return core.get_movie_genres(login_uid, HDR)

@app.get("/api/movie_libraries")
def api_movie_libraries():
    if not is_configured: return []
    return core.get_movie_libraries(login_uid, HDR)

@app.get("/api/music/genres")
def api_music_genres():
    if not is_configured: return []
    return core.get_music_genres(login_uid, HDR)

@app.get("/api/music/artists")
def api_music_artists():
    if not is_configured: return []
    return core.get_music_artists(HDR)

@app.get("/api/music/artists/{artist_id}/albums")
def api_music_artist_albums(artist_id: str):
    if not is_configured: raise HTTPException(status_code=400, detail="Not configured")
    return core.get_albums_by_artist(artist_id, HDR)

@app.get("/api/music/random_artist")
def api_get_random_artist():
    if not is_configured: raise HTTPException(status_code=400, detail="Not configured")
    artist = core.get_random_artist(HDR)
    if not artist:
        raise HTTPException(status_code=404, detail="No artists found in the library.")
    return artist

@app.get("/api/music/random_album")
def api_get_random_album():
    if not is_configured: raise HTTPException(status_code=400, detail="Not configured")
    album = core.get_random_album(HDR)
    if not album:
        raise HTTPException(status_code=404, detail="No albums found in the library.")
    return album

@app.get("/api/manageable_items")
def api_manageable_items(user_id: str):
    if not is_configured: return []
    user_specific_hdr = core.auth_headers(token, user_id)
    items = core.get_manageable_items(user_id, user_specific_hdr)
    cache_headers = {
        "Cache-Control": "no-cache, no-store, must-revalidate",
        "Pragma": "no-cache",
        "Expires": "0",
    }
    return JSONResponse(content=items, headers=cache_headers)

@app.get("/api/items/{item_id}/children")
def api_get_item_children(item_id: str, user_id: str):
    if not is_configured: raise HTTPException(status_code=400, detail="Not configured")
    user_specific_hdr = core.auth_headers(token, user_id)
    try:
        return core.get_item_children(user_id, item_id, user_specific_hdr)
    except Exception as e:
        logging.error(f"Error fetching children for item {item_id}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/delete_item")
def api_delete_item(req: DeleteItemRequest):
    if not is_configured: raise HTTPException(status_code=400, detail="Not configured")
    try:
        action_hdr = core.auth_headers(token, req.user_id)
        success = core.delete_item_by_id(req.item_id, action_hdr)
        if success:
            return {"status": "ok", "log": ["Item deleted successfully."]}
        else:
            raise HTTPException(status_code=400, detail="Failed to delete item. Check server logs for permission issues.")
    except Exception as e:
        logging.error(f"Error processing delete request for item {req.item_id}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"An internal server error occurred: {str(e)}")

@app.post("/api/mix")
def api_mix(req: MixRequest):
    if not is_configured: raise HTTPException(status_code=400, detail="Not configured")
    try:
        if req.delete:
            return core.mix(
                shows=[],
                count=0,
                playlist=req.playlist,
                delete=True,
                verbose=False,
                target_uid=req.target_uid,
            )
        raise HTTPException(400, "This endpoint is for deletion only.")
    except Exception as e:
        raise HTTPException(400, str(e))

@app.post("/api/movies/preview_count")
def api_movies_preview_count(req: MovieFinderRequest):
    if not is_configured: raise HTTPException(status_code=400, detail="Not configured")
    try:
        user_specific_hdr = core.auth_headers(token, req.user_id)
        filters = req.filters.copy()
        filters['duration_minutes'] = None
        filters['limit'] = None
        found_movies = core.find_movies(user_id=req.user_id, filters=filters, hdr=user_specific_hdr)
        return {"count": len(found_movies)}
    except Exception as e:
        raise HTTPException(400, str(e))

@app.post("/api/music/preview_count")
def api_music_preview_count(req: MusicFinderRequest):
    if not is_configured: raise HTTPException(status_code=400, detail="Not configured")
    try:
        user_specific_hdr = core.auth_headers(token, req.user_id)
        filters = req.filters.copy()
        filters['limit'] = None
        found_songs = core.find_songs(user_id=req.user_id, filters=filters, hdr=user_specific_hdr)
        return {"count": len(found_songs)}
    except Exception as e:
        raise HTTPException(400, str(e))


@app.post("/api/create_mixed_playlist")
def api_create_mixed_playlist(req: MixedPlaylistRequest):
    if not is_configured: raise HTTPException(status_code=400, detail="Not configured")
    user_specific_hdr = core.auth_headers(token, req.user_id)
    if req.create_as_collection:
        if not req.blocks or len(req.blocks) != 1 or req.blocks[0].get("type") != "movie":
            raise HTTPException(400, "Collections can only be created from a single movie block.")

        movie_filters = req.blocks[0].get("filters", {})
        return core.create_movie_collection(
            user_id=req.user_id,
            collection_name=req.playlist_name,
            filters=movie_filters,
            hdr=user_specific_hdr
        )
    else:
        if not req.blocks:
             raise HTTPException(400, "No blocks provided for playlist creation.")
        return core.create_mixed_playlist(
            user_id=req.user_id,
            playlist_name=req.playlist_name,
            blocks=req.blocks,
            hdr=user_specific_hdr
        )

@app.get("/api/schedules")
def api_get_schedules():
    if not is_configured: return []
    schedules = scheduler.scheduler_manager.get_all_schedules()
    cache_headers = {
        "Cache-Control": "no-cache, no-store, must-revalidate",
        "Pragma": "no-cache",
        "Expires": "0",
    }
    return JSONResponse(content=schedules, headers=cache_headers)

@app.post("/api/schedules")
def api_create_schedule(req: ScheduleRequest):
    if not is_configured: raise HTTPException(status_code=400, detail="Not configured")
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

@app.post("/api/schedules/{schedule_id}/run")
def api_run_schedule_now(schedule_id: str):
    if not is_configured: raise HTTPException(status_code=400, detail="Not configured")
    result = scheduler.scheduler_manager.run_schedule_now(schedule_id)
    if not result:
        raise HTTPException(status_code=404, detail="Schedule not found.")
    return result

@app.delete("/api/schedules/{schedule_id}")
def api_delete_schedule(schedule_id: str):
    if not is_configured: raise HTTPException(status_code=400, detail="Not configured")
    scheduler.scheduler_manager.remove_schedule(schedule_id)
    return {"status": "ok", "log": ["Schedule deleted."]}
