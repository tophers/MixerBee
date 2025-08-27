import logging
from fastapi import APIRouter, HTTPException
from fastapi.responses import JSONResponse

import app as core
import models
import app_state

router = APIRouter()

@router.get("/api/users")
def api_users():
    if not app_state.is_configured: return []
    users = core.all_users(app_state.HDR)
    return [{"id": u["Id"], "name": u["Name"]} for u in users]

@router.get("/api/default_user")
def api_default_user():
    if not app_state.is_configured: return {"id": None, "name": "Not Configured"}
    return {"id": app_state.DEFAULT_UID, "name": app_state.DEFAULT_USER_NAME}

@router.get("/api/shows")
def api_shows():
    if not app_state.is_configured: return []
    r = core.SESSION.get(
        f"{core.EMBY_URL}/Users/{app_state.login_uid}/Items",
        params={"IncludeItemTypes": "Series", "Recursive": "true"},
        headers=app_state.HDR, timeout=10,
    )
    r.raise_for_status()
    return [{"id": i["Id"], "name": i["Name"]} for i in r.json().get("Items", [])]

@router.get("/api/episode_lookup")
def api_episode_lookup(series_id: str, season: int, episode: int):
    if not app_state.is_configured: raise HTTPException(status_code=400, detail="Not configured")
    ep_data = core.get_specific_episode(series_id, season, episode, app_state.HDR)
    if not ep_data:
        raise HTTPException(status_code=404, detail="Specific episode not found.")
    return {"name": ep_data.get("Name", "Unknown Episode")}

@router.get("/api/shows/{series_id}/first_unwatched")
def api_get_first_unwatched(series_id: str, user_id: str):
    if not app_state.is_configured: raise HTTPException(status_code=400, detail="Not configured")
    user_specific_hdr = core.auth_headers(app_state.token, user_id)
    ep_data = core.get_first_unwatched_episode(series_id, user_id, user_specific_hdr)
    if not ep_data:
        raise HTTPException(status_code=404, detail="Could not find an unwatched episode.")
    return ep_data

@router.get("/api/shows/{series_id}/random_unwatched")
def api_get_random_unwatched(series_id: str, user_id: str):
    if not app_state.is_configured: raise HTTPException(status_code=400, detail="Not configured")
    user_specific_hdr = core.auth_headers(app_state.token, user_id)
    ep_data = core.get_random_unwatched_episode(series_id, user_id, user_specific_hdr)
    if not ep_data:
        raise HTTPException(status_code=404, detail="Could not find a random episode.")
    return ep_data

@router.get("/api/users/{user_id}/playlists")
def api_get_playlists(user_id: str):
    if not app_state.is_configured: return []
    user_specific_hdr = core.auth_headers(app_state.token, user_id)
    playlists = core.get_playlists(user_id, user_specific_hdr)
    return playlists

@router.get("/api/movie_genres")
def api_movie_genres():
    if not app_state.is_configured: return []
    return core.get_movie_genres(app_state.login_uid, app_state.HDR)

@router.get("/api/movie_libraries")
def api_movie_libraries():
    if not app_state.is_configured:
        return []
    return core.get_movie_libraries(app_state.login_uid, app_state.HDR)

@router.get("/api/music/genres")
def api_music_genres():
    if not app_state.is_configured: return []
    return core.get_music_genres(app_state.login_uid, app_state.HDR)

@router.get("/api/music/artists")
def api_music_artists():
    if not app_state.is_configured: return []
    return core.get_music_artists(app_state.HDR)

@router.get("/api/music/artists/{artist_id}/albums")
def api_music_artist_albums(artist_id: str):
    if not app_state.is_configured: raise HTTPException(status_code=400, detail="Not configured")
    return core.get_albums_by_artist(artist_id, app_state.HDR)

@router.get("/api/people")
def api_get_people(name: str = ""):
    """Searches for people (actors, directors, etc.) by name."""
    if not app_state.is_configured:
        return []
    return core.get_people(name, app_state.HDR)

@router.get("/api/studios")
def api_get_studios(name: str = ""):
    """Searches for studios by name."""
    if not app_state.is_configured:
        return []
    return core.get_studios(name, app_state.login_uid, app_state.HDR)

@router.get("/api/music/random_artist")
def api_get_random_artist():
    if not app_state.is_configured: raise HTTPException(status_code=400, detail="Not configured")
    artist = core.get_random_artist(app_state.HDR)
    if not artist:
        raise HTTPException(status_code=404, detail="No artists found in the library.")
    return artist

@router.get("/api/music/random_album")
def api_get_random_album():
    if not app_state.is_configured: raise HTTPException(status_code=400, detail="Not configured")
    album = core.get_random_album(app_state.HDR)
    if not album:
        raise HTTPException(status_code=404, detail="No albums found in the library.")
    return album

@router.get("/api/manageable_items")
def api_manageable_items(user_id: str):
    if not app_state.is_configured: return []
    user_specific_hdr = core.auth_headers(app_state.token, user_id)
    items = core.get_manageable_items(user_id, user_specific_hdr)
    cache_headers = {
        "Cache-Control": "no-cache, no-store, must-revalidate",
        "Pragma": "no-cache",
        "Expires": "0",
    }
    return JSONResponse(content=items, headers=cache_headers)

@router.get("/api/items/{item_id}/children")
def api_get_item_children(item_id: str, user_id: str):
    if not app_state.is_configured: raise HTTPException(status_code=400, detail="Not configured")
    user_specific_hdr = core.auth_headers(app_state.token, user_id)
    try:
        return core.get_item_children(user_id, item_id, user_specific_hdr)
    except Exception as e:
        logging.error(f"Error fetching children for item {item_id}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/api/delete_item")
def api_delete_item(req: models.DeleteItemRequest):
    if not app_state.is_configured: raise HTTPException(status_code=400, detail="Not configured")
    try:
        action_hdr = core.auth_headers(app_state.token, req.user_id)
        success = core.delete_item_by_id(req.item_id, action_hdr)
        if success:
            return {"status": "ok", "log": ["Item deleted successfully."]}
        else:
            raise HTTPException(status_code=400, detail="Failed to delete item. Check server logs for permission issues.")
    except Exception as e:
        logging.error(f"Error processing delete request for item {req.item_id}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"An internal server error occurred: {str(e)}")

@router.post("/api/playlists/{playlist_id}/items/remove")
def api_remove_from_playlist(playlist_id: str, req: models.RemoveFromPlaylistRequest):
    if not app_state.is_configured: raise HTTPException(status_code=400, detail="Not configured")
    try:
        action_hdr = core.auth_headers(app_state.token, req.user_id)
        success = core.remove_item_from_playlist(playlist_id, req.item_id_to_remove, action_hdr)
        if success:
            return {"status": "ok", "log": ["Item removed from playlist."]}
        else:
            # This could be because the item wasn't found in the playlist to begin with.
            raise HTTPException(status_code=400, detail="Failed to remove item from playlist. It may have already been removed.")
    except Exception as e:
        logging.error(f"Error removing item {req.item_id_to_remove} from playlist {playlist_id}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/api/mix")
def api_mix(req: models.MixRequest):
    if not app_state.is_configured: raise HTTPException(status_code=400, detail="Not configured")
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
