"""
app/client.py - Handles configuration, session management, and authentication
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
from app.logger import get_logger

logger = get_logger("MixerBee.Client")

IS_DOCKER = os.path.exists('/.dockerenv')
PROJECT_ROOT = Path(__file__).resolve().parent.parent

if IS_DOCKER:
    CONFIG_DIR = Path("/config")
else:
    CONFIG_DIR = PROJECT_ROOT / "config"

ENV_PATH = CONFIG_DIR / ".env"
CONFIG_DIR.mkdir(parents=True, exist_ok=True)

load_dotenv(ENV_PATH)

EMBY_URL = os.environ.get("EMBY_URL", "").rstrip("/")
EMBY_USER = os.environ.get("EMBY_USER")
EMBY_PASS = os.environ.get("EMBY_PASS")

CLIENT_NAME = "MixerBee"
CLIENT_VERSION = "2026.04.7"
DEVICE_ID = "MixerBeePy"
DEVICE_NAME = "MixerBee"

SESSION = requests.Session()
_retry = Retry(total=3, backoff_factor=0.3, status_forcelist=(502, 503, 504))
_adapter = HTTPAdapter(max_retries=_retry)
SESSION.mount("http://", _adapter)
SESSION.mount("https://", _adapter)

atexit.register(SESSION.close)

def test_connection(hdr: Dict[str, str]) -> Tuple[bool, int]:
    """
    Makes a lightweight, authenticated call to the server to check if the token is valid.
    Returns (isValid: bool, statusCode: int).
    """
    if not EMBY_URL:
        logger.warning("Connection test failed: Server URL is not configured.")
        return False, 0
    try:
        logger.info(f"Testing server connection: {EMBY_URL}/System/Info")
        r = SESSION.get(f"{EMBY_URL}/System/Info", headers=hdr, timeout=5)
        is_valid = r.status_code == 200
        if is_valid:
            logger.info("Connection test successful.")
        else:
            logger.warning(f"Connection test returned unexpected status: {r.status_code}")
        return is_valid, r.status_code
    except requests.RequestException as e:
        logger.error(f"Connection test failed with exception: {e}")
        return False, 500 


def authenticate(username: str, password: str, url: str, server_type: str) -> Tuple[str, str]:
    """
    Authenticates with Emby or Jellyfin and returns the User ID and Access Token.
    """
    auth_url = url.rstrip("/")
    if not auth_url:
        raise ValueError("Server URL is not configured.")

    logger.info(f"Authenticating user '{username}' with {server_type} server at {auth_url}...")
    endpoint = f"{auth_url}/Users/AuthenticateByName"
    payload = {"Username": username, "Pw": password}

    auth_str = f'MediaBrowser Client="{CLIENT_NAME}", Device="{DEVICE_NAME}", DeviceId="{DEVICE_ID}", Version="{CLIENT_VERSION}"'

    if server_type == 'jellyfin':
        headers = {"Authorization": auth_str}
    else:
        headers = {"X-Emby-Authorization": auth_str}

    r = SESSION.post(endpoint, json=payload, headers=headers, timeout=10)

    try:
        r.raise_for_status()
        j = r.json()
        logger.info("Authentication successful. Token acquired.")
        return j["User"]["Id"], j["AccessToken"]
    except requests.RequestException as e:
        logger.error(f"Authentication failed: {e}")
        raise


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

    import app_state
    if app_state.SERVER_TYPE == 'jellyfin':
        headers['Authorization'] = auth_str
    else:
        headers['X-Emby-Authorization'] = auth_str

    return headers
