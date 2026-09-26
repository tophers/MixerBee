"""
routers/quick_playlists.py – APIRouter
"""

from fastapi import APIRouter, HTTPException, Depends

import app as core
import models
import app_state
from quick_playlist_registry import QUICK_BUILD_MAP, get_public_registry
from .dependencies import get_current_auth_headers, media_for_user

router = APIRouter()

@router.get("/api/quick_builds/types")
def api_get_quick_build_types():
    """Returns all supported quick playlist / smart build types with schema and schedulability metadata."""
    return get_public_registry()

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
        "media": media_for_user(auth_deps, req.user_id),
        "log": []
    }

    for option_key in expected_options:
        if option_key not in req.options:
            raise HTTPException(status_code=400, detail=f"Missing required option '{option_key}' for build type '{build_type}'")
        kwargs[option_key] = req.options[option_key]

    try:
        result = func_to_call(**kwargs)

        if new_item_id := result.get("new_item_id"):
            result["newItemUrl"] = core.construct_item_url(new_item_id, auth_deps["media"])

        return result
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))