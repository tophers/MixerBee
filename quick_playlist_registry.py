"""
quick_playlist_registry.py - Shared registry for Smart Build and Quick Playlist types.
Single source of truth for build functions, required options, and schedulability.
"""

from typing import Dict, Any, Callable, List, Optional
import app as core

QUICK_PLAYLIST_REGISTRY: Dict[str, Dict[str, Any]] = {
    "recently_added": {
        "type": "recently_added",
        "name": "Recently Added",
        "description": "The latest movies and episodes added to your library.",
        "icon": "zap",
        "func": core.create_recently_added_playlist,
        "required_options": ["count"],
        "default_options": {"count": 25},
        "schedulable": True,
        "category": "mixed"
    },
    "next_up": {
        "type": "next_up",
        "name": "Next Up",
        "description": "Next episodes from your in-progress shows.",
        "icon": "play",
        "func": core.create_continue_watching_playlist,
        "required_options": ["count"],
        "default_options": {"count": 15},
        "schedulable": True,
        "category": "tv"
    },
    "pilot_sampler": {
        "type": "pilot_sampler",
        "name": "Pilot Sampler",
        "description": "Random pilot episodes from unwatched shows.",
        "icon": "film",
        "func": core.create_pilot_sampler_playlist,
        "required_options": ["count"],
        "default_options": {"count": 10},
        "schedulable": True,
        "category": "tv"
    },
    "from_the_vault": {
        "type": "from_the_vault",
        "name": "From the Vault",
        "description": "Favorite movies you haven't watched in a while.",
        "icon": "archive",
        "func": core.create_forgotten_favorites_playlist,
        "required_options": ["count"],
        "default_options": {"count": 20},
        "schedulable": True,
        "category": "movies"
    },
    "genre_roulette": {
        "type": "genre_roulette",
        "name": "Movie Genre Roulette",
        "description": "A movie marathon from a random genre.",
        "icon": "shuffle",
        "func": core.create_movie_marathon_playlist,
        "required_options": ["genre", "count"],
        "default_options": {"count": 10},
        "schedulable": False,
        "category": "movies"
    },
    "top_community_unwatched": {
        "type": "top_community_unwatched",
        "name": "Top Community Picks",
        "description": "Highest community-rated movies you haven't seen.",
        "icon": "film",
        "func": core.create_top_community_unwatched_playlist,
        "required_options": ["count"],
        "default_options": {"count": 10},
        "schedulable": True,
        "category": "movies"
    },
    "top_critic_unwatched": {
        "type": "top_critic_unwatched",
        "name": "Top Critic Picks",
        "description": "Highest critic-rated movies you haven't seen.",
        "icon": "film",
        "func": core.create_top_critic_unwatched_playlist,
        "required_options": ["count"],
        "default_options": {"count": 10},
        "schedulable": True,
        "category": "movies"
    },
    "artist_spotlight": {
        "type": "artist_spotlight",
        "name": "Artist Spotlight",
        "description": "Top songs from a selected artist.",
        "icon": "music",
        "func": core.create_artist_spotlight_playlist,
        "required_options": ["artist_id", "count"],
        "default_options": {"count": 25},
        "schedulable": True,
        "category": "music"
    },
    "genre_sampler": {
        "type": "genre_sampler",
        "name": "Music Genre Sampler",
        "description": "Random songs from a selected music genre.",
        "icon": "music",
        "func": core.create_music_genre_playlist,
        "required_options": ["genre", "count"],
        "default_options": {"count": 25},
        "schedulable": True,
        "category": "music"
    },
    "album_roulette": {
        "type": "album_roulette",
        "name": "Album Roulette",
        "description": "All tracks from an album in sequence.",
        "icon": "disc",
        "func": core.create_album_playlist,
        "required_options": ["album_id"],
        "default_options": {},
        "schedulable": True,
        "category": "music"
    },
}

# Derived quick build map: {type: (func, required_options)}
QUICK_BUILD_MAP = {
    k: (v["func"], v["required_options"])
    for k, v in QUICK_PLAYLIST_REGISTRY.items()
}

# Derived schedulable map: {type: func}
QUICK_PLAYLIST_MAP = {
    k: v["func"]
    for k, v in QUICK_PLAYLIST_REGISTRY.items()
    if v["schedulable"]
}


def get_public_registry() -> List[Dict[str, Any]]:
    """Returns registry metadata for API and frontend presentation."""
    return [
        {
            "type": v["type"],
            "name": v["name"],
            "description": v["description"],
            "icon": v["icon"],
            "required_options": v["required_options"],
            "default_options": v["default_options"],
            "schedulable": v["schedulable"],
            "category": v["category"]
        }
        for v in QUICK_PLAYLIST_REGISTRY.values()
    ]
