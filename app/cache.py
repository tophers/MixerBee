"""Library metadata cached independently for each authenticated connection."""
import threading

from . import tv, movies, studios, music
from .media_client import ConnectionUnavailable, current_media
from app.logger import get_logger

logger = get_logger('MixerBee.Cache')
CACHE = {}
_locks = {}
_guard = threading.Lock()


def _is_authorization_failure(exc):
    """True only for failures that mean this connection may no longer see the library.

    Transient trouble (timeouts, refused connections, 5xx) must not be mistaken for
    revoked access: dropping the snapshot for those blanks the library UI for every
    reader until the next refresh.
    """
    if isinstance(exc, (ConnectionUnavailable, PermissionError)):
        return True
    response = getattr(exc, 'response', None)
    return getattr(response, 'status_code', None) in (401, 403)


def get_library_data(media=None):
    media = media or current_media()
    return CACHE.get(media.connection.id, {})


def refresh_cache(media):
    key = media.connection.id
    with _guard:
        lock = _locks.setdefault(key, threading.Lock())
    if not lock.acquire(blocking=False):
        return
    try:
        uid = media.user_id
        data = {
            'seriesData': tv.get_all_series(uid, media),
            'movieGenreData': movies.get_movie_genres(uid, media),
            'libraryData': movies.get_movie_libraries(uid, media),
            'artistData': music.get_music_artists(media),
            'musicGenreData': music.get_music_genres(uid, media),
            'studioData': studios.aggregate_all_studios(uid, media),
        }
        with _guard:
            # Removal retires the lock as well as the snapshot. A refresh already
            # in flight must not restore that deleted connection's data.
            if _locks.get(key) is lock:
                CACHE[key] = data
    except Exception as exc:
        if _is_authorization_failure(exc):
            # Do not serve an older visibility snapshot after an authorization failure.
            CACHE.pop(key, None)
            logger.exception('Library cache refresh failed for connection %s; dropped snapshot', key)
        else:
            # Keep the last good snapshot: this is transient, not a visibility change.
            logger.warning(
                'Library cache refresh failed for connection %s (%s: %s); keeping previous snapshot',
                key, type(exc).__name__, exc
            )
    finally:
        lock.release()


def refresh_all_caches():
    from connections import all_media_clients
    for media in all_media_clients():
        refresh_cache(media)


def forget_connection(connection_id):
    """Drop all process-local cache state for a removed connection."""
    with _guard:
        CACHE.pop(connection_id, None)
        _locks.pop(connection_id, None)
