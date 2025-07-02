"""
app/music.py - All music-related logic.
"""
import random
import logging
from typing import Dict, List, Optional

import requests

from .client import SESSION, EMBY_URL

# ---------------------------------------------------------------------------
# Music helpers
# ---------------------------------------------------------------------------

def get_music_library_id(hdr: Dict[str, str]) -> Optional[str]:
    """Finds the ID of the first library with the collection type 'music'."""
    try:
        r = SESSION.get(f"{EMBY_URL}/Library/MediaFolders", headers=hdr, timeout=10)
        r.raise_for_status()
        folders = r.json().get("Items", [])
        for folder in folders:
            if folder.get("CollectionType") == "music":
                return folder.get("Id")
    except requests.RequestException as e:
        logging.error(f"Could not fetch music library ID: {e}")
    return None

def get_music_genres(hdr: Dict[str, str]) -> List[Dict[str, str]]:
    """Fetches all music genres using the ParentId of the main music library."""
    music_library_id = get_music_library_id(hdr)
    if not music_library_id:
        logging.warning("No music library found. Cannot fetch music genres.")
        return []

    params = {
        "IncludeItemTypes": "Audio",
        "ParentId": music_library_id
    }
    r = SESSION.get(f"{EMBY_URL}/Genres",
                    params=params, headers=hdr, timeout=10)
    r.raise_for_status()
    return r.json().get("Items", [])

def get_music_artists(hdr: Dict[str, str]) -> List[Dict[str, str]]:
    """Fetches all music artists from Emby."""
    params = {
        "IncludeItemTypes": "MusicArtist",
        "Recursive": "true",
        "Fields": "Id,Name",
        "SortBy": "SortName",
    }
    r = SESSION.get(f"{EMBY_URL}/Items", params=params, headers=hdr, timeout=20)
    r.raise_for_status()
    return r.json().get("Items", [])

def get_random_artist(hdr: Dict[str, str]) -> Optional[Dict[str, str]]:
    """Fetches all music artists and returns one at random."""
    all_artists = get_music_artists(hdr)
    if not all_artists:
        return None
    return random.choice(all_artists)

def get_random_album(hdr: Dict[str, str]) -> Optional[Dict[str, str]]:
    """Fetches all music albums and returns one at random."""
    params = {
        "IncludeItemTypes": "MusicAlbum",
        "Recursive": "true",
        "Fields": "Id,Name,ArtistItems",
    }
    r = SESSION.get(f"{EMBY_URL}/Items", params=params, headers=hdr, timeout=20)
    r.raise_for_status()
    all_albums = r.json().get("Items", [])
    if not all_albums:
        return None
    return random.choice(all_albums)

def get_albums_by_artist(artist_id: str, hdr: Dict[str, str]) -> List[Dict[str, str]]:
    """Fetches all albums for a given artist."""
    params = {
        "IncludeItemTypes": "MusicAlbum",
        "Recursive": "true",
        "ArtistIds": artist_id,
        "Fields": "Id,Name",
        "SortBy": "ProductionYear,SortName",
        "SortOrder": "Descending",
    }
    r = SESSION.get(f"{EMBY_URL}/Items", params=params, headers=hdr, timeout=15)
    r.raise_for_status()
    return r.json().get("Items", [])


def get_songs_by_album(album_id: str, hdr: Dict[str, str]) -> List[Dict[str, str]]:
    """Fetches all songs for a given album, sorted by track number."""
    params = {
        "IncludeItemTypes": "Audio",
        "Recursive": "true",
        "ParentId": album_id,
        "Fields": "Id,Name,IndexNumber,ParentIndexNumber",
        "SortBy": "ParentIndexNumber,IndexNumber",
    }
    r = SESSION.get(f"{EMBY_URL}/Items", params=params, headers=hdr, timeout=15)
    r.raise_for_status()
    return r.json().get("Items", [])

def get_songs_by_artist(artist_id: str, hdr: Dict[str, str], sort: str = "PlayCount", limit: Optional[int] = None) -> List[Dict[str, str]]:
    """Fetches songs for an artist, with optional sorting and limiting."""
    params = {
        "IncludeItemTypes": "Audio",
        "Recursive": "true",
        "ArtistIds": artist_id,
        "Fields": "Id,Name,PlayCount",
        # Sorting by PlayCount directly in the API call can be unreliable.
        # We will fetch all and sort manually if needed.
        "SortBy": "Random" if sort == "Random" else "SortName",
    }

    r = SESSION.get(f"{EMBY_URL}/Items", params=params, headers=hdr, timeout=20)
    r.raise_for_status()
    songs = r.json().get("Items", [])

    if sort == "Top":
        # Sort by PlayCount manually after fetching the songs.
        songs.sort(key=lambda x: x.get("UserData", {}).get("PlayCount", 0), reverse=True)

    if limit:
        return songs[:limit]

    return songs

def find_songs(user_id: str, filters: Dict, hdr: Dict[str, str]) -> List[Dict[str, str]]:
    """Finds songs based on a set of filters, similar to find_movies."""
    base_params = {
        "IncludeItemTypes": "Audio",
        "Recursive": "true",
        "UserId": user_id,
        "Fields": "Genres,UserData,PlayCount"
    }

    r = SESSION.get(f"{EMBY_URL}/Users/{user_id}/Items", params=base_params, headers=hdr, timeout=30)
    r.raise_for_status()
    all_songs = r.json().get("Items", [])

    # Genre filtering
    genres_to_search = filters.get("genres")
    if genres_to_search:
        genre_match_type = filters.get("genre_match", "any")
        required_genres = set(g.lower() for g in genres_to_search)

        if genre_match_type == "any":
            all_songs = [
                s for s in all_songs
                if required_genres.intersection(set(g.lower() for g in s.get("Genres", [])))
            ]
        else:  # 'all'
            all_songs = [
                s for s in all_songs
                if required_genres.issubset(set(g.lower() for g in s.get("Genres", [])))
            ]

    final_list = all_songs

    # Sorting
    sort_by = filters.get("sort_by", "Random")
    if sort_by == "Random":
        random.shuffle(final_list)
    else:
        # Example sort keys: PlayCount, DateCreated, Name
        reverse = sort_by in ("PlayCount", "DateCreated")
        # Use a default value of 0 or "" for sorting to avoid errors on missing keys
        final_list.sort(key=lambda s: s.get(sort_by, 0 if sort_by == "PlayCount" else ""), reverse=reverse)

    # Limiting
    limit = filters.get("limit")
    if limit is not None:
        return final_list[:int(limit)]

    return final_list