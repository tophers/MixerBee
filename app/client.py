"""
app/client.py - Handles configuration, session management, and authentication.
"""
import os
import sys
import atexit
from pathlib import Path
from typing import Tuple, Dict

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from dotenv import load_dotenv

# ---------------------------------------------------------------------------
# config / .env handling
# ---------------------------------------------------------------------------

# This logic is designed to find the .env file relative to the project root,
# not the app/ directory itself.
project_root = Path(__file__).resolve().parent.parent

ENV_PATH = project_root / ".mixerbee.env"
if not ENV_PATH.exists():
    xdg = Path(os.getenv("XDG_CONFIG_HOME", "~/.config")).expanduser()
    ENV_PATH = xdg / "mixerbee" / ".env"

if not load_dotenv(ENV_PATH):
    sys.stderr.write(f"[mixerbee] warning: no .env file found at {ENV_PATH}\n")

try:
    EMBY_URL = os.environ["EMBY_URL"].rstrip("/")
    EMBY_USER = os.environ["EMBY_USER"]
    EMBY_PASS = os.environ["EMBY_PASS"]
except KeyError as m:
    raise RuntimeError(f"Missing {m} in environment settings") from None

CLIENT_NAME = os.getenv("CLIENT_NAME", "MixerBee")
DEVICE_ID = os.getenv("DEVICE_ID", "MixerBee_CLI")


# ---------------------------------------------------------------------------
# requests session with retries
# ---------------------------------------------------------------------------

SESSION = requests.Session()
_retry = Retry(total=3, backoff_factor=0.3, status_forcelist=(502, 503, 504))
_adapter = HTTPAdapter(max_retries=_retry)
SESSION.mount("http://", _adapter)
SESSION.mount("https://", _adapter)

# Ensure the session is closed when the application exits
atexit.register(SESSION.close)


# ---------------------------------------------------------------------------
# authentication helpers
# ---------------------------------------------------------------------------

def authenticate(username: str, password: str) -> Tuple[str, str]:
    """Authenticates with Emby and returns the User ID and Access Token."""
    hdr = {"X-Emby-Authorization":
           f'MediaBrowser Client="{CLIENT_NAME}",Device="script",'
           f'DeviceId="{DEVICE_ID}",Version="1.0"'}
    r = SESSION.post(f"{EMBY_URL}/Users/AuthenticateByName",
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