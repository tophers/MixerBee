"""
routers/library.py – APIRouter
"""

import logging
from typing import Dict, Any, List
from fastapi import APIRouter, HTTPException, Depends
from fastapi.responses import JSONResponse

import app as core
import models
import app_state
from app.cache import get_library_data
from .dependencies import get_current_auth_headers

router = APIRouter()

@router.get("/api/library_data")
def api_library_data(auth_deps: dict = Depends(get_current_auth_headers)) -> Dict[str, Any]:
    """Returns a consolidated dictionary of all necessary library data for the UI."""
    cached_data = get_library_data()
    if not cached_data:
        raise HTTPException(
            status_code=503,
            detail="Library data is not yet available. The cache may still be warming up. Please try again in a moment."
        )
    return cached_data

@router.get("/api/default_user")
def api_default_user(auth_deps: dict = Depends(get_current_auth_headers)) -> Dict[str, str]:
    return {"id": app_state.DEFAULT_UID, "name": app_state.DEFAULT_USER_NAME}

@router.get("/api/episode_lookup")
def api_episode_lookup(series_id: str, season: int, episode: int, auth_deps: dict = Depends(get_current_auth_headers)) -> Dict[str, str]:
    ep_data = core.get_specific_episode(series_id, season, episode, auth_deps["hdr"])
    if not ep_data:
        raise HTTPException(status_code=404, detail="Specific episode not found.")
    return {"name": ep_data.get("Name", "Unknown Episode")}

@router.get("/api/shows/{series_id}/first_unwatched")
def api_get_first_unwatched(series_id: str, user_id: str, auth_deps: dict = Depends(get_current_auth_headers)) -> Dict[str, Any]:
    user_specific_hdr = core.auth_headers(auth_deps["token"], user_id)
    ep_data = core.get_first_unwatched_episode(series_id, user_id, user_specific_hdr)
    if not ep_data:
        raise HTTPException(status_code=404, detail="Could not find an unwatched episode.")
    return ep_data

@router.get("/api/shows/{series_id}/random_unwatched")
def api_get_random_unwatched(series_id: str, user_id: str, auth_deps: dict = Depends(get_current_auth_headers)) -> Dict[str, Any]:
    user_specific_hdr = core.auth_headers(auth_deps["token"], user_id)
    ep_data = core.get_random_unwatched_episode(series_id, user_id, user_specific_hdr)
    if not ep_data:
        raise HTTPException(status_code=404, detail="Could not find a random episode.")
    return ep_data

@router.get("/api/users/{user_id}/playlists")
def api_get_playlists(user_id: str, auth_deps: dict = Depends(get_current_auth_headers)) -> List[Dict[str, Any]]:
    user_specific_hdr = core.auth_headers(auth_deps["token"], user_id)
    return core.get_playlists(user_id, user_specific_hdr)

@router.get("/api/music/artists/{artist_id}/albums")
def api_music_artist_albums(artist_id: str, auth_deps: dict = Depends(get_current_auth_headers)) -> List[Dict[str, Any]]:
    return core.get_albums_by_artist(artist_id, auth_deps["hdr"])

@router.get("/api/people")
def api_get_people(name: str = "", auth_deps: dict = Depends(get_current_auth_headers)) -> List[Dict[str, str]]:
    """Searches for people (actors, directors, etc.) by name."""
    return core.get_people(name, auth_deps["hdr"])

@router.get("/api/studios")
def api_get_studios(name: str = "", auth_deps: dict = Depends(get_current_auth_headers)) -> List[Dict[str, str]]:
    """Searches for studios by name using the cached library data."""
    library_data = get_library_data()
    return core.get_studios(name, library_data)

@router.get("/api/music/random_artist")
def api_get_random_artist(auth_deps: dict = Depends(get_current_auth_headers)) -> Dict[str, str]:
    artist = core.get_random_artist(auth_deps["hdr"])
    if not artist:
        raise HTTPException(status_code=404, detail="No artists found in the library.")
    return artist

@router.get("/api/music/random_album")
def api_get_random_album(auth_deps: dict = Depends(get_current_auth_headers)) -> Dict[str, str]:
    album = core.get_random_album(auth_deps["hdr"])
    if not album:
        raise HTTPException(status_code=404, detail="No albums found in the library.")
    return album

@router.get("/api/manageable_items")
def api_manageable_items(user_id: str, auth_deps: dict = Depends(get_current_auth_headers)) -> JSONResponse:
    user_specific_hdr = core.auth_headers(auth_deps["token"], user_id)
    items = core.get_manageable_items(user_id, user_specific_hdr)
    cache_headers = {
        "Cache-Control": "no-cache, no-store, must-revalidate",
        "Pragma": "no-cache",
        "Expires": "0",
    }
    return JSONResponse(content=items, headers=cache_headers)

@router.get("/api/items/{item_id}/children")
def api_get_item_children(item_id: str, user_id: str, auth_deps: dict = Depends(get_current_auth_headers)) -> List[Dict[str, Any]]:
    user_specific_hdr = core.auth_headers(auth_deps["token"], user_id)
    try:
        return core.get_item_children(user_id, item_id, user_specific_hdr)
    except Exception as e:
        logging.error(f"Error fetching children for item {item_id}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/api/delete_item")
def api_delete_item(req: models.DeleteItemRequest, auth_deps: dict = Depends(get_current_auth_headers)) -> Dict[str, Any]:
    try:
        action_hdr = core.auth_headers(auth_deps["token"], req.user_id)
        if core.delete_item_by_id(req.item_id, action_hdr):
            return {"status": "ok", "log": ["Item deleted successfully."]}
        else:
            raise HTTPException(status_code=400, detail="Failed to delete item. Check server logs for permission issues.")
    except Exception as e:
        logging.error(f"Error processing delete request for item {req.item_id}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"An internal server error occurred: {str(e)}")

@router.post("/api/playlists/{playlist_id}/items/remove")
def api_remove_from_playlist(playlist_id: str, req: models.RemoveFromPlaylistRequest, auth_deps: dict = Depends(get_current_auth_headers)) -> Dict[str, Any]:
    try:
        action_hdr = core.auth_headers(auth_deps["token"], req.user_id)
        if core.remove_item_from_playlist(playlist_id, req.item_id_to_remove, action_hdr):
            return {"status": "ok", "log": ["Item removed from playlist."]}
        else:
            raise HTTPException(status_code=400, detail="Failed to remove item from playlist. It may have already been removed.")
    except Exception as e:
        logging.error(f"Error removing item {req.item_id_to_remove} from playlist {playlist_id}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/api/convert_item")
def api_convert_item(req: models.ConvertItemRequest, auth_deps: dict = Depends(get_current_auth_headers)) -> Dict[str, Any]:
    action_hdr = core.auth_headers(auth_deps["token"], req.user_id)
    log = []

    try:
        children = core.get_item_children(req.user_id, req.item_id, action_hdr)
        if not children:
            raise HTTPException(status_code=400, detail="Source item is empty. Nothing to convert.")

        item_ids = [child["Id"] for child in children]

        if req.target_type.lower() == "collection":
            new_id = core.create_collection_from_ids(req.user_id, req.new_name, item_ids, action_hdr, log)
        else:
            new_id = core.create_playlist(req.new_name, req.user_id, item_ids, action_hdr, log)

        if not new_id:
            raise HTTPException(status_code=500, detail="Failed to create the new converted item.")

        if req.delete_original:
            core.delete_item_by_id(req.item_id, action_hdr)
            log.append("Original item deleted.")

        return {"status": "ok", "log": log, "new_item_id": new_id}

    except HTTPException:
        raise
    except Exception as e:
        logging.error(f"Error converting item {req.item_id}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))