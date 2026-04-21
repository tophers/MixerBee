"""
app/movies.py - All movie-related logic
"""

import random
import logging
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
        "Fields": "Genres,PremiereDate,UserData,RunTimeTicks,Studios,People",
        "Limit": 2000
    }

    if filters.get("parent_ids"):
        base_params["ParentIds"] = ",".join(filters["parent_ids"])

    if filters.get("ids"):
        base_params["Ids"] = ",".join(filters["ids"])

    if filters.get("year_from"):
        base_params["MinPremiereDate"] = f"{filters['year_from']}-01-01"
    if filters.get("year_to"):
        base_params["MaxPremiereDate"] = f"{filters['year_to']}-12-31"

    people_any = filters.get("people", [])
    people_all = filters.get("people_all", [])
    combined_people = people_any + people_all

    if combined_people:
        person_ids = []
        person_names = []
        person_types = set()

        for p in combined_people:
            p_id = p.get("Id") if isinstance(p, dict) else None
            p_name = p.get("Name") if isinstance(p, dict) else (p if isinstance(p, str) else None)

            if p_id:
                person_ids.append(p_id)
            elif p_name:
                person_names.append(p_name)

            role = p.get("Role", "") if isinstance(p, dict) else ""
            if role and role.lower() not in ["person", "any", ""]:
                person_types.add(role)

        if person_ids:
            base_params["PersonIds"] = ",".join(person_ids)
        if person_names:
            base_params["People"] = ",".join(person_names)
        if person_types:
            base_params["PersonTypes"] = ",".join(person_types)

    exclude_people_filter = filters.get("exclude_people")
    if exclude_people_filter:
        exclude_person_ids = []
        for p in exclude_people_filter:
            p_id = p.get("Id") if isinstance(p, dict) else p
            if p_id:
                exclude_person_ids.append(p_id)
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

    # --- AND Logic for People ---
    if people_all:
        required_ids = {p["Id"] for p in people_all if isinstance(p, dict) and p.get("Id")}
        required_names = {p["Name"].lower() for p in people_all if isinstance(p, dict) and not p.get("Id") and p.get("Name")}

        filtered_by_people = []
        for m in all_movies:
            movie_people = m.get("People", [])
            movie_person_ids = {p.get("Id") for p in movie_people}
            movie_person_names = {p.get("Name", "").lower() for p in movie_people}

            id_match = required_ids.issubset(movie_person_ids) if required_ids else True
            name_match = required_names.issubset(movie_person_names) if required_names else True

            if id_match and name_match:
                filtered_by_people.append(m)
        all_movies = filtered_by_people

    # --- Studio Filtering ---
    def get_movie_studio_set(movie):
        return {s.get("Name", "").lower() for s in movie.get("Studios", []) if s.get("Name")}

    studios_to_search = filters.get("studios")
    if studios_to_search:
        required_studios = {s.lower() for s in studios_to_search}
        all_movies = [m for m in all_movies if get_movie_studio_set(m).intersection(required_studios)]

    studios_to_exclude = filters.get("exclude_studios")
    if studios_to_exclude:
        exclude_studios = {s.lower() for s in studios_to_exclude}
        all_movies = [m for m in all_movies if not get_movie_studio_set(m).intersection(exclude_studios)]

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
        reverse = (sort_by == "DateCreated")
        final_list.sort(key=lambda m: m.get(sort_by) or "", reverse=reverse)

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
    if limit:
        return final_list[:int(limit)]

    return final_list