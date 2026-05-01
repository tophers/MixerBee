"""
app/music.py - All music-related logic
"""

import random
from typing import Dict, List, Optional
import requests

from . import client
from app.logger import get_logger

logger = get_logger("MixerBee.Music")

def get_music_genres(user_id: str, hdr: Dict[str, str]) -> List[Dict[str, str]]:
    """
    Fetches all music genres for a user by aggregating them from all albums.
    """
    logger.info(f"Aggregating music genres for user {user_id}. Using MusicAlbums to optimize payload...")

    params = {
        "IncludeItemTypes": "MusicAlbum",
        "Recursive": "true",
        "Fields": "Genres",
        "UserId": user_id
    }

    try:
        r = client.SESSION.get(f"{client.EMBY_URL}/Users/{user_id}/Items", params=params, headers=hdr, timeout=60)
        r.raise_for_status()

        all_albums = r.json().get("Items", [])

        if not all_albums:
            logger.info(f"No music albums found for user {user_id}. Returning empty genre list.")
            return []

        unique_genres = set()
        for album in all_albums:
            for genre_name in album.get("Genres", []):
                unique_genres.add(genre_name)

        logger.info(f"Found {len(unique_genres)} unique music genres for user {user_id} across {len(all_albums)} albums.")

        genre_list = [{"Name": name, "Id": name} for name in sorted(list(unique_genres))]
        return genre_list

    except Exception as e:
        logger.error(f"Failed to aggregate music genres for user {user_id}: {e}", exc_info=True)
        return []

def get_music_artists(hdr: Dict[str, str]) -> List[Dict[str, str]]:
    """Fetches all music artists from Emby for the user specified in the header."""
    user_id = hdr.get("X-Emby-User-Id")
    logger.info(f"Fetching all music album artists for user {user_id}...")
    params = {
        "Recursive": "true",
        "Fields": "Id,Name",
        "SortBy": "SortName",
        "UserId": user_id,
        "AlbumArtistOnly": "true"
    }
    r = client.SESSION.get(f"{client.EMBY_URL}/Artists", params=params, headers=hdr, timeout=20)
    r.raise_for_status()
    artists = r.json().get("Items", [])
    logger.info(f"Found {len(artists)} music album artists.")
    return artists

def get_random_artist(hdr: Dict[str, str]) -> Optional[Dict[str, str]]:
    """Fetches a random music artist directly via the API."""
    user_id = hdr.get("X-Emby-User-Id")
    logger.info("Fetching a random music artist natively...")
    params = {
        "IncludeItemTypes": "MusicArtist",
        "Recursive": "true",
        "SortBy": "Random",
        "Limit": 1,
        "UserId": user_id
    }
    try:
        r = client.SESSION.get(f"{client.EMBY_URL}/Items", params=params, headers=hdr, timeout=10)
        r.raise_for_status()
        items = r.json().get("Items", [])
        if items:
            return items[0]
    except Exception as e:
        logger.error(f"Failed to fetch random artist: {e}")
    return None

def get_random_album(hdr: Dict[str, str]) -> Optional[Dict[str, str]]:
    """Fetches a random music album directly via the API."""
    user_id = hdr.get("X-Emby-User-Id")
    logger.info("Fetching a random music album natively...")
    params = {
        "IncludeItemTypes": "MusicAlbum",
        "Recursive": "true",
        "Fields": "Id,Name,ArtistItems",
        "SortBy": "Random",
        "Limit": 1,
        "UserId": user_id
    }
    try:
        r = client.SESSION.get(f"{client.EMBY_URL}/Items", params=params, headers=hdr, timeout=10)
        r.raise_for_status()
        items = r.json().get("Items", [])
        if items:
            return items[0]
    except Exception as e:
        logger.error(f"Failed to fetch random album: {e}")
    return None

def get_albums_by_artist(artist_id: str, hdr: Dict[str, str]) -> List[Dict[str, str]]:
    """Fetches all albums for a given artist."""
    user_id = hdr.get("X-Emby-User-Id")
    logger.info(f"Fetching albums for artist ID {artist_id}...")
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
    albums = r.json().get("Items", [])
    logger.info(f"Found {len(albums)} albums.")
    return albums


def get_songs_by_album(album_id: str, hdr: Dict[str, str]) -> List[Dict[str, str]]:
    """Fetches all songs for a given album, sorted by track number."""
    user_id = hdr.get("X-Emby-User-Id")
    logger.info(f"Fetching songs for album ID {album_id}...")
    params = {
        "IncludeItemTypes": "Audio",
        "Recursive": "true",
        "ParentId": album_id,
        "Fields": "Id,Name,IndexNumber,ParentIndexNumber,ArtistItems,Album",
        "SortBy": "ParentIndexNumber,IndexNumber",
        "UserId": user_id
    }
    r = client.SESSION.get(f"{client.EMBY_URL}/Items", params=params, headers=hdr, timeout=15)
    r.raise_for_status()
    songs = r.json().get("Items", [])
    logger.info(f"Found {len(songs)} songs.")
    return songs

def get_songs_by_artist(artist_id: str, hdr: Dict[str, str], sort: str = "PlayCount", limit: Optional[int] = None) -> List[Dict[str, str]]:
    """Fetches songs for an artist, fully leveraging API sorting and limits."""
    user_id = hdr.get("X-Emby-User-Id")
    logger.info(f"Fetching songs for artist ID {artist_id} (Sort: {sort}, Limit: {limit})...")
    params = {
        "IncludeItemTypes": "Audio",
        "Recursive": "true",
        "ArtistIds": artist_id,
        "Fields": "Id,Name,PlayCount,ArtistItems,Album",
        "UserId": user_id,
    }

    if sort == "Random":
        params["SortBy"] = "Random"
    elif sort == "Top" or sort == "PlayCount":
        params["SortBy"] = "PlayCount"
        params["SortOrder"] = "Descending"
    else:
        params["SortBy"] = "SortName"

    if limit:
        params["Limit"] = limit

    r = client.SESSION.get(f"{client.EMBY_URL}/Items", params=params, headers=hdr, timeout=20)
    r.raise_for_status()
    songs = r.json().get("Items", [])

    logger.info(f"Returning {len(songs)} tracks for artist.")
    return songs

def find_songs(user_id: str, filters: Dict, hdr: Dict[str, str]) -> List[Dict[str, str]]:
    """Finds songs based on a set of filters, utilizing API randomness where possible."""
    logger.info(f"Finding songs for user {user_id} with filters: {filters}")
    
    base_params = {
        "IncludeItemTypes": "Audio",
        "Recursive": "true",
        "UserId": user_id,
        "Fields": "Genres,UserData,PlayCount,ArtistItems,Album",
        "Limit": 3000
    }

    sort_by = filters.get("sort_by", "Random")
    if sort_by == "Random":
        base_params["SortBy"] = "Random"
    else:
        base_params["SortBy"] = sort_by
        if sort_by in ("PlayCount", "DateCreated"):
            base_params["SortOrder"] = "Descending"

    r = client.SESSION.get(f"{client.EMBY_URL}/Users/{user_id}/Items", params=base_params, headers=hdr, timeout=30)
    r.raise_for_status()
    all_songs = r.json().get("Items", [])
    logger.info(f"Retrieved {len(all_songs)} initial songs from API.")

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
    logger.info(f"Local filtering complete. {len(final_list)} songs match criteria.")

    limit = filters.get("limit")
    if limit is not None:
        logger.info(f"Applying count limit. Returning {int(limit)} songs.")
        return final_list[:int(limit)]

    return final_list