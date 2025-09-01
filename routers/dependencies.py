"""
dependencies.py – APIRouter
"""

import logging
from fastapi import HTTPException, status

import app_state
import app.client as client

_is_token_known_good = False

def get_current_auth_headers() -> dict:
    """
    FastAPI Dependency to ensure the app is configured and the auth token is valid.
    This function will be called before any endpoint that includes it.
    """
    global _is_token_known_good

    if not app_state.is_configured:
        logging.warning("Auth dependency called but app_state is not configured. Attempting to load...")
        app_state.load_and_authenticate()

    if not app_state.is_configured:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Application is not configured. Please provide server details in settings."
        )

    if _is_token_known_good:
        return {
            "hdr": app_state.HDR,
            "token": app_state.token,
            "login_uid": app_state.login_uid
        }

    is_valid, status_code = client.test_connection(app_state.HDR)

    if is_valid:
        logging.info("Existing auth token is valid.")
        _is_token_known_good = True
        return {
            "hdr": app_state.HDR,
            "token": app_state.token,
            "login_uid": app_state.login_uid
        }
    
    if status_code == 401:
        logging.warning("Auth token is expired or invalid. Attempting to re-authenticate...")
        try:
            app_state.load_and_authenticate()
            _is_token_known_good = True 
            logging.info("Successfully re-authenticated and refreshed token.")
            return {
                "hdr": app_state.HDR,
                "token": app_state.token,
                "login_uid": app_state.login_uid
            }
        except Exception as e:
            logging.error(f"Failed to re-authenticate after token expired: {e}", exc_info=True)
            _is_token_known_good = False
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Could not re-authenticate with the media server. The server may be offline or credentials have changed."
            )
    
    logging.error(f"Media server connection test failed with status code: {status_code}")
    _is_token_known_good = False
    raise HTTPException(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        detail=f"Could not connect to the media server. Status: {status_code}"
    )