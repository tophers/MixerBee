"""
app_state.py – Manages global configuration and runtime state.
"""
import os
import logging
from pathlib import Path
from dotenv import load_dotenv

import app as core

# --- Path Resolution ---
IS_DOCKER = os.path.exists('/.dockerenv')
if IS_DOCKER:
    CONFIG_DIR = Path("/config")
else:
    CONFIG_DIR = Path(__file__).parent / "config"

ENV_PATH = CONFIG_DIR / ".env"
CONFIG_DIR.mkdir(parents=True, exist_ok=True)

# --- Global State Variables ---
login_uid, token, HDR, is_configured = None, None, {}, False
DEFAULT_USER_NAME, DEFAULT_UID = None, None
GEMINI_API_KEY = None
SERVER_TYPE = None
SERVER_ID = None
CACHE_REFRESH_MINUTES = 15

def load_and_authenticate():
    """Loads config from .env and authenticates, setting global state."""
    global login_uid, token, HDR, is_configured, DEFAULT_USER_NAME, DEFAULT_UID, GEMINI_API_KEY, SERVER_TYPE, SERVER_ID, CACHE_REFRESH_MINUTES

    load_dotenv(ENV_PATH, override=True)

    SERVER_TYPE = os.environ.get("SERVER_TYPE", "emby").lower()
    core.EMBY_URL = os.environ.get("EMBY_URL", "").rstrip("/")
    core.EMBY_USER = os.environ.get("EMBY_USER")
    core.EMBY_PASS = os.environ.get("EMBY_PASS")
    GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

    try:
        CACHE_REFRESH_MINUTES = int(os.environ.get("CACHE_REFRESH_MINUTES", 15))
        if CACHE_REFRESH_MINUTES <= 0:
            logging.warning("CACHE_REFRESH_MINUTES must be a positive integer. Falling back to default of 15 minutes.")
            CACHE_REFRESH_MINUTES = 15
    except (ValueError, TypeError):
        logging.warning("Invalid CACHE_REFRESH_MINUTES value. Falling back to default of 15 minutes.")
        CACHE_REFRESH_MINUTES = 15


    try:
        if not all([core.EMBY_URL, core.EMBY_USER, core.EMBY_PASS]):
            raise ValueError("Missing required Emby/Jellyfin credentials in environment.")

        login_uid, token = core.authenticate(core.EMBY_USER, core.EMBY_PASS, core.EMBY_URL, SERVER_TYPE)
        HDR = core.auth_headers(token, login_uid)

        system_info_resp = core.SESSION.get(f"{core.EMBY_URL}/System/Info", headers=HDR, timeout=5)
        system_info_resp.raise_for_status()
        SERVER_ID = system_info_resp.json().get("Id")

        DEFAULT_USER_NAME = core.EMBY_USER
        DEFAULT_UID = login_uid

        is_configured = True
        logging.info(f"Successfully loaded configuration and authenticated with {SERVER_TYPE.capitalize()}. Server ID: {SERVER_ID}")
        logging.info(f"Library data cache refresh interval set to {CACHE_REFRESH_MINUTES} minutes.") 

    except Exception as e:
        login_uid, token, HDR, is_configured = None, None, {}, False
        DEFAULT_USER_NAME, DEFAULT_UID = None, None
        SERVER_TYPE = None
        SERVER_ID = None
        logging.warning(f"Initial configuration load failed: {e}")