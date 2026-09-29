"""
routers/presets.py – APIRouter with Cache Control
"""

import logging
from typing import Dict, List
from fastapi import APIRouter, HTTPException, status, Body, Depends
from fastapi.responses import JSONResponse

import preset_manager as pm
from models import MixedPlaylistRequest, ExternalPromptRequest
from .dependencies import get_current_auth_headers, require_generative_ai

router = APIRouter()

@router.get("/api/presets")
def api_get_presets(auth_deps: dict = Depends(get_current_auth_headers)):
    """Returns all saved presets with no-cache headers to ensure external API updates show up."""
    data = pm.preset_manager.get_all_presets(auth_deps["connection_id"])
    return JSONResponse(
        content=data,
        headers={
            "Cache-Control": "no-cache, no-store, must-revalidate",
            "Pragma": "no-cache",
            "Expires": "0",
        }
    )

@router.get("/api/presets/catalog")
def api_get_preset_catalog(auth_deps: dict = Depends(get_current_auth_headers)):
    """Returns stable IDs with preset names and data for first-party clients."""
    return JSONResponse(
        content=pm.preset_manager.get_preset_records(auth_deps["connection_id"]),
        headers={"Cache-Control": "no-cache, no-store, must-revalidate", "Pragma": "no-cache", "Expires": "0"}
    )

STARTER_RECIPES = [
    {
        "id": "starter_unwatched_movies",
        "name": "Unwatched Movie Showcase",
        "description": "Picks 5 unwatched movies sorted at random.",
        "tags": ["movies", "unwatched"],
        "is_favorite": True,
        "block": {
            "type": "movie",
            "filters": {
                "watched_status": "unplayed",
                "sort_by": "Random",
                "limit": 5
            }
        }
    },
    {
        "id": "starter_next_up_tv",
        "name": "Next-Up TV Sampler",
        "description": "Plays the next unwatched episode for your shows.",
        "tags": ["tv", "unwatched"],
        "is_favorite": False,
        "block": {
            "type": "tv",
            "mode": "count",
            "count": 1,
            "interleave": True,
            "shows": []
        }
    },
    {
        "id": "starter_critic_favorites",
        "name": "Top Critic Movies",
        "description": "Highest critic-rated unwatched movies.",
        "tags": ["movies", "critic"],
        "is_favorite": False,
        "block": {
            "type": "movie",
            "filters": {
                "watched_status": "unplayed",
                "sort_by": "CriticRating",
                "limit": 5
            }
        }
    }
]

@router.get("/api/recipes/starters")
def api_get_starter_recipes():
    """Returns the catalog of starter recipes."""
    return JSONResponse(content=STARTER_RECIPES)

@router.get("/api/recipes")
def api_get_recipes(query: str = None, tag: str = None, favorites_only: bool = False, auth_deps: dict = Depends(get_current_auth_headers)):
    """Returns connection recipes matching optional query or tag filters."""
    recipes = pm.preset_manager.list_recipes(auth_deps["connection_id"], query=query, tag=tag, favorites_only=favorites_only)
    return JSONResponse(content=recipes)

@router.post("/api/recipes", status_code=status.HTTP_201_CREATED)
def api_save_recipe(payload: Dict = Body(...), auth_deps: dict = Depends(get_current_auth_headers)):
    """Saves or updates a reusable block recipe."""
    name = payload.get("name")
    block_def = payload.get("block") or payload.get("block_json")
    if not name or not block_def:
        raise HTTPException(status_code=400, detail="'name' and 'block' definition are required.")
    
    recipe_id = pm.preset_manager.save_recipe(
        connection_id=auth_deps["connection_id"],
        name=name.strip(),
        block_def=block_def,
        description=payload.get("description", ""),
        tags=payload.get("tags", []),
        is_favorite=bool(payload.get("is_favorite", False)),
        recipe_id=payload.get("id") or payload.get("recipe_id")
    )
    if recipe_id:
        return {"status": "ok", "recipe_id": recipe_id}
    raise HTTPException(status_code=500, detail="Failed to save recipe.")

@router.delete("/api/recipes/{recipe_id}")
def api_delete_recipe(recipe_id: str, auth_deps: dict = Depends(get_current_auth_headers)):
    """Deletes an owned recipe."""
    success = pm.preset_manager.delete_recipe(recipe_id, auth_deps["connection_id"])
    return {"status": "ok" if success else "error"}

@router.patch("/api/presets/{preset_id}")
def api_update_preset(preset_id: str, payload: Dict = Body(...), auth_deps: dict = Depends(get_current_auth_headers)):
    """Updates preset metadata (tags, favorite) or renames the preset while preserving stable ID."""
    conn_id = auth_deps["connection_id"]
    new_name = payload.get("name")
    if new_name:
        success = pm.preset_manager.rename_preset(preset_id, conn_id, new_name)
        if not success:
            raise HTTPException(status_code=400, detail="Failed to rename preset.")

    tags = payload.get("tags")
    is_favorite = payload.get("is_favorite")
    if tags is not None or is_favorite is not None:
        pm.preset_manager.update_preset_metadata(preset_id, conn_id, tags=tags, is_favorite=is_favorite)

    return {"status": "ok"}

@router.post("/api/presets", status_code=status.HTTP_201_CREATED)
def api_save_preset(payload: Dict = Body(...), auth_deps: dict = Depends(get_current_auth_headers)):
    """Saves a new preset or overwrites an existing one with envelope support."""
    preset_name = payload.get("name")
    preset_data = payload.get("data")
    mix_options = payload.get("mix_options")
    tags = payload.get("tags")
    is_favorite = payload.get("is_favorite")

    if not preset_name:
        raise HTTPException(status_code=400, detail="Invalid payload. 'name' is required.")

    if isinstance(preset_data, dict) and "blocks" in preset_data:
        mix_options = mix_options or preset_data.get("mix_options")
        blocks = preset_data["blocks"]
    elif isinstance(preset_data, list):
        blocks = preset_data
    else:
        raise HTTPException(status_code=400, detail="Invalid payload. 'data' must be a list of blocks or an envelope with 'blocks'.")

    preset_id = pm.preset_manager.save_preset(
        preset_name=preset_name,
        preset_data=blocks,
        connection_id=auth_deps["connection_id"],
        mix_options=mix_options,
        tags=tags,
        is_favorite=is_favorite
    )
    if preset_id:
        return {"status": "ok", "preset_id": preset_id, "log": [f"Preset '{preset_name}' saved."]}
    
    raise HTTPException(status_code=500, detail="Failed to save preset.")


def delete_preset_record(record, connection_id):
    if record:
        uses = pm.preset_manager.schedule_usage_count(record['id'], connection_id)
        if uses:
            raise HTTPException(400, f"Preset is used by {uses} schedule(s). Reassign or delete those schedules first.")
        if pm.preset_manager.delete_preset_by_id(record['id'], connection_id):
            return {"status": "ok", "log": [f"Preset '{record['name']}' deleted."]}
    return {"status": "ok", "log": ["Preset not found or already deleted."]}


@router.delete("/api/presets/id/{preset_id}", status_code=status.HTTP_200_OK)
def api_delete_preset_by_id(preset_id: str, auth_deps: dict = Depends(get_current_auth_headers)):
    """Deletes an owned preset by its stable ID."""
    record = pm.preset_manager.get_preset_by_id(preset_id, auth_deps["connection_id"])
    return delete_preset_record(record, auth_deps["connection_id"])


@router.delete("/api/presets/{preset_name}", status_code=status.HTTP_200_OK)
def api_delete_preset(preset_name: str, auth_deps: dict = Depends(get_current_auth_headers)):
    """Compatibility endpoint for deleting a preset by name."""
    record = pm.preset_manager.get_preset_by_name(preset_name, auth_deps["connection_id"])
    return delete_preset_record(record, auth_deps["connection_id"])

@router.post("/api/external/prompt_to_preset", status_code=status.HTTP_201_CREATED)
def api_external_prompt_to_preset(req: ExternalPromptRequest, auth_deps: dict = Depends(get_current_auth_headers)):
    """
    External API Endpoint: Generates blocks from a prompt and saves them as a preset.

    An external API key identifies a connection, not a browser session, so the policy
    is resolved through that connection's owning account -- a key cannot outrank the
    account-wide switch.
    """
    require_generative_ai(auth_deps)
    try:
        from app.ai import generate_smart_blocks
        
        blocks, model_used, logs = generate_smart_blocks(req.prompt, media=auth_deps["media"])
        
        if not blocks and logs:
            raise HTTPException(status_code=404, detail=logs[0])

        success = pm.preset_manager.save_preset(req.preset_name, blocks, auth_deps["connection_id"])
        
        if success:
            return {
                "status": "ok", 
                "log": [f"Preset '{req.preset_name}' created from prompt using {model_used}."],
                "blocks": blocks
            }
        else:
            raise HTTPException(status_code=500, detail="Failed to save preset to database.")
            
    except HTTPException:
        raise
    except Exception as e:
        logging.error("External prompt_to_preset failed", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))
