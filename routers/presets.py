"""
presets.py – APIRouter
"""

import logging
from typing import Dict, List
from fastapi import APIRouter, HTTPException, status, Body

import preset_manager as pm
from models import MixedPlaylistRequest 

router = APIRouter()

@router.get("/api/presets", response_model=Dict[str, List[Dict]])
def api_get_presets():
    """Returns all saved presets."""
    return pm.preset_manager.get_all_presets()

@router.post("/api/presets", status_code=status.HTTP_201_CREATED)
def api_save_preset(payload: Dict = Body(...)):
    """Saves a new preset or overwrites an existing one."""
    preset_name = payload.get("name")
    preset_data = payload.get("data")
    if not preset_name or not isinstance(preset_data, list):
        raise HTTPException(status_code=400, detail="Invalid payload. 'name' and 'data' are required.")

    success = pm.preset_manager.save_preset(preset_name, preset_data)
    if success:
        return {"status": "ok", "log": [f"Preset '{preset_name}' saved."]}
    
    raise HTTPException(status_code=500, detail="Failed to save preset.")


@router.delete("/api/presets/{preset_name}", status_code=status.HTTP_200_OK)
def api_delete_preset(preset_name: str):
    """Deletes a preset by its name."""
    success = pm.preset_manager.delete_preset(preset_name)
    if success:
        return {"status": "ok", "log": [f"Preset '{preset_name}' deleted."]}
    
    return {"status": "ok", "log": [f"Preset '{preset_name}' not found or already deleted."]}