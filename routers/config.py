"""
config.py – APIRouter
"""

import logging
from fastapi import APIRouter, HTTPException, Depends
from fastapi.responses import JSONResponse

import app as core
import models
import app_state

router = APIRouter()

@router.get("/api/config_status")
def api_config_status():
    return {
        "is_configured": app_state.is_configured,
        "is_ai_configured": bool(app_state.GEMINI_API_KEY),
        "server_type": app_state.SERVER_TYPE
    }

@router.post("/api/settings")
def api_save_settings(req: models.SettingsRequest):
    """Saves connection details and hot-swaps the active configuration."""
    env_content = (
        f'SERVER_TYPE="{req.server_type}"\n'
        f'EMBY_URL="{req.emby_url}"\n'
        f'EMBY_USER="{req.emby_user}"\n'
        f'EMBY_PASS="{req.emby_pass}"\n'
    )
    if req.gemini_key:
        env_content += f'GEMINI_API_KEY="{req.gemini_key}"\n'

    try:
        core.authenticate(req.emby_user, req.emby_pass, req.emby_url, req.server_type)

        with open(app_state.ENV_PATH, "w") as f:
            f.write(env_content)

        app_state.load_and_authenticate()

        return {
            "status": "ok",
            "log": ["Settings saved and applied successfully! The page will now reload."]
        }
    except Exception as e:
        logging.error(f"Failed to save settings: {e}", exc_info=True)
        error_detail = "Could not authenticate with the provided credentials. Please check the server type, URL, username, and password."
        raise HTTPException(status_code=400, detail=error_detail)


@router.post("/api/settings/test")
def api_test_settings():
    """Tests the currently loaded .env configuration."""
    if not app_state.is_configured:
        return JSONResponse(
            status_code=400,
            content={"status": "error", "log": ["Application is not configured."]}
        )
    try:
        # Pass the currently configured server type to the test
        core.authenticate(core.EMBY_USER, core.EMBY_PASS, core.EMBY_URL, app_state.SERVER_TYPE)
        return {"status": "ok", "log": [f"{app_state.SERVER_TYPE.capitalize()} connection test successful!"]}
    except Exception as e:
        logging.error(f"Failed to test settings: {e}", exc_info=True)
        return JSONResponse(
            status_code=400,
            content={"status": "error", "log": ["Connection test failed. Check .env file and server status."]}
        )