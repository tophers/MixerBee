"""
app/client.py - Handles configuration, session management, and authentication.
"""
import os
import sys
import json
import atexit
from pathlib import Path
from typing import Tuple, Dict, Optional

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from dotenv import load_dotenv

import app_state

IS_DOCKER = os.path.exists('/.dockerenv')
PROJECT_ROOT = Path(__file__).resolve().parent.parent

if IS_DOCKER:
    CONFIG_DIR = Path("/config")
else:
    CONFIG_DIR = PROJECT_ROOT / "config"

ENV_PATH = CONFIG_DIR / ".env"
CONFIG_DIR.mkdir(parents=True, exist_ok=True)

# --- Load Environment Early ---
load_dotenv(ENV_PATH)

# --- Global Config Variables ---
EMBY_URL = os.environ.get("EMBY_URL", "").rstrip("/")
EMBY_USER = os.environ.get("EMBY_USER")
EMBY_PASS = os.environ.get("EMBY_PASS")

# Static client identifiers.
CLIENT_NAME = "MixerBee"
CLIENT_VERSION = "1.0.0"
DEVICE_ID = "MixerBeePy"
DEVICE_NAME = "MixerBee"

# requests session with retries
SESSION = requests.Session()
_retry = Retry(total=3, backoff_factor=0.3, status_forcelist=(502, 503, 504))
_adapter = HTTPAdapter(max_retries=_retry)
SESSION.mount("http://", _adapter)
SESSION.mount("https://", _adapter)

# Ensure the session is closed when the application exits
atexit.register(SESSION.close)

# Authentication helpers
def authenticate(username: str, password: str, url: str, server_type: str) -> Tuple[str, str]:
    """
    Authenticates with Emby or Jellyfin and returns the User ID and Access Token.
    """
    auth_url = url.rstrip("/")
    if not auth_url:
        raise ValueError("Server URL is not configured.")

    endpoint = f"{auth_url}/Users/AuthenticateByName"
    payload = {"Username": username, "Pw": password}

    auth_str = f'MediaBrowser Client="{CLIENT_NAME}", Device="{DEVICE_NAME}", DeviceId="{DEVICE_ID}", Version="{CLIENT_VERSION}"'

    if server_type == 'jellyfin':
        headers = {"Authorization": auth_str}
    else: # emby
        headers = {"X-Emby-Authorization": auth_str}

    r = SESSION.post(endpoint, json=payload, headers=headers, timeout=10)

    r.raise_for_status()
    j = r.json()
    return j["User"]["Id"], j["AccessToken"]


def auth_headers(token: str, user_id: str) -> Dict[str, str]:
    """Constructs the standard authorization headers for API calls AFTER authentication."""
    auth_str = (
        f'MediaBrowser Client="{CLIENT_NAME}", Device="{DEVICE_NAME}", '
        f'DeviceId="{DEVICE_ID}", Version="{CLIENT_VERSION}", '
        f'UserId="{user_id}", Token="{token}"'
    )
    
    headers = {
        "X-Emby-Token": token,
        "X-MediaBrowser-Token": token,
        "X-Emby-User-Id": user_id,
    }

    if app_state.SERVER_TYPE == 'jellyfin':
        headers['Authorization'] = auth_str
    else: # emby
        headers['X-Emby-Authorization'] = auth_str

    return headers