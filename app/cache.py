"""
app/cache.py - Manages a persistent, background-refreshed cache for library data
"""

import threading
from typing import Dict, Any, List
from app.logger import get_logger

from . import tv, movies, studios, client,  music, users

logger = get_logger("MixerBee.Cache")

_cache_key = ["data"]
CACHE: Dict[str, Any] = {_cache_key[0]: {}}

_refresh_lock = threading.Lock()

def get_library_data() -> Dict[str, Any]:
    """Safely retrieves the current data from the cache."""
    return CACHE.get(_cache_key[0], {})

def _fetch_all_data(auth_details: Dict[str, str]) -> Dict[str, Any]:
    """
    The core data fetching logic. This function contacts the media server
    to get all the necessary data for the application's UI.
    """
    try:
        token = auth_details.get("token")
        login_uid = auth_details.get("login_uid")

        if not all([token, login_uid]):
            logger.warning("Cannot refresh cache, missing auth details.")
            return {}

        hdr = client.auth_headers(token, login_uid)

        logger.info("Starting background refresh of all library data...")
        
        data = {
            "seriesData": tv.get_all_series(login_uid, hdr),
            "movieGenreData": movies.get_movie_genres(login_uid, hdr),
            "libraryData": movies.get_movie_libraries(login_uid, hdr),
            "artistData": music.get_music_artists(hdr),
            "musicGenreData": music.get_music_genres(login_uid, hdr),
            "studioData": studios.aggregate_all_studios(login_uid, hdr),
        }
        logger.info("Background refresh completed successfully.")
        return data

    except Exception as e:
        logger.error(f"An error occurred during background refresh: {e}", exc_info=True)
        return {}

def refresh_cache(auth_details: Dict[str, str] = None):
    """
    Public function to trigger a cache refresh. It's thread-safe.
    """
    if not auth_details:
        from app_state import token, login_uid
        auth_details = {"token": token, "login_uid": login_uid}

    if _refresh_lock.acquire(blocking=False):
        try:
            new_data = _fetch_all_data(auth_details)
            if new_data:
                CACHE[_cache_key[0]] = new_data
        finally:
            _refresh_lock.release()
    else:
        logger.info("Refresh is already in progress. Skipping.")