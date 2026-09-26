"""
routers/presets.py – APIRouter with Cache Control
"""

import logging
from typing import Dict, List
from fastapi import APIRouter, HTTPException, status, Body, Depends
from fastapi.responses import JSONResponse

import preset_manager as pm
from models import MixedPlaylistRequest, ExternalPromptRequest
from .dependencies import get_current_auth_headers

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

@router.post("/api/presets", status_code=status.HTTP_201_CREATED)
def api_save_preset(payload: Dict = Body(...), auth_deps: dict = Depends(get_current_auth_headers)):
    """Saves a new preset or overwrites an existing one."""
    preset_name = payload.get("name")
    preset_data = payload.get("data")
    if not preset_name or not isinstance(preset_data, list):
        raise HTTPException(status_code=400, detail="Invalid payload. 'name' and 'data' are required.")

    preset_id = pm.preset_manager.save_preset(preset_name, preset_data, auth_deps["connection_id"])
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
    """
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
