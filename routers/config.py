"""
routers/config.py – APIRouter
"""

import logging
import os
import sys
import threading
import time
from fastapi import APIRouter, HTTPException
from fastapi.responses import JSONResponse

import app as core
import models
import app_state
import database

router = APIRouter()

def _trigger_restart(delay: int = 2):
    time.sleep(delay)
    logging.warning("RESTART: Re-executing process.")
    os.execv(sys.executable, [sys.executable] + sys.argv)

@router.get("/api/config_status")
def api_config_status():
    if not app_state.is_configured:
        app_state.load_and_authenticate()

    return {
        "is_configured": app_state.is_configured,
        "is_ai_configured": bool(app_state.GEMINI_API_KEY or app_state.AI_PROVIDER == "ollama"),
        "server_type": app_state.SERVER_TYPE,
        "version": core.CLIENT_VERSION,
        "ai_provider": app_state.AI_PROVIDER,
        "ollama_model": app_state.OLLAMA_MODEL
    }

@router.get("/api/settings")
def api_get_settings():
    """Returns the current runtime settings to populate the UI."""
    return {
        "server_type": app_state.SERVER_TYPE or "emby",
        "emby_url": core.EMBY_URL or "",
        "emby_user": core.EMBY_USER or "",
        "emby_pass": core.EMBY_PASS or "",
        "ai_provider": app_state.AI_PROVIDER or "gemini",
        "gemini_key": app_state.GEMINI_API_KEY or "",
        "ollama_url": app_state.OLLAMA_URL or "http://localhost:11434",
        "ollama_model": app_state.OLLAMA_MODEL or "qwen2.5:7b",
        "version": core.CLIENT_VERSION
    }

@router.post("/api/settings")
def api_save_settings(req: models.SettingsRequest):
    """Saves settings to both .env and the database."""

    settings_dict = {
        "SERVER_TYPE": req.server_type,
        "EMBY_URL": req.emby_url.strip(),
        "EMBY_USER": req.emby_user.strip(),
        "EMBY_PASS": req.emby_pass,
        "AI_PROVIDER": req.ai_provider,
        "OLLAMA_URL": req.ollama_url.strip(),
        "OLLAMA_MODEL": req.ollama_model.strip(),
        "GEMINI_API_KEY": req.gemini_key.strip() if req.gemini_key else ""
    }

    try:
        core.authenticate(req.emby_user, req.emby_pass, req.emby_url, req.server_type)

        with database.get_db_connection() as conn:
            for k, v in settings_dict.items():
                conn.execute("INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)", (k, v))
            
            env_content = "\n".join([f'{k}="{v}"' for k, v in settings_dict.items() if v is not None])
            new_hash = "".join([f"{k}{v}" for k, v in settings_dict.items()]).encode('utf-8')
            
            with open(app_state.ENV_PATH, "w") as f:
                f.write(env_content)
            
            final_hash = app_state.get_env_hash()
            conn.execute("INSERT OR REPLACE INTO settings (key, value) VALUES ('env_hash', ?)", (final_hash,))
            conn.commit()

        threading.Thread(target=_trigger_restart, daemon=True).start()

        return {"status": "ok", "log": ["Settings saved. Application restarting..."]}
    except Exception as e:
        logging.error(f"Save failed: {e}")
        raise HTTPException(status_code=400, detail=f"Failed to authenticate or save: {str(e)}")