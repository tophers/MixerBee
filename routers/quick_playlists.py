"""
quick_playlists.py – APIRouter
"""

from fastapi import APIRouter, HTTPException, Depends

import app as core
import models
import app_state
from .dependencies import get_current_auth_headers

router = APIRouter()

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


@router.post("/api/quick_builds")
def api_quick_builds(req: models.QuickBuildRequest, auth_deps: dict = Depends(get_current_auth_headers)):
    """Handles all 'Smart Build' requests from a single, unified endpoint."""
    build_type = req.quick_build_type
    if build_type not in QUICK_BUILD_MAP:
        raise HTTPException(status_code=400, detail=f"Unknown quick_build_type: {build_type}")

    func_to_call, expected_options = QUICK_BUILD_MAP[build_type]

    kwargs = {
        "user_id": req.user_id,
        "playlist_name": req.playlist_name,
        "hdr": core.auth_headers(auth_deps["token"], req.user_id),
        "log": []
    }

    for option_key in expected_options:
        if option_key not in req.options:
            raise HTTPException(status_code=400, detail=f"Missing required option '{option_key}' for build type '{build_type}'")
        kwargs[option_key] = req.options[option_key]

    try:
        result = func_to_call(**kwargs)

        if new_item_id := result.get("new_item_id"):
            result["newItemUrl"] = _construct_item_url(new_item_id)

        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))