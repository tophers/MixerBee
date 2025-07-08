"""
app/client.py - Handles configuration, session management, and authentication.
"""
import os
import sys
import atexit
from pathlib import Path
from typing import Tuple, Dict, Optional

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from dotenv import load_dotenv

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

# Static client identifiers. These are no longer needed in the .env file.
CLIENT_NAME = "MixerBee"
DEVICE_ID = "MixerBeePy"

# requests session with retries
SESSION = requests.Session()
_retry = Retry(total=3, backoff_factor=0.3, status_forcelist=(502, 503, 504))
_adapter = HTTPAdapter(max_retries=_retry)
SESSION.mount("http://", _adapter)
SESSION.mount("https://", _adapter)

# Ensure the session is closed when the application exits
atexit.register(SESSION.close)

# authentication helpers
def authenticate(username: str, password: str, url: Optional[str] = None) -> Tuple[str, str]:
    """Authenticates with Emby and returns the User ID and Access Token."""
    auth_url = (url or EMBY_URL).rstrip("/")
    if not auth_url:
        raise ValueError("Emby URL is not configured.")

    hdr = {"X-Emby-Authorization":
           f'MediaBrowser Client="{CLIENT_NAME}",Device="script",'
           f'DeviceId="{DEVICE_ID}",Version="1.0"'}

    r = SESSION.post(f"{auth_url}/Users/AuthenticateByName",
                     data={"Username": username, "Pw": password},
                     headers=hdr, timeout=10)
    r.raise_for_status()
    j = r.json()
    return j["User"]["Id"], j["AccessToken"]


def auth_headers(token: str, user_id: str) -> Dict[str, str]:
    """Constructs the standard authorization headers for Emby API calls."""
    return {
        "X-Emby-Token": token,
        "X-Emby-User-Id": user_id,
        "X-Emby-Authorization":
            f'MediaBrowser Client="{CLIENT_NAME}",Device="script",'
            f'DeviceId="{DEVICE_ID}",Version="1.0",UserId="{user_id}",'
            f'Token="{token}"'
    }