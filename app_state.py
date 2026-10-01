"""
app_state.py – Manages global configuration
"""

import os
import hashlib
import json
import uuid
import threading
from dotenv import load_dotenv

import app as core
import app.client as client

from runtime_paths import CONFIG_DIR, ENV_PATH

CONFIG_DIR.mkdir(parents=True, exist_ok=True)

is_configured = False
DEFAULT_USER_NAME, DEFAULT_UID = None, None
GEMINI_API_KEY = None

AI_PROVIDER = "ollama"
OLLAMA_URL = "http://localhost:11434"
OLLAMA_MODEL = "qwen2.5:7b"
OLLAMA_TIMEOUT = 120
STARRED_MODELS = []
VERBOSE_LOGGING = False
_logging_settings_lock = threading.RLock()
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

# Defined after VERBOSE_LOGGING above: get_logger() reads it to set the initial level.
from app.logger import get_logger

logger = get_logger("MixerBee.State")

def load_logging_settings() -> bool:
    """Load installation logging independently of legacy media credentials."""
    import database
    from app.logger import refresh_logger_level
    from app.log_buffer import capture

    global VERBOSE_LOGGING
    with _logging_settings_lock:
        with database.get_db_connection() as conn:
            row = conn.execute("SELECT value FROM settings WHERE key='VERBOSE_LOGGING'").fetchone()
        VERBOSE_LOGGING = str(row['value'] if row else 'false').lower() in ('true', '1', 't', 'yes')
        refresh_logger_level()
        # Capture follows the saved preference exactly, so a restart with verbose on
        # starts collecting immediately and a restart with it off collects nothing.
        capture.attach_all()
        capture.set_enabled(VERBOSE_LOGGING)
        return VERBOSE_LOGGING


def set_verbose_logging(enabled: bool) -> bool:
    """Persist before applying, so a failed save leaves runtime logging unchanged."""
    import database
    from app.logger import refresh_logger_level
    from app.log_buffer import capture

    global VERBOSE_LOGGING
    with _logging_settings_lock:
        with database.get_db_connection() as conn:
            columns = {r['name'] for r in conn.execute('PRAGMA table_info(settings)')}
            if 'updated_at' in columns:
                conn.execute(
                    "INSERT OR REPLACE INTO settings (key,value,updated_at) VALUES ('VERBOSE_LOGGING',?,CURRENT_TIMESTAMP)",
                    ('true' if enabled else 'false',))
            else:
                conn.execute(
                    "INSERT OR REPLACE INTO settings (key,value) VALUES ('VERBOSE_LOGGING',?)",
                    ('true' if enabled else 'false',))
            conn.commit()
        VERBOSE_LOGGING = enabled
        refresh_logger_level()
        # Turning verbose off drops every retained record; turning it on starts a new
        # capture generation, which invalidates any cursor a browser still holds.
        capture.attach_all()
        capture.set_enabled(enabled)
        return VERBOSE_LOGGING


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
            logger.info("SETTINGS: .env file change detected. Syncing to database...")
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
        # Legacy settings facade for the current single-connection UI only.
        core.EMBY_URL = client.EMBY_URL = settings.get("EMBY_URL", "").rstrip("/")
        core.EMBY_USER = settings.get("EMBY_USER")
        core.EMBY_PASS = settings.get("EMBY_PASS")

        AI_PROVIDER = settings.get("AI_PROVIDER", "ollama").lower()
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
    global is_configured, DEFAULT_USER_NAME, DEFAULT_UID, SERVER_ID, OLLAMA_TIMEOUT

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

        from app.media_client import Connection, MediaClient
        from connections import save_authenticated_connection
        candidate = MediaClient(Connection(uuid.uuid4().hex, core.EMBY_URL, SERVER_TYPE, core.EMBY_USER, core.EMBY_PASS))
        try:
            auth = candidate.authenticate()
        finally:
            candidate.session.close()
        # Seed the provider selection only when .env actually named one *and* supplied
        # its credentials. The module defaults above are fallbacks, not consent: writing
        # them in would make every legacy import look like a deliberate AI setup.
        provider = (AI_PROVIDER or "").strip().lower()
        seeded_ai = {"GEMINI_API_KEY": GEMINI_API_KEY or "", "OLLAMA_URL": OLLAMA_URL or "",
                     "OLLAMA_MODEL": OLLAMA_MODEL or "", "OLLAMA_TIMEOUT": OLLAMA_TIMEOUT,
                     "AI_PROVIDER": ""}
        if (provider == "gemini" and (GEMINI_API_KEY or "").strip()) or \
           (provider == "ollama" and (OLLAMA_URL or "").strip() and (OLLAMA_MODEL or "").strip()):
            seeded_ai["AI_PROVIDER"] = provider
        media = save_authenticated_connection(
            core.EMBY_URL, SERVER_TYPE, core.EMBY_USER, core.EMBY_PASS, auth, seeded_ai)
        SERVER_ID = media.connection.server_id

        DEFAULT_USER_NAME = core.EMBY_USER
        DEFAULT_UID = media.user_id
        is_configured = True
        return True
    except Exception as e:
        is_configured = False
        logger.warning(f"Auth failed: {e}")
        return False
