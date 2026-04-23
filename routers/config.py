"""
routers/config.py – APIRouter
"""

import logging
import os
import sys
import threading
import time
import requests
import json
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
        "ollama_model": app_state.OLLAMA_MODEL,
        "starred_models": app_state.STARRED_MODELS
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
        "starred_models": app_state.STARRED_MODELS,
        "version": core.CLIENT_VERSION
    }

@router.get("/api/ollama/status")
def api_ollama_status():
    """Proxies request to Ollama to get installed and running models."""
    if not app_state.OLLAMA_URL:
        raise HTTPException(status_code=400, detail="Ollama URL not configured")
    
    try:
        tags_resp = requests.get(f"{app_state.OLLAMA_URL}/api/tags", timeout=5)
        tags_data = tags_resp.json() if tags_resp.ok else {"models": []}
        
        ps_resp = requests.get(f"{app_state.OLLAMA_URL}/api/ps", timeout=5)
        ps_data = ps_resp.json() if ps_resp.ok else {"models": []}
        
        return {
            "installed": tags_data.get("models", []),
            "running": ps_data.get("models", [])
        }
    except Exception as e:
        logging.error(f"Failed to fetch Ollama status: {e}")
        return {"installed": [], "running": [], "error": str(e)}

@router.post("/api/settings/model")
def api_update_active_model(req: models.ModelUpdateRequest):
    """Snappy update for just the active Ollama model without restart."""
    app_state.OLLAMA_MODEL = req.ollama_model
    with database.get_db_connection() as conn:
        conn.execute("INSERT OR REPLACE INTO settings (key, value) VALUES ('OLLAMA_MODEL', ?)", (req.ollama_model,))
        conn.commit()
    return {"status": "ok", "model": req.ollama_model}

@router.post("/api/settings/test")
def api_test_settings(req: models.SettingsRequest):
    """Temporary authentication attempt to verify credentials without saving."""
    try:
        uid, token = core.authenticate(
            req.emby_user.strip(),
            req.emby_pass,
            req.emby_url.strip(),
            req.server_type
        )

        hdr = core.auth_headers(token, uid)
        is_valid, status = core.client.test_connection(hdr)

        if is_valid:
            return {"status": "ok", "log": ["Connection successful! Credentials and URL verified."]}
        else:
            return {"status": "error", "log": [f"Server reached, but returned unexpected status: {status}"]}

    except Exception as e:
        logging.error(f"Settings test failed: {e}")
        return {"status": "error", "log": [f"Connection failed: {str(e)}"]}

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
        "GEMINI_API_KEY": req.gemini_key.strip() if req.gemini_key else "",
        "STARRED_MODELS": json.dumps(req.starred_models or [])
    }

    try:
        core.authenticate(req.emby_user, req.emby_pass, req.emby_url, req.server_type)

        with database.get_db_connection() as conn:
            for k, v in settings_dict.items():
                conn.execute("INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)", (k, v))

            env_keys = ["SERVER_TYPE", "EMBY_URL", "EMBY_USER", "EMBY_PASS", "AI_PROVIDER", "OLLAMA_URL", "OLLAMA_MODEL", "GEMINI_API_KEY"]
            env_content = "\n".join([f'{k}="{settings_dict[k]}"' for k in env_keys if settings_dict.get(k) is not None])

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