"""
library.py – APIRouter
"""

import logging
from fastapi import APIRouter, HTTPException, Depends
from fastapi.responses import JSONResponse

import app as core
import models
import app_state
from app.cache import get_library_data
from .dependencies import get_current_auth_headers

router = APIRouter()

@router.get("/api/library_data")
def api_library_data(auth_deps: dict = Depends(get_current_auth_headers)):
    """Returns a consolidated dictionary of all necessary library data for the UI."""
    cached_data = get_library_data()
    if not cached_data:
        raise HTTPException(
            status_code=503, 
            detail="Library data is not yet available. The cache may still be warming up. Please try again in a moment."
        )
    return cached_data

@router.get("/api/users")
def api_users(auth_deps: dict = Depends(get_current_auth_headers)):
    users = core.all_users(auth_deps["hdr"])
    return [{"id": u["Id"], "name": u["Name"]} for u in users]

@router.get("/api/default_user")
def api_default_user(auth_deps: dict = Depends(get_current_auth_headers)):
    return {"id": app_state.DEFAULT_UID, "name": app_state.DEFAULT_USER_NAME}

@router.get("/api/shows")
def api_shows(auth_deps: dict = Depends(get_current_auth_headers)):
    r = core.SESSION.get(
        f"{core.EMBY_URL}/Users/{auth_deps['login_uid']}/Items",
        params={"IncludeItemTypes": "Series", "Recursive": "true"},
        headers=auth_deps["hdr"], timeout=10,
    )
    r.raise_for_status()
    return [{"id": i["Id"], "name": i["Name"]} for i in r.json().get("Items", [])]

@router.get("/api/episode_lookup")
def api_episode_lookup(series_id: str, season: int, episode: int, auth_deps: dict = Depends(get_current_auth_headers)):
    ep_data = core.get_specific_episode(series_id, season, episode, auth_deps["hdr"])
    if not ep_data:
        raise HTTPException(status_code=404, detail="Specific episode not found.")
    return {"name": ep_data.get("Name", "Unknown Episode")}

@router.get("/api/shows/{series_id}/first_unwatched")
def api_get_first_unwatched(series_id: str, user_id: str, auth_deps: dict = Depends(get_current_auth_headers)):
    user_specific_hdr = core.auth_headers(auth_deps["token"], user_id)
    ep_data = core.get_first_unwatched_episode(series_id, user_id, user_specific_hdr)
    if not ep_data:
        raise HTTPException(status_code=404, detail="Could not find an unwatched episode.")
    return ep_data

@router.get("/api/shows/{series_id}/random_unwatched")
def api_get_random_unwatched(series_id: str, user_id: str, auth_deps: dict = Depends(get_current_auth_headers)):
    user_specific_hdr = core.auth_headers(auth_deps["token"], user_id)
    ep_data = core.get_random_unwatched_episode(series_id, user_id, user_specific_hdr)
    if not ep_data:
        raise HTTPException(status_code=404, detail="Could not find a random episode.")
    return ep_data

@router.get("/api/users/{user_id}/playlists")
def api_get_playlists(user_id: str, auth_deps: dict = Depends(get_current_auth_headers)):
    user_specific_hdr = core.auth_headers(auth_deps["token"], user_id)
    playlists = core.get_playlists(user_id, user_specific_hdr)
    return playlists

@router.get("/api/movie_genres")
def api_movie_genres(auth_deps: dict = Depends(get_current_auth_headers)):
    return core.get_movie_genres(auth_deps["login_uid"], auth_deps["hdr"])

@router.get("/api/movie_libraries")
def api_movie_libraries(auth_deps: dict = Depends(get_current_auth_headers)):
    return core.get_movie_libraries(auth_deps["login_uid"], auth_deps["hdr"])

@router.get("/api/music/genres")
def api_music_genres(auth_deps: dict = Depends(get_current_auth_headers)):
    return core.get_music_genres(auth_deps["login_uid"], auth_deps["hdr"])

@router.get("/api/music/artists")
def api_music_artists(auth_deps: dict = Depends(get_current_auth_headers)):
    return core.get_music_artists(auth_deps["hdr"])

@router.get("/api/music/artists/{artist_id}/albums")
def api_music_artist_albums(artist_id: str, auth_deps: dict = Depends(get_current_auth_headers)):
    return core.get_albums_by_artist(artist_id, auth_deps["hdr"])

@router.get("/api/people")
def api_get_people(name: str = "", auth_deps: dict = Depends(get_current_auth_headers)):
    """Searches for people (actors, directors, etc.) by name."""
    return core.get_people(name, auth_deps["hdr"])

@router.get("/api/studios")
def api_get_studios(name: str = "", auth_deps: dict = Depends(get_current_auth_headers)):
    """Searches for studios by name."""
    return core.get_studios(name, auth_deps["login_uid"], auth_deps["hdr"])

@router.get("/api/music/random_artist")
def api_get_random_artist(auth_deps: dict = Depends(get_current_auth_headers)):
    artist = core.get_random_artist(auth_deps["hdr"])
    if not artist:
        raise HTTPException(status_code=404, detail="No artists found in the library.")
    return artist

@router.get("/api/music/random_album")
def api_get_random_album(auth_deps: dict = Depends(get_current_auth_headers)):
    album = core.get_random_album(auth_deps["hdr"])
    if not album:
        raise HTTPException(status_code=404, detail="No albums found in the library.")
    return album

@router.get("/api/manageable_items")
def api_manageable_items(user_id: str, auth_deps: dict = Depends(get_current_auth_headers)):
    user_specific_hdr = core.auth_headers(auth_deps["token"], user_id)
    items = core.get_manageable_items(user_id, user_specific_hdr)
    cache_headers = {
        "Cache-Control": "no-cache, no-store, must-revalidate",
        "Pragma": "no-cache",
        "Expires": "0",
    }
    return JSONResponse(content=items, headers=cache_headers)

@router.get("/api/items/{item_id}/children")
def api_get_item_children(item_id: str, user_id: str, auth_deps: dict = Depends(get_current_auth_headers)):
    user_specific_hdr = core.auth_headers(auth_deps["token"], user_id)
    try:
        return core.get_item_children(user_id, item_id, user_specific_hdr)
    except Exception as e:
        logging.error(f"Error fetching children for item {item_id}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/api/delete_item")
def api_delete_item(req: models.DeleteItemRequest, auth_deps: dict = Depends(get_current_auth_headers)):
    try:
        action_hdr = core.auth_headers(auth_deps["token"], req.user_id)
        success = core.delete_item_by_id(req.item_id, action_hdr)
        if success:
            return {"status": "ok", "log": ["Item deleted successfully."]}
        else:
            raise HTTPException(status_code=400, detail="Failed to delete item. Check server logs for permission issues.")
    except Exception as e:
        logging.error(f"Error processing delete request for item {req.item_id}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"An internal server error occurred: {str(e)}")

@router.post("/api/playlists/{playlist_id}/items/remove")
def api_remove_from_playlist(playlist_id: str, req: models.RemoveFromPlaylistRequest, auth_deps: dict = Depends(get_current_auth_headers)):
    try:
        action_hdr = core.auth_headers(auth_deps["token"], req.user_id)
        success = core.remove_item_from_playlist(playlist_id, req.item_id_to_remove, action_hdr)
        if success:
            return {"status": "ok", "log": ["Item removed from playlist."]}
        else:
            raise HTTPException(status_code=400, detail="Failed to remove item from playlist. It may have already been removed.")
    except Exception as e:
        logging.error(f"Error removing item {req.item_id_to_remove} from playlist {playlist_id}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/api/mix")
def api_mix(req: models.MixRequest, auth_deps: dict = Depends(get_current_auth_headers)):
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