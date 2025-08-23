"""
app/music.py - All music-related logic.
"""
import random
import logging
from typing import Dict, List, Optional

import requests

from . import client

# Music helpers
def get_music_genres(user_id: str, hdr: Dict[str, str]) -> List[Dict[str, str]]:
    """
    Fetches all music genres for a user by aggregating them from all audio items.
    This is more reliable than the /Genres endpoint for some user/permission configurations.
    """
    logging.info(f"Aggregating music genres for user {user_id}. This may take a moment for large libraries...")
    
    params = {
        "IncludeItemTypes": "Audio",
        "Recursive": "true",
        "Fields": "Genres",
        "UserId": user_id
    }
    
    try:
        r = client.SESSION.get(f"{client.EMBY_URL}/Users/{user_id}/Items", params=params, headers=hdr, timeout=60)
        r.raise_for_status()
        
        all_songs = r.json().get("Items", [])
        
        if not all_songs:
            logging.info(f"No audio items found for user {user_id}. Returning empty genre list.")
            return []

        unique_genres = set()
        for song in all_songs:
            for genre_name in song.get("Genres", []):
                unique_genres.add(genre_name)

        logging.info(f"Found {len(unique_genres)} unique music genres for user {user_id}.")

        # Convert the set of strings to the list of dicts the frontend expects
        genre_list = [{"Name": name, "Id": name} for name in sorted(list(unique_genres))]
        return genre_list

    except Exception as e:
        logging.error(f"Failed to aggregate music genres for user {user_id}: {e}", exc_info=True)
        return []

def get_music_artists(hdr: Dict[str, str]) -> List[Dict[str, str]]:
    """Fetches all music artists from Emby for the user specified in the header."""
    user_id = hdr.get("X-Emby-User-Id")
    params = {
        "IncludeItemTypes": "MusicArtist",
        "Recursive": "true",
        "Fields": "Id,Name",
        "SortBy": "SortName",
        "UserId": user_id
    }
    r = client.SESSION.get(f"{client.EMBY_URL}/Items", params=params, headers=hdr, timeout=20)
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
    user_id = hdr.get("X-Emby-User-Id")
    params = {
        "IncludeItemTypes": "MusicAlbum",
        "Recursive": "true",
        "Fields": "Id,Name,ArtistItems",
        "UserId": user_id
    }
    r = client.SESSION.get(f"{client.EMBY_URL}/Items", params=params, headers=hdr, timeout=20)
    r.raise_for_status()
    all_albums = r.json().get("Items", [])
    if not all_albums:
        return None
    return random.choice(all_albums)

def get_albums_by_artist(artist_id: str, hdr: Dict[str, str]) -> List[Dict[str, str]]:
    """Fetches all albums for a given artist."""
    user_id = hdr.get("X-Emby-User-Id")
    params = {
        "IncludeItemTypes": "MusicAlbum",
        "Recursive": "true",
        "ArtistIds": artist_id,
        "Fields": "Id,Name",
        "SortBy": "ProductionYear,SortName",
        "SortOrder": "Descending",
        "UserId": user_id
    }
    r = client.SESSION.get(f"{client.EMBY_URL}/Items", params=params, headers=hdr, timeout=15)
    r.raise_for_status()
    return r.json().get("Items", [])


def get_songs_by_album(album_id: str, hdr: Dict[str, str]) -> List[Dict[str, str]]:
    """Fetches all songs for a given album, sorted by track number."""
    user_id = hdr.get("X-Emby-User-Id")
    params = {
        "IncludeItemTypes": "Audio",
        "Recursive": "true",
        "ParentId": album_id,
        "Fields": "Id,Name,IndexNumber,ParentIndexNumber",
        "SortBy": "ParentIndexNumber,IndexNumber",
        "UserId": user_id
    }
    r = client.SESSION.get(f"{client.EMBY_URL}/Items", params=params, headers=hdr, timeout=15)
    r.raise_for_status()
    return r.json().get("Items", [])

def get_songs_by_artist(artist_id: str, hdr: Dict[str, str], sort: str = "PlayCount", limit: Optional[int] = None) -> List[Dict[str, str]]:
    """Fetches songs for an artist, with optional sorting and limiting."""
    user_id = hdr.get("X-Emby-User-Id")
    params = {
        "IncludeItemTypes": "Audio",
        "Recursive": "true",
        "ArtistIds": artist_id,
        "Fields": "Id,Name,PlayCount",
        "UserId": user_id,
        "SortBy": "Random" if sort == "Random" else "SortName",
    }

    r = client.SESSION.get(f"{client.EMBY_URL}/Items", params=params, headers=hdr, timeout=20)
    r.raise_for_status()
    songs = r.json().get("Items", [])

    if sort == "Top":
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

    r = client.SESSION.get(f"{client.EMBY_URL}/Users/{user_id}/Items", params=base_params, headers=hdr, timeout=30)
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
        elif genre_match_type == "all":
            all_songs = [
                s for s in all_songs
                if required_genres.issubset(set(g.lower() for g in s.get("Genres", [])))
            ]
        elif genre_match_type == "none":
            all_songs = [
                s for s in all_songs
                if not required_genres.intersection(set(g.lower() for g in s.get("Genres", [])))
            ]

    final_list = all_songs

    # Sorting
    sort_by = filters.get("sort_by", "Random")
    if sort_by == "Random":
        random.shuffle(final_list)
    else:
        reverse = sort_by in ("PlayCount", "DateCreated")
        final_list.sort(key=lambda s: s.get(sort_by, 0 if sort_by == "PlayCount" else ""), reverse=reverse)

    # Limiting
    limit = filters.get("limit")
    if limit is not None:
        return final_list[:int(limit)]

    return final_list