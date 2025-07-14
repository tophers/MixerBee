import logging
from fastapi import APIRouter, HTTPException

import app as core
import models
import app_state
import gemini_client

router = APIRouter()

def get_auth_dependencies():
    """Dependency to ensure the app is configured and to get headers."""
    if not app_state.is_configured:
        raise HTTPException(status_code=400, detail="Application is not configured.")
    return {
        "login_uid": app_state.login_uid,
        "token": app_state.token,
        "HDR": app_state.HDR
    }

@router.post("/api/create_from_text")
def api_create_from_text(req: models.AiPromptRequest):
    auth_deps = get_auth_dependencies()
    if not app_state.GEMINI_API_KEY:
        raise HTTPException(status_code=501, detail="Gemini API key is not configured on the server.")

    try:
        available_shows = [s['Name'] for s in core.search_series("", auth_deps["HDR"])]
        available_genres = [g['Name'] for g in core.get_movie_genres(auth_deps["login_uid"], auth_deps["HDR"])]
        blocks = gemini_client.generate_blocks_from_prompt(
            prompt=req.prompt,
            api_key=app_state.GEMINI_API_KEY,
            available_shows=available_shows,
            available_genres=available_genres
        )
        
        # Post-process blocks to resolve person names to full objects with IDs
        for block in blocks:
            if block.get("type") == "movie":
                filters = block.get("filters", {})
                
                # Resolve people names to full person objects
                for person_key in ["people", "exclude_people"]:
                    if person_key in filters and filters[person_key]:
                        resolved_people = []
                        for person_info in filters[person_key]:
                            if person_info.get("Name"):
                                # Search for the person by name, take the first result
                                found_people = core.get_people(person_info["Name"], auth_deps["HDR"])
                                if found_people:
                                    resolved_people.append(found_people[0])
                        filters[person_key] = resolved_people

        return {"status": "ok", "blocks": blocks}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/api/movies/preview_count")
def api_movies_preview_count(req: models.MovieFinderRequest):
    auth_deps = get_auth_dependencies()
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
def api_music_preview_count(req: models.MusicFinderRequest):
    auth_deps = get_auth_dependencies()
    try:
        user_specific_hdr = core.auth_headers(auth_deps["token"], req.user_id)
        filters = req.filters.copy()
        filters['limit'] = None
        found_songs = core.find_songs(user_id=req.user_id, filters=filters, hdr=user_specific_hdr)
        return {"count": len(found_songs)}
    except Exception as e:
        raise HTTPException(400, str(e))

@router.post("/api/create_mixed_playlist")
def api_create_mixed_playlist(req: models.MixedPlaylistRequest):
    auth_deps = get_auth_dependencies()
    user_specific_hdr = core.auth_headers(auth_deps["token"], req.user_id)
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

@router.post("/api/playlists/{playlist_id}/add-items")
def api_add_items_to_playlist(playlist_id: str, req: models.AddItemsRequest):
    auth_deps = get_auth_dependencies()
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