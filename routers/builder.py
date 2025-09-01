"""
builder.py – APIRouter
"""

import logging
from fastapi import APIRouter, HTTPException, Depends

import app as core
import models
import app_state
import gemini_client
from .dependencies import get_current_auth_headers

router = APIRouter()

def _construct_item_url(item_id: str) -> str:
    """Helper to construct the correct Emby/Jellyfin URL for an item."""
    if not item_id:
        return None
    base_url = core.EMBY_URL.rstrip("/")
    if app_state.SERVER_TYPE == 'jellyfin':
        return f"{base_url}/web/index.html#!/details?id={item_id}"
    else: # emby
        url = f"{base_url}/web/index.html#!/item?id={item_id}"
        if app_state.SERVER_ID:
            url += f"&serverId={app_state.SERVER_ID}"
        return url

@router.post("/api/create_from_text")
def api_create_from_text(req: models.AiPromptRequest, auth_deps: dict = Depends(get_current_auth_headers)):
    if not app_state.GEMINI_API_KEY:
        raise HTTPException(status_code=501, detail="Gemini API key is not configured on the server.")

    try:
        available_shows = [s['Name'] for s in core.search_series("", auth_deps["hdr"])]
        available_genres = [g['Name'] for g in core.get_movie_genres(auth_deps["login_uid"], auth_deps["hdr"])]
        blocks = gemini_client.generate_blocks_from_prompt(
            prompt=req.prompt,
            api_key=app_state.GEMINI_API_KEY,
            available_shows=available_shows,
            available_genres=available_genres
        )

        for block in blocks:
            if block.get("type") == "movie":
                filters = block.get("filters", {})

                for person_key in ["people", "exclude_people"]:
                    if person_key in filters and filters[person_key]:
                        resolved_people = []
                        for person_info in filters[person_key]:
                            if person_info.get("Name"):
                                found_people = core.get_people(person_info["Name"], auth_deps["hdr"])
                                if found_people:
                                    resolved_people.append(found_people[0])
                        filters[person_key] = resolved_people

        return {"status": "ok", "blocks": blocks}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/api/movies/preview_count")
def api_movies_preview_count(req: models.MovieFinderRequest, auth_deps: dict = Depends(get_current_auth_headers)):
    try:
        user_specific_hdr = core.auth_headers(auth_deps["token"], req.user_id)
        filters = req.filters.copy()
        filters['duration_minutes'] = None
        filters['limit'] = None
        found_movies = core.find_movies(user_id=req.user_id, filters=filters, hdr=user_specific_hdr)
        return {"count": len(found_movies)}
    except Exception as e:
        raise HTTPException(400, str(e))

@router.post("/api/music/preview_count")
def api_music_preview_count(req: models.MusicFinderRequest, auth_deps: dict = Depends(get_current_auth_headers)):
    try:
        user_specific_hdr = core.auth_headers(auth_deps["token"], req.user_id)
        filters = req.filters.copy()
        filters['limit'] = None
        found_songs = core.find_songs(user_id=req.user_id, filters=filters, hdr=user_specific_hdr)
        return {"count": len(found_songs)}
    except Exception as e:
        raise HTTPException(400, str(e))

@router.post("/api/builder/preview")
def api_builder_preview(req: models.BuilderPreviewRequest, auth_deps: dict = Depends(get_current_auth_headers)):
    try:
        user_specific_hdr = core.auth_headers(auth_deps["token"], req.user_id)
        # We can pass an empty list for log_messages as we don't need to return them for a preview.
        items = core.generate_items_from_blocks(req.user_id, req.blocks, user_specific_hdr, [])
        formatted_items = core.format_items_for_preview(items)
        return formatted_items
    except Exception as e:
        logging.error(f"Error generating playlist preview: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"An error occurred while generating the preview: {e}")

@router.post("/api/create_mixed_playlist")
def api_create_mixed_playlist(req: models.MixedPlaylistRequest, auth_deps: dict = Depends(get_current_auth_headers)):
    user_specific_hdr = core.auth_headers(auth_deps["token"], req.user_id)
    result = {}
    if req.create_as_collection:
        if not req.blocks or len(req.blocks) != 1 or req.blocks[0].get("type") != "movie":
            raise HTTPException(400, "Collections can only be created from a single movie block.")

        movie_filters = req.blocks[0].get("filters", {})
        result = core.create_movie_collection(
            user_id=req.user_id,
            collection_name=req.playlist_name,
            filters=movie_filters,
            hdr=user_specific_hdr
        )
    else:
        if not req.blocks:
             raise HTTPException(400, "No blocks provided for playlist creation.")
        result = core.create_mixed_playlist(
            user_id=req.user_id,
            playlist_name=req.playlist_name,
            blocks=req.blocks,
            hdr=user_specific_hdr
        )

    if new_item_id := result.get("new_item_id"):
        result["newItemUrl"] = _construct_item_url(new_item_id)

    return result


@router.post("/api/playlists/{playlist_id}/add-items")
def api_add_items_to_playlist(playlist_id: str, req: models.AddItemsRequest, auth_deps: dict = Depends(get_current_auth_headers)):
    try:
        user_specific_hdr = core.auth_headers(auth_deps["token"], req.user_id)
        result = core.add_items_to_playlist(
            user_id=req.user_id,
            playlist_id=playlist_id,
            blocks=req.blocks,
            hdr=user_specific_hdr
        )
        return result
    except Exception as e:
        logging.error(f"Error adding items to playlist {playlist_id}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))