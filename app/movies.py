"""
app/movies.py - All movie-related logic.
"""

import random
from typing import Dict, List, Optional

from .client import SESSION, EMBY_URL


def get_movie_libraries(hdr: Dict[str, str]) -> List[Dict[str, str]]:
    """Fetches all movie libraries (folders) from Emby."""
    r = SESSION.get(f"{EMBY_URL}/Library/MediaFolders", headers=hdr, timeout=10)
    r.raise_for_status()
    all_folders = r.json().get("Items", [])
    # Filter for folders that are specifically of the 'movies' collection type
    movie_folders = [
        {"Id": f["Id"], "Name": f["Name"]}
        for f in all_folders
        if f.get("CollectionType") == "movies"
    ]
    return movie_folders


def get_movie_genres(hdr: Dict[str, str]) -> List[Dict[str, str]]:
    """Fetches all movie genres from Emby."""
    params = {"IncludeItemTypes": "Movie"}
    r = SESSION.get(f"{EMBY_URL}/Genres",
                    params=params, headers=hdr, timeout=10)
    r.raise_for_status()
    return r.json().get("Items", [])


def find_movies(user_id: str, filters: Dict,
                hdr: Dict[str, str]) -> List[Dict[str, str]]:
    """Finds movies based on a set of filters."""
    base_params = {
        "IncludeItemTypes": "Movie",
        "Recursive": "true",
        "Fields": "Genres,PremiereDate,UserData,RunTimeTicks"
    }

    if filters.get("parent_ids"):
        base_params["ParentId"] = ",".join(filters["parent_ids"])

    if filters.get("year_from"):
        base_params["MinPremiereDate"] = f"{filters['year_from']}-01-01"
    if filters.get("year_to"):
        base_params["MaxPremiereDate"] = f"{filters['year_to']}-12-31"

    r = SESSION.get(f"{EMBY_URL}/Users/{user_id}/Items", params=base_params, headers=hdr, timeout=30)
    r.raise_for_status()
    all_movies = r.json().get("Items", [])

    watched_status = filters.get("watched_status")
    if watched_status and watched_status != "all":
        is_played_target = (watched_status == "played")
        all_movies = [m for m in all_movies if m.get("UserData", {}).get("Played", False) == is_played_target]

    genres_to_search = filters.get("genres")
    if genres_to_search:
        genre_match_type = filters.get("genre_match", "any")
        required_genres = set(g.lower() for g in genres_to_search)

        if genre_match_type == "any":
            all_movies = [
                m for m in all_movies
                if required_genres.intersection(set(g.lower() for g in m.get("Genres", [])))
            ]
        else: # 'all'
            all_movies = [
                m for m in all_movies
                if required_genres.issubset(set(g.lower() for g in m.get("Genres", [])))
            ]

    final_list = all_movies

    sort_by = filters.get("sort_by", "Random")
    if sort_by == "Random":
        random.shuffle(final_list)
    else:
        reverse = sort_by in ("PremiereDate", "DateCreated")
        final_list.sort(key=lambda m: m.get(sort_by, ""), reverse=reverse)

    target_duration_minutes = filters.get("duration_minutes")
    if target_duration_minutes:
        target_duration_ticks = int(target_duration_minutes) * 60 * 10000000
        playlist_movies = []
        current_duration_ticks = 0
        for movie in final_list:
            runtime_ticks = movie.get("RunTimeTicks")
            if runtime_ticks:
                if current_duration_ticks + runtime_ticks <= target_duration_ticks:
                    playlist_movies.append(movie)
                    current_duration_ticks += runtime_ticks
        return playlist_movies

    limit = filters.get("limit")
    if limit is not None:
        return final_list[:int(limit)]

    return final_list