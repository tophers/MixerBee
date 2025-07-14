"""
app/movies.py - All movie-related logic.
"""

import random
from typing import Dict, List, Optional

from . import client


def get_movie_libraries(user_id: str, hdr: Dict[str, str]) -> List[Dict[str, str]]:
    """Fetches all movie libraries (folders) a specific user can see."""
    r = client.SESSION.get(f"{client.EMBY_URL}/Users/{user_id}/Views", headers=hdr, timeout=10)
    r.raise_for_status()
    all_views = r.json().get("Items", [])
    movie_folders = [
        {"Id": f["Id"], "Name": f["Name"]}
        for f in all_views
        if f.get("CollectionType") == "movies"
    ]
    return movie_folders


def get_movie_genres(user_id: str, hdr: Dict[str, str]) -> List[Dict[str, str]]:
    """Fetches all movie genres available to a specific user."""
    params = {"IncludeItemTypes": "Movie", "UserId": user_id}
    r = client.SESSION.get(f"{client.EMBY_URL}/Genres",
                      params=params, headers=hdr, timeout=10)
    r.raise_for_status()
    return r.json().get("Items", [])

def find_movies(user_id: str, filters: Dict,
                hdr: Dict[str, str]) -> List[Dict[str, str]]:
    """Finds movies based on a set of filters."""
    base_params = {
        "IncludeItemTypes": "Movie",
        "Recursive": "true",
        "Fields": "Genres,PremiereDate,UserData,RunTimeTicks,Studios"
    }

    if filters.get("parent_ids"):
        base_params["ParentId"] = ",".join(filters["parent_ids"])

    if filters.get("year_from"):
        base_params["MinPremiereDate"] = f"{filters['year_from']}-01-01"
    if filters.get("year_to"):
        base_params["MaxPremiereDate"] = f"{filters['year_to']}-12-31"
    
    people_filter = filters.get("people")
    if people_filter:
        person_ids = [p.get("Id") for p in people_filter if p.get("Id")]
        if person_ids:
            base_params["PersonIds"] = ",".join(person_ids)

    exclude_people_filter = filters.get("exclude_people")
    if exclude_people_filter:
        exclude_person_ids = [p.get("Id") for p in exclude_people_filter if p.get("Id")]
        if exclude_person_ids:
            base_params["ExcludePersonIds"] = ",".join(exclude_person_ids)

    if "PersonIds" in base_params or "ExcludePersonIds" in base_params:
        base_params["UserId"] = user_id 
        endpoint_url = f"{client.EMBY_URL}/Items"
    else:
        endpoint_url = f"{client.EMBY_URL}/Users/{user_id}/Items"

    r = client.SESSION.get(endpoint_url, params=base_params, headers=hdr, timeout=30)
    
    r.raise_for_status()
    all_movies = r.json().get("Items", [])

    studios_to_search = filters.get("studios")
    if studios_to_search:
        search_terms = [s.lower() for s in studios_to_search]
        
        def has_matching_studio(movie):
            movie_studios = [s.get("Name", "").lower() for s in movie.get("Studios", [])]
            for movie_studio in movie_studios:
                for term in search_terms:
                    if term in movie_studio:
                        return True
            return False

        all_movies = [m for m in all_movies if has_matching_studio(m)]

    studios_to_exclude = filters.get("exclude_studios")
    if studios_to_exclude:
        exclude_terms = [s.lower() for s in studios_to_exclude]

        def has_excluded_studio(movie):
            movie_studios = [s.get("Name", "").lower() for s in movie.get("Studios", [])]
            for movie_studio in movie_studios:
                for term in exclude_terms:
                    if term in movie_studio:
                        return True
            return False

        all_movies = [m for m in all_movies if not has_excluded_studio(m)]

    watched_status = filters.get("watched_status")
    if watched_status and watched_status != "all":
        is_played_target = (watched_status == "played")
        all_movies = [m for m in all_movies if m.get("UserData", {}).get("Played", False) == is_played_target]

    def get_movie_genre_set(movie):
        return {g.lower() for g in movie.get("Genres", [])}

    genres_any = filters.get("genres_any")
    if genres_any:
        required_genres_any = {g.lower() for g in genres_any}
        all_movies = [m for m in all_movies if get_movie_genre_set(m).intersection(required_genres_any)]

    genres_all = filters.get("genres_all")
    if genres_all:
        required_genres_all = {g.lower() for g in genres_all}
        all_movies = [m for m in all_movies if required_genres_all.issubset(get_movie_genre_set(m))]

    genres_exclude = filters.get("genres_exclude")
    if genres_exclude:
        exclude_genres = {g.lower() for g in genres_exclude}
        all_movies = [m for m in all_movies if not get_movie_genre_set(m).intersection(exclude_genres)]

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