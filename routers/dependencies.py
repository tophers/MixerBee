"""
dependencies.py – APIRouter
"""

import logging
import time
from fastapi import HTTPException, status

import app_state
import app.client as client

_last_token_check = 0
TOKEN_TTL_SECONDS = 300

def get_current_auth_headers() -> dict:
    """
    FastAPI Dependency to ensure the app is configured and the auth token is valid.
    """
    global _last_token_check

    if not app_state.is_configured:
        logging.warning("Auth dependency called but app_state is not configured. Attempting to recover...")
        if not app_state.load_and_authenticate():
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Application is not configured. Please provide server details in settings."
            )

    now = time.time()
    if (now - _last_token_check) < TOKEN_TTL_SECONDS:
        return {
            "hdr": app_state.HDR,
            "token": app_state.token,
            "login_uid": app_state.login_uid
        }

    is_valid, status_code = client.test_connection(app_state.HDR)

    if is_valid:
        _last_token_check = now
        return {
            "hdr": app_state.HDR,
            "token": app_state.token,
            "login_uid": app_state.login_uid
        }

    if status_code in (401, 403):
        logging.warning("Auth token is expired or invalid. Attempting to re-authenticate...")
        if app_state.load_and_authenticate():
            _last_token_check = time.time()
            logging.info("Successfully re-authenticated and refreshed token.")
            return {
                "hdr": app_state.HDR,
                "token": app_state.token,
                "login_uid": app_state.login_uid
            }
        else:
            logging.error("Failed to re-authenticate after token expired.")
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Could not re-authenticate with the media server. Check your credentials."
            )

    logging.error(f"Media server connection test failed with status code: {status_code}")
    raise HTTPException(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        detail=f"Could not connect to the media server. Status: {status_code}"
    )