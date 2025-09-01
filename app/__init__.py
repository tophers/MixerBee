"""
app/__init__.py - Public interface for the MixerBee core logic.
"""

from .client import (
    SESSION,
    EMBY_URL,
    EMBY_USER,
    EMBY_PASS,
    authenticate,
    auth_headers
)

from .users import (
    all_users,
    user_id_by_name
)

from .tv import (
    get_all_series,
    search_series,
    get_specific_episode,
    get_first_unwatched_episode,
    get_random_unwatched_episode,
    parse_show, # For legacy CLI
    series_id,  # For legacy CLI
    episodes,   # For legacy CLI
    interleave  # For legacy CLI
)

from .movies import (
    get_movie_libraries,
    get_movie_genres,
    find_movies
)

from .people import (
    get_people
)

from .studios import (
    get_studios
)

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

from .items import (
    get_playlists,
    delete_playlist,
    create_playlist,
    remove_item_from_playlist,
    get_collections,
    delete_collection,
    create_movie_collection,
    delete_item_by_id,
    get_item_children,
    get_manageable_items,
    create_recently_added_playlist,
    create_pilot_sampler_playlist,
    create_continue_watching_playlist,
    create_forgotten_favorites_playlist,
    create_movie_marathon_playlist,
    create_artist_spotlight_playlist,
    create_album_playlist,
    create_music_genre_playlist
)

from .builder import (
    create_mixed_playlist,
    add_items_to_playlist,
    generate_items_from_blocks,
    format_items_for_preview
)
