"""
config.py – APIRouter
"""

import logging
import os
import sys
import threading
import time
from fastapi import APIRouter, HTTPException, Depends
from fastapi.responses import JSONResponse

import app as core
import models
import app_state

router = APIRouter()

def _trigger_restart(delay: int = 2):
    """
    Waits for a delay then replaces the current process with a new one,
    effectively restarting the application.
    """
    time.sleep(delay)
    logging.warning("RESTART: Triggering application restart after initial configuration.")
    os.execv(sys.executable, [sys.executable] + sys.argv)


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
    # Check if the app was unconfigured *before* we try to save.
    was_unconfigured = not app_state.is_configured

    env_content = (
        f'SERVER_TYPE="{req.server_type}"\n'
        f'EMBY_URL="{req.emby_url}"\n'
        f'EMBY_USER="{req.emby_user}"\n'
        f'EMBY_PASS="{req.emby_pass}"\n'
    )
    if req.gemini_key:
        env_content += f'GEMINI_API_KEY="{req.gemini_key}"\n'

    try:
        # First, test if the new credentials are valid before saving.
        core.authenticate(req.emby_user, req.emby_pass, req.emby_url, req.server_type)

        with open(app_state.ENV_PATH, "w") as f:
            f.write(env_content)

        # If this was the first time being configured, trigger a restart.
        # This is done in a background thread to allow the HTTP response to be sent first.
        if was_unconfigured:
            restart_thread = threading.Thread(target=_trigger_restart, daemon=True)
            restart_thread.start()

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