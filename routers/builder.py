"""
routers/builder.py – APIRouter
"""

import logging
import random
from typing import Dict, List, Optional
from fastapi import APIRouter, HTTPException, Depends

import app as core
import models
import app_state
from app.cache import get_library_data
from app.ai import generate_smart_blocks
from preset_manager import preset_manager
from .dependencies import get_current_auth_headers, media_for_user, require_collection_permission, require_generative_ai

router = APIRouter()

def _get_random_movie_block(media) -> Dict:
    cached_data = get_library_data(media)
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
        start_year = random.choice([1970, 1980, 1990, 2000, 2010, 2020])
        filters["year_from"] = start_year
        filters["year_to"] = start_year + 9

    return {"type": "movie", "filters": filters}

def _get_random_tv_block(media) -> Dict:
    cached_data = get_library_data(media)
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

def _get_random_music_block(media) -> Dict:
    cached_data = get_library_data(media)
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

@router.get("/api/builder/random_block", response_model=Dict)
def api_get_random_block(auth_deps: dict = Depends(get_current_auth_headers)):
    block_generators = {
        "movie": _get_random_movie_block,
        "tv": _get_random_tv_block,
        "music": _get_random_music_block
    }

    lib_data = get_library_data(auth_deps["media"])
    possible_block_types = [
        block_type for block_type, generator in block_generators.items()
        if (generator is not _get_random_tv_block or lib_data.get("seriesData"))
        and (generator is not _get_random_music_block or lib_data.get("artistData") or lib_data.get("musicGenreData"))
    ]
    if not possible_block_types:
        raise HTTPException(status_code=404, detail="Not enough library data to generate a random block.")

    chosen_type = random.choice(possible_block_types)
    random_block = block_generators[chosen_type](auth_deps["media"])

    if not random_block:
         raise HTTPException(status_code=500, detail=f"Failed to generate a random '{chosen_type}' block.")

    return random_block

@router.post("/api/create_from_text")
def api_create_from_text(req: models.AiPromptRequest, auth_deps: dict = Depends(get_current_auth_headers)):
    # One shared check replaces the old per-endpoint provider reading, which disagreed
    # with the other two and could not see the account-wide switch at all.
    require_generative_ai(auth_deps)

    try:
        blocks, model_used, logs = generate_smart_blocks(req.prompt, req.tweaks, req.existing_blocks, media=auth_deps["media"])

        for block in blocks:
            if block.get("type") == "movie" and "filters" in block:
                filters = block["filters"]
                for person_key in ["people", "exclude_people"]:
                    if person_key in filters and filters[person_key]:
                        resolved_people = []
                        for person_info in filters[person_key]:
                            if name := person_info.get("Name"):
                                found_people = core.get_people(name, auth_deps["media"])
                                if found_people:
                                    resolved_people.append(found_people[0])
                        filters[person_key] = resolved_people

        return {
            "status": "ok",
            "blocks": blocks,
            "model_used": model_used,
            "log": logs if logs else [f"Successfully generated using {model_used}."]
        }
    except HTTPException:
        raise
    except Exception as e:
        logging.error("Failed to generate from text", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/api/movies/preview_count")
def api_movies_preview_count(req: models.MovieFinderRequest, auth_deps: dict = Depends(get_current_auth_headers)):
    try:
        media = media_for_user(auth_deps, req.user_id)
        filters = req.filters.copy()
        filters['duration_minutes'] = None
        filters['limit'] = None
        found_movies = core.find_movies(user_id=req.user_id, filters=filters, media=media)
        return {"count": len(found_movies)}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(400, str(e))

@router.post("/api/music/preview_count")
def api_music_preview_count(req: models.MusicFinderRequest, auth_deps: dict = Depends(get_current_auth_headers)):
    try:
        media = media_for_user(auth_deps, req.user_id)
        filters = req.filters.copy()
        filters['limit'] = None
        found_songs = core.find_songs(user_id=req.user_id, filters=filters, media=media)
        return {"count": len(found_songs)}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(400, str(e))

@router.post("/api/builder/preview")
def api_builder_preview(req: models.BuilderPreviewRequest, auth_deps: dict = Depends(get_current_auth_headers)):
    try:
        media = media_for_user(auth_deps, req.user_id)
        resolution = core.resolve_mix(
            user_id=req.user_id,
            blocks=req.blocks,
            media=media,
            mix_options=req.mix_options
        )
        formatted_items = core.format_items_for_preview([r.get("raw_item") or r for r in resolution.rows])

        return {
            "status": "ok",
            "data": formatted_items,
            "rows": resolution.rows,
            "warnings": resolution.warnings,
            "total_duration_ticks": resolution.total_duration_ticks,
            "total_duration_formatted": core.format_duration_ticks(resolution.total_duration_ticks)
        }
    except HTTPException:
        raise
    except Exception as e:
        logging.error(f"Error generating playlist preview: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"An error occurred while generating the preview: {e}")

@router.post("/api/create_mixed_playlist")
def api_create_mixed_playlist(req: models.MixedPlaylistRequest, auth_deps: dict = Depends(get_current_auth_headers)):
    media = media_for_user(auth_deps, req.user_id)
    result = {}
    
    if req.item_ids:
        new_item_id = core.create_playlist(
            name=req.playlist_name,
            user_id=req.user_id,
            ids=req.item_ids,
            media=media,
            log=[]
        )
        result = {"status": "ok" if new_item_id else "error", "new_item_id": new_item_id, "log": ["Playlist created from custom order."]}
    
    elif req.create_as_collection:
        require_collection_permission(media)
        if not req.blocks or len(req.blocks) != 1 or (req.blocks[0].get("type") != "movie" and req.blocks[0].get("vibe_type") != "movie"):
            raise HTTPException(400, "Collections can only be created from a single movie block.")

        movie_filters = req.blocks[0].get("filters", {})
        result = core.create_movie_collection(
            user_id=req.user_id,
            collection_name=req.playlist_name,
            filters=movie_filters,
            media=media
        )
    else:
        if not req.blocks:
             raise HTTPException(400, "No blocks provided for playlist creation.")
        result = core.create_mixed_playlist(
            user_id=req.user_id,
            playlist_name=req.playlist_name,
            blocks=req.blocks,
            media=media,
            mix_options=req.mix_options
        )

    if new_item_id := result.get("new_item_id"):
        result["newItemUrl"] = core.construct_item_url(new_item_id, auth_deps["media"])

    return result

@router.post("/api/playlists/{playlist_id}/add-items")
def api_add_items_to_playlist(playlist_id: str, req: models.AddItemsRequest, auth_deps: dict = Depends(get_current_auth_headers)):
    try:
        media = media_for_user(auth_deps, req.user_id)
        result = core.add_items_to_playlist(
            user_id=req.user_id,
            playlist_id=playlist_id,
            blocks=req.blocks,
            media=media,
            mix_options=req.mix_options
        )
        return result
    except HTTPException:
        raise
    except Exception as e:
        logging.error(f"Error adding items to playlist {playlist_id}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/api/external/build_preset", response_model=Dict)
def api_external_build_preset(req: models.ExternalBuildRequest, auth_deps: dict = Depends(get_current_auth_headers)):
    """
    External API Endpoint: Loads a preset and creates a mixed playlist.
    """
    try:
        all_presets = preset_manager.get_all_presets(auth_deps["connection_id"])
        blocks = all_presets.get(req.preset_name)
        
        if not blocks:
            raise HTTPException(status_code=404, detail=f"Preset '{req.preset_name}' not found.")

        media = media_for_user(auth_deps, auth_deps["login_uid"])
        
        result = core.create_mixed_playlist(
            user_id=auth_deps["login_uid"],
            playlist_name=req.playlist_name,
            blocks=blocks,
            media=media
        )

        if new_item_id := result.get("new_item_id"):
            result["newItemUrl"] = core.construct_item_url(new_item_id, auth_deps["media"])

        return result

    except HTTPException:
        raise
    except Exception as e:
        logging.error(f"External build_preset failed for preset '{req.preset_name}'", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/api/build_runs")
@router.get("/api/build-runs")
def api_get_build_runs(
    limit: int = 50,
    preset_id: Optional[str] = None,
    schedule_id: Optional[str] = None,
    operation: Optional[str] = None,
    auth_deps: dict = Depends(get_current_auth_headers)
):
    runs = core.build_history.get_recent_build_runs(
        connection_id=auth_deps["connection_id"],
        limit=limit,
        preset_id=preset_id,
        schedule_id=schedule_id,
        operation=operation
    )
    return {"status": "ok", "runs": runs}

@router.get("/api/build_runs/{run_id}")
@router.get("/api/build-runs/{run_id}")
def api_get_build_run_detail(
    run_id: str,
    auth_deps: dict = Depends(get_current_auth_headers)
):
    detail = core.build_history.get_build_run_detail(run_id, auth_deps["connection_id"])
    if not detail:
        raise HTTPException(status_code=404, detail=f"Build run '{run_id}' not found.")
    return {"status": "ok", "run": detail}

@router.get("/api/build_runs/{run_id}/diff/{compare_run_id}")
@router.get("/api/build-runs/{run_id}/diff/{compare_run_id}")
def api_diff_build_runs(
    run_id: str,
    compare_run_id: str,
    auth_deps: dict = Depends(get_current_auth_headers)
):
    run_a = core.build_history.get_build_run_detail(run_id, auth_deps["connection_id"])
    if not run_a:
        raise HTTPException(status_code=404, detail=f"Build run '{run_id}' not found.")
    run_b = core.build_history.get_build_run_detail(compare_run_id, auth_deps["connection_id"])
    if not run_b:
        raise HTTPException(status_code=404, detail=f"Build run '{compare_run_id}' not found.")

    diff = core.build_history.compute_run_diff(run_a.get("items", []), run_b.get("items", []))
    return {
        "status": "ok",
        "run_id": run_id,
        "compare_run_id": compare_run_id,
        "diff": diff
    }

@router.post("/api/build_runs/{run_id}/replay")
@router.post("/api/build-runs/{run_id}/replay")
def api_replay_build_run(
    run_id: str,
    req: Optional[models.ReplayRunRequest] = None,
    auth_deps: dict = Depends(get_current_auth_headers)
):
    target_user_id = (req.user_id if req and req.user_id else None) or auth_deps["login_uid"]
    media = media_for_user(auth_deps, target_user_id)
    playlist_name = req.playlist_name if req else None
    dry_run = req.dry_run if req else False

    try:
        result = core.build_history.replay_build_run(
            run_id=run_id,
            connection_id=auth_deps["connection_id"],
            user_id=target_user_id,
            media=media,
            playlist_name=playlist_name,
            dry_run=dry_run
        )
        if result.get("status") == "error" and not dry_run and result.get("available_items_count") == 0:
            raise HTTPException(status_code=400, detail=result.get("message", "Replay failed."))
        return result
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except HTTPException:
        raise
    except Exception as e:
        logging.error(f"Error replaying build run {run_id}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))

