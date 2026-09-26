"""Legacy single-connection setup facade.

Domain operations receive MediaClient explicitly. These configuration values are
used only by the existing Settings/bootstrap flow until account setup replaces it.
"""
import os
import uuid
from dotenv import load_dotenv
from runtime_paths import CONFIG_DIR, ENV_PATH
from .media_client import Connection, MediaClient, CLIENT_VERSION

CONFIG_DIR.mkdir(parents=True, exist_ok=True)
load_dotenv(ENV_PATH)

EMBY_URL = os.environ.get('EMBY_URL', '').rstrip('/')
EMBY_USER = os.environ.get('EMBY_USER')
EMBY_PASS = os.environ.get('EMBY_PASS')


def authenticate(username: str, password: str, url: str, server_type: str):
    """Validate candidate settings without changing any saved client's identity."""
    candidate = MediaClient(Connection(uuid.uuid4().hex, url.rstrip('/'), server_type, username, password))
    try:
        result = candidate.authenticate()
        return result['User']['Id'], result['AccessToken']
    finally:
        candidate.session.close()
