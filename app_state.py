#!/usr/bin/env python3
"""
app_state.py – Manages global configuration and runtime state.
"""
import os
import logging
from pathlib import Path
from dotenv import load_dotenv

import app as core

# --- Global State Variables ---
login_uid, token, HDR, is_configured = None, None, {}, False
DEFAULT_USER_NAME, DEFAULT_UID = None, None
GEMINI_API_KEY = None
SERVER_TYPE = None

# --- Path Resolution ---
IS_DOCKER = os.path.exists('/.dockerenv')
HERE = Path(__file__).parent

if IS_DOCKER:
    CONFIG_DIR = Path("/config")
else:
    CONFIG_DIR = HERE / "config"

ENV_PATH = CONFIG_DIR / ".env"
CONFIG_DIR.mkdir(parents=True, exist_ok=True)


def load_and_authenticate():
    """Loads config from .env and authenticates, setting global state."""
    global login_uid, token, HDR, is_configured, DEFAULT_USER_NAME, DEFAULT_UID, GEMINI_API_KEY, SERVER_TYPE

    load_dotenv(ENV_PATH, override=True)

    # Reload from os.environ after load_dotenv
    SERVER_TYPE = os.environ.get("SERVER_TYPE", "emby").lower()
    core.EMBY_URL = os.environ.get("EMBY_URL", "").rstrip("/")
    core.EMBY_USER = os.environ.get("EMBY_USER")
    core.EMBY_PASS = os.environ.get("EMBY_PASS")
    GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

    try:
        if not all([core.EMBY_URL, core.EMBY_USER, core.EMBY_PASS]):
            raise ValueError("Missing required Emby/Jellyfin credentials in environment.")

        login_uid, token = core.authenticate(core.EMBY_USER, core.EMBY_PASS, core.EMBY_URL, SERVER_TYPE)
        HDR = core.auth_headers(token, login_uid)

        DEFAULT_USER_NAME = core.EMBY_USER
        DEFAULT_UID = login_uid

        is_configured = True
        logging.info(f"Successfully loaded configuration and authenticated with {SERVER_TYPE.capitalize()}.")

    except Exception as e:
        login_uid, token, HDR, is_configured = None, None, {}, False
        DEFAULT_USER_NAME, DEFAULT_UID = None, None
        SERVER_TYPE = None
        logging.warning(f"Initial configuration load failed: {e}")