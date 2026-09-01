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
import app.client as client

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
EXTERNAL_API_KEY = None
WEBHOOK_DEBOUNCE_SECONDS = 30

# Gatekeeping: ACCESS_KEY guards the entire API/UI (auto-generated on first run, DB-only,
# never round-tripped through .env). WEBHOOK_SECRET is a separate, opt-in secret checked
# on /api/webhook only, since Emby/Jellyfin notification plugins can't send custom headers
# and instead get it via a URL query param.
ACCESS_KEY = None
WEBHOOK_SECRET = None

CACHE_REFRESH_MINUTES = 15
SERVER_TYPE = "emby"
SERVER_ID = None

ENRICHMENT_BACKUP = {}

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
                "AI_PROVIDER", "OLLAMA_URL", "OLLAMA_MODEL", "OLLAMA_TIMEOUT", "GEMINI_API_KEY",
                "VERBOSE_LOGGING", "EXTERNAL_API_KEY"
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

    global SERVER_TYPE, AI_PROVIDER, OLLAMA_URL, OLLAMA_MODEL, OLLAMA_TIMEOUT, GEMINI_API_KEY, VERBOSE_LOGGING, STARRED_MODELS, EXTERNAL_API_KEY, ACCESS_KEY, WEBHOOK_SECRET, WEBHOOK_DEBOUNCE_SECONDS

    with database.get_db_connection() as conn:
        rows = conn.execute("SELECT key, value FROM settings").fetchall()
        settings = {row['key']: row['value'] for row in rows}

        SERVER_TYPE = settings.get("SERVER_TYPE", "emby").lower()
        # Every app/*.py domain module (items, movies, tv, music, ...) builds its Emby
        # request URLs from app.client.EMBY_URL directly, not from this core.EMBY_URL copy
        # (app/__init__.py's `from .client import EMBY_URL` binds a value, not a live
        # reference, so the two diverge the moment either is reassigned). core.EMBY_URL
        # alone only feeds core.authenticate()'s explicit argument below, so keep
        # client.EMBY_URL in sync too or a mid-process re-sync (e.g. after a manual .env
        # edit, without the full restart a Settings-UI save triggers) leaves every actual
        # API call pointed at a stale host.
        core.EMBY_URL = client.EMBY_URL = settings.get("EMBY_URL", "").rstrip("/")
        core.EMBY_USER = settings.get("EMBY_USER")
        core.EMBY_PASS = settings.get("EMBY_PASS")

        AI_PROVIDER = settings.get("AI_PROVIDER", "gemini").lower()
        OLLAMA_URL = settings.get("OLLAMA_URL", "http://localhost:11434")
        OLLAMA_MODEL = settings.get("OLLAMA_MODEL", "qwen2.5:7b")
        GEMINI_API_KEY = settings.get("GEMINI_API_KEY")

        try:
            OLLAMA_TIMEOUT = int(settings.get("OLLAMA_TIMEOUT") or 120)
        except (TypeError, ValueError):
            OLLAMA_TIMEOUT = 120
        
        try:
            STARRED_MODELS = json.loads(settings.get("STARRED_MODELS", "[]"))
        except:
            STARRED_MODELS = []
            
        VERBOSE_LOGGING = str(settings.get("VERBOSE_LOGGING", "false")).lower() in ("true", "1", "t", "yes")
        
        EXTERNAL_API_KEY = settings.get("EXTERNAL_API_KEY")

        # ACCESS_KEY/WEBHOOK_SECRET/WEBHOOK_DEBOUNCE_SECONDS are DB-only (never written to
        # .env, never in keys_to_sync above) so a later .env edit can never wipe them out via
        # sync_env_to_db, which would otherwise write "" for any key .env doesn't mention.
        # ACCESS_KEY/WEBHOOK_SECRET are also opt-in and unset by default: MixerBee stays open
        # on the LAN, same as before this existed, until the admin deliberately sets one from
        # Settings (the UI nags but never forces this).
        ACCESS_KEY = settings.get("MIXERBEE_ACCESS_KEY") or None
        WEBHOOK_SECRET = settings.get("MIXERBEE_WEBHOOK_SECRET") or None

        try:
            WEBHOOK_DEBOUNCE_SECONDS = max(1, int(settings.get("WEBHOOK_DEBOUNCE_SECONDS") or 30))
        except (TypeError, ValueError):
            WEBHOOK_DEBOUNCE_SECONDS = 30

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
