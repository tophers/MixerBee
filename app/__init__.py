"""
app/__init__.py - Public interface for the MixerBee core logic.

This file imports key functions from the submodules to make them
easily accessible from a single namespace. For example, other parts of the
application can do `import app as core` and then call `core.find_movies()`.
"""

# From client.py - Session and authentication
from .client import (
    SESSION,
    EMBY_URL,
    EMBY_USER,
    EMBY_PASS,
    authenticate,
    auth_headers
)

# From users.py
from .users import (
    all_users,
    user_id_by_name
)

# From tv.py
from .tv import (
    search_series,
    get_specific_episode,
    get_first_unwatched_episode,
    get_random_unwatched_episode,
    parse_show, # For legacy CLI
    series_id,  # For legacy CLI
    episodes,   # For legacy CLI
    interleave  # For legacy CLI
)

# From movies.py
from .movies import (
    get_movie_libraries,
    get_movie_genres,
    find_movies
)

# From music.py
from .music import (
    get_music_genres,
    get_music_artists,
    get_random_artist,
    get_random_album,
    get_albums_by_artist,
    get_songs_by_album,
    get_songs_by_artist,
    find_songs
)

# From items.py
from .items import (
    get_playlists,
    delete_playlist,
    create_playlist,
    get_collections,
    delete_collection,
    create_movie_collection,
    delete_item_by_id,
    get_item_children,
    get_manageable_items,
    create_pilot_sampler_playlist,
    create_continue_watching_playlist,
    create_forgotten_favorites_playlist,
    create_movie_marathon_playlist,
    create_artist_spotlight_playlist,
    create_album_playlist,
    create_music_genre_playlist
)

# From builder.py
from .builder import create_mixed_playlist
