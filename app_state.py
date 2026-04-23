"""
app_state.py – Manages global configuration
"""

import os
import logging
import hashlib
import json
from pathlib import Path
from dotenv import load_dotenv

import app as core

IS_DOCKER = os.path.exists('/.dockerenv')
if IS_DOCKER:
    CONFIG_DIR = Path("/config")
else:
    CONFIG_DIR = Path(__file__).parent / "config"

ENV_PATH = CONFIG_DIR / ".env"
CONFIG_DIR.mkdir(parents=True, exist_ok=True)

login_uid, token, HDR, is_configured = None, None, {}, False
DEFAULT_USER_NAME, DEFAULT_UID = None, None
GEMINI_API_KEY = None

AI_PROVIDER = "gemini"
OLLAMA_URL = "http://localhost:11434"
OLLAMA_MODEL = "qwen2.5:7b"
OLLAMA_TIMEOUT = 120
STARRED_MODELS = []
VERBOSE_LOGGING = False

CACHE_REFRESH_MINUTES = 15
SERVER_TYPE = "emby"
SERVER_ID = None

def get_env_hash():
    """Calculates an MD5 hash of the .env file to detect manual changes."""
    if not ENV_PATH.exists():
        return ""
    with open(ENV_PATH, "rb") as f:
        return hashlib.md5(f.read()).hexdigest()

def sync_env_to_db():
    """
    Checks if the .env file has changed since the last run.
    If it has, we push the .env values into the database.
    """
    import database

    current_hash = get_env_hash()

    with database.get_db_connection() as conn:
        row = conn.execute("SELECT value FROM settings WHERE key = 'env_hash'").fetchone()
        stored_hash = row['value'] if row else ""

        if current_hash != stored_hash:
            logging.info("SETTINGS: .env file change detected. Syncing to database...")
            load_dotenv(ENV_PATH, override=True)

            keys_to_sync = [
                "SERVER_TYPE", "EMBY_URL", "EMBY_USER", "EMBY_PASS",
                "AI_PROVIDER", "OLLAMA_URL", "OLLAMA_MODEL", "GEMINI_API_KEY",
                "VERBOSE_LOGGING"
            ]

            for k in keys_to_sync:
                val = os.environ.get(k, "")
                conn.execute(
                    "INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)",
                    (k, val)
                )

            conn.execute("INSERT OR REPLACE INTO settings (key, value) VALUES ('env_hash', ?)", (current_hash,))
            conn.commit()

def load_settings_from_db():
    """Hydrates runtime globals from the SQLite settings table."""
    import database

    global SERVER_TYPE, AI_PROVIDER, OLLAMA_URL, OLLAMA_MODEL, GEMINI_API_KEY, VERBOSE_LOGGING, STARRED_MODELS

    with database.get_db_connection() as conn:
        rows = conn.execute("SELECT key, value FROM settings").fetchall()
        settings = {row['key']: row['value'] for row in rows}

        SERVER_TYPE = settings.get("SERVER_TYPE", "emby").lower()
        core.EMBY_URL = settings.get("EMBY_URL", "").rstrip("/")
        core.EMBY_USER = settings.get("EMBY_USER")
        core.EMBY_PASS = settings.get("EMBY_PASS")

        AI_PROVIDER = settings.get("AI_PROVIDER", "gemini").lower()
        OLLAMA_URL = settings.get("OLLAMA_URL", "http://localhost:11434")
        OLLAMA_MODEL = settings.get("OLLAMA_MODEL", "qwen2.5:7b")
        GEMINI_API_KEY = settings.get("GEMINI_API_KEY")
        
        try:
            STARRED_MODELS = json.loads(settings.get("STARRED_MODELS", "[]"))
        except:
            STARRED_MODELS = []
            
        VERBOSE_LOGGING = str(settings.get("VERBOSE_LOGGING", "false")).lower() in ("true", "1", "t", "yes")

def load_and_authenticate() -> bool:
    """Master startup sequence: Hash check -> DB Sync -> Hydrate -> Authenticate."""
    global login_uid, token, HDR, is_configured, DEFAULT_USER_NAME, DEFAULT_UID, SERVER_ID, OLLAMA_TIMEOUT

    try:
        sync_env_to_db()
        load_settings_from_db()

        try:
            from app.logger import refresh_logger_level
            refresh_logger_level()
        except ImportError:
            pass

        if not all([core.EMBY_URL, core.EMBY_USER, core.EMBY_PASS]):
            raise ValueError("Incomplete server configuration.")

        login_uid, token = core.authenticate(core.EMBY_USER, core.EMBY_PASS, core.EMBY_URL, SERVER_TYPE)
        HDR = core.auth_headers(token, login_uid)

        system_info_resp = core.SESSION.get(f"{core.EMBY_URL}/System/Info", headers=HDR, timeout=5)
        system_info_resp.raise_for_status()
        SERVER_ID = system_info_resp.json().get("Id")

        DEFAULT_USER_NAME = core.EMBY_USER
        DEFAULT_UID = login_uid
        is_configured = True
        return True
    except Exception as e:
        is_configured = False
        logging.warning(f"Auth failed: {e}")
        return False