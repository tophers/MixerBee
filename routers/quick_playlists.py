from fastapi import APIRouter, HTTPException

import app as core
import models
import app_state

router = APIRouter()

# Map the quick build 'type' from the frontend to the backend function
# and the keys for options that the function expects.
QUICK_BUILD_MAP = {
    "recently_added": (core.create_recently_added_playlist, ['count']),
    "next_up": (core.create_continue_watching_playlist, ['count']),
    "pilot_sampler": (core.create_pilot_sampler_playlist, ['count']),
    "from_the_vault": (core.create_forgotten_favorites_playlist, ['count']),
    "genre_roulette": (core.create_movie_marathon_playlist, ['genre', 'count']),
    "artist_spotlight": (core.create_artist_spotlight_playlist, ['artist_id', 'count']),
    "album_roulette": (core.create_album_playlist, ['album_id']),
    "genre_sampler": (core.create_music_genre_playlist, ['genre', 'count']),
}


@router.post("/api/quick_builds")
def api_quick_builds(req: models.QuickBuildRequest):
    """Handles all 'Smart Build' requests from a single, unified endpoint."""
    if not app_state.is_configured:
        raise HTTPException(status_code=400, detail="Not configured")

    build_type = req.quick_build_type
    if build_type not in QUICK_BUILD_MAP:
        raise HTTPException(status_code=400, detail=f"Unknown quick_build_type: {build_type}")

    func_to_call, expected_options = QUICK_BUILD_MAP[build_type]

    # Prepare arguments for the function call
    kwargs = {
        "user_id": req.user_id,
        "playlist_name": req.playlist_name,
        "hdr": core.auth_headers(app_state.token, req.user_id),
        "log": []
    }

    # Extract required options from the request body's 'options' dict
    # This also validates that the required options are present.
    for option_key in expected_options:
        if option_key not in req.options:
            raise HTTPException(status_code=400, detail=f"Missing required option '{option_key}' for build type '{build_type}'")
        kwargs[option_key] = req.options[option_key]

    try:
        # Dynamically call the correct core function with the prepared arguments
        result = func_to_call(**kwargs)
        return result
    except Exception as e:
        # This will catch issues from the core functions, like API errors
        raise HTTPException(status_code=500, detail=str(e))