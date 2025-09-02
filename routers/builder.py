"""
builder.py – APIRouter
"""

import logging
import random
from typing import Dict, List
from fastapi import APIRouter, HTTPException, Depends

import app as core
import models
import app_state
import gemini_client
from app.cache import get_library_data
from .dependencies import get_current_auth_headers

router = APIRouter()

def _get_random_movie_block() -> Dict:
    """Constructs a randomized movie block."""
    cached_data = get_library_data()
    all_genres = cached_data.get("movieGenreData", [])
    all_libraries = cached_data.get("libraryData", [])

    filters = {
        "watched_status": random.choice(["unplayed", "all"]),
        "sort_by": "Random",
        "parent_ids": [lib["Id"] for lib in all_libraries],
        "limit": random.randint(3, 10)
    }

    if all_genres and random.random() < 0.5:
        chosen_genre = random.choice(all_genres)
        filters["genres_any"] = [chosen_genre["Name"]]

    if random.random() < 0.4:
        start_year = random.choice([1970, 1980, 1990, 2000, 2010])
        filters["year_from"] = start_year
        filters["year_to"] = start_year + 9

    return {"type": "movie", "filters": filters}

def _get_random_tv_block() -> Dict:
    """Constructs a randomized TV block."""
    cached_data = get_library_data()
    all_series = cached_data.get("seriesData", [])
    if not all_series:
        return None

    chosen_show = random.choice(all_series)
    show_object = {
        "name": chosen_show["name"],
        "season": 1,
        "episode": 1,
        "unwatched": random.choice([True, False])
    }

    return {
        "type": "tv",
        "shows": [show_object],
        "mode": "count",
        "count": random.randint(2, 5),
        "interleave": True
    }

def _get_random_music_block() -> Dict:
    """Constructs a randomized music block."""
    cached_data = get_library_data()
    all_artists = cached_data.get("artistData", [])
    all_genres = cached_data.get("musicGenreData", [])

    possible_modes = []
    if all_artists:
        possible_modes.extend(["artist_top", "artist_random"])
    if all_genres:
        possible_modes.append("genre")

    if not possible_modes:
        return None

    mode = random.choice(possible_modes)
    music_data = {"mode": mode}

    if mode.startswith("artist"):
        chosen_artist = random.choice(all_artists)
        music_data["artistId"] = chosen_artist["Id"]
        music_data["count"] = random.choice([10, 15, 20])
    elif mode == "genre":
        chosen_genre = random.choice(all_genres)
        music_data["filters"] = {
            "genres": [chosen_genre["Name"]],
            "sort_by": "Random",
            "limit": random.choice([15, 25, 50])
        }

    return {"type": "music", "music": music_data}

def _construct_item_url(item_id: str) -> str:
    """Helper to construct the correct Emby/Jellyfin URL for an item."""
    if not item_id:
        return None
    base_url = core.EMBY_URL.rstrip("/")
    if app_state.SERVER_TYPE == 'jellyfin':
        return f"{base_url}/web/index.html#!/details?id={item_id}"
    else:
        url = f"{base_url}/web/index.html#!/item?id={item_id}"
        if app_state.SERVER_ID:
            url += f"&serverId={app_state.SERVER_ID}"
        return url

# --- API Endpoints ---
@router.get("/api/builder/random_block", response_model=Dict)
def api_get_random_block(auth_deps: dict = Depends(get_current_auth_headers)):
    """Generates a single, randomized block for the 'Surprise Me' feature."""

    block_generators = {
        "movie": _get_random_movie_block,
        "tv": _get_random_tv_block,
        "music": _get_random_music_block
    }

    possible_block_types = [
        block_type for block_type, generator in block_generators.items()
        if generator is not _get_random_tv_block or get_library_data().get("seriesData")
    ]
    if not possible_block_types:
        raise HTTPException(status_code=404, detail="Not enough library data to generate a random block.")

    chosen_type = random.choice(possible_block_types)
    random_block = block_generators[chosen_type]()

    if not random_block:
         raise HTTPException(status_code=500, detail=f"Failed to generate a random '{chosen_type}' block.")

    return random_block


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
        items = core.generate_items_from_blocks(req.user_id, req.blocks, user_specific_hdr, [])
        formatted_items = core.format_items_for_preview(items)
        return {"status": "ok", "data": formatted_items}
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