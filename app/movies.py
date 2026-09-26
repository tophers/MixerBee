"""
app/movies.py - All movie-related logic
"""

import random
from datetime import datetime, timedelta
from typing import Dict, List, Optional

from . import client
from app.logger import get_logger

logger = get_logger("MixerBee.Movies")

def get_movie_libraries(user_id: str, media: client.MediaClient) -> List[Dict[str, str]]:
    """Fetches all movie libraries (folders) a specific user can see."""
    logger.info(f"Fetching movie libraries for user {user_id}...")
    r = media.get(f"/Users/{user_id}/Views", timeout=10)
    r.raise_for_status()
    all_views = r.json().get("Items", [])
    movie_folders = [
        {"Id": f["Id"], "Name": f["Name"]}
        for f in all_views
        if f.get("CollectionType") == "movies"
    ]
    logger.info(f"Found {len(movie_folders)} movie libraries.")
    return movie_folders

def get_movie_genres(user_id: str, media: client.MediaClient) -> List[Dict[str, str]]:
    """Fetches all movie genres available to a specific user."""
    logger.info(f"Fetching movie genres for user {user_id} using native endpoint...")
    params = {"IncludeItemTypes": "Movie", "UserId": user_id, "SortBy": "SortName"}
    r = media.get("/Genres",
                           params=params, timeout=10)
    r.raise_for_status()
    genres = r.json().get("Items", [])
    logger.info(f"Found {len(genres)} movie genres.")
    return genres

LANGUAGE_SYNONYMS = {
    "en": {"en", "eng", "english"},
    "eng": {"en", "eng", "english"},
    "english": {"en", "eng", "english"},
    "es": {"es", "spa", "spanish", "español"},
    "spa": {"es", "spa", "spanish", "español"},
    "spanish": {"es", "spa", "spanish", "español"},
    "fr": {"fr", "fra", "fre", "french", "français"},
    "fra": {"fr", "fra", "fre", "french", "français"},
    "fre": {"fr", "fra", "fre", "french", "français"},
    "french": {"fr", "fra", "fre", "french", "français"},
    "de": {"de", "deu", "ger", "german", "deutsch"},
    "deu": {"de", "deu", "ger", "german", "deutsch"},
    "ger": {"de", "deu", "ger", "german", "deutsch"},
    "german": {"de", "deu", "ger", "german", "deutsch"},
    "it": {"it", "ita", "italian", "italiano"},
    "ita": {"it", "ita", "italian", "italiano"},
    "italian": {"it", "ita", "italian", "italiano"},
    "ja": {"ja", "jpn", "japanese"},
    "jpn": {"ja", "jpn", "japanese"},
    "japanese": {"ja", "jpn", "japanese"},
    "ko": {"ko", "kor", "korean"},
    "kor": {"ko", "kor", "korean"},
    "korean": {"ko", "kor", "korean"},
    "zh": {"zh", "zho", "chi", "chinese"},
    "zho": {"zh", "zho", "chi", "chinese"},
    "chi": {"zh", "zho", "chi", "chinese"},
    "chinese": {"zh", "zho", "chi", "chinese"},
    "pt": {"pt", "por", "portuguese", "português"},
    "por": {"pt", "por", "portuguese", "português"},
    "portuguese": {"pt", "por", "portuguese", "português"},
    "ru": {"ru", "rus", "russian"},
    "rus": {"ru", "rus", "russian"},
    "russian": {"ru", "rus", "russian"}
}

def language_matches(stream_lang: Optional[str], target_lang: str) -> bool:
    if not stream_lang or not target_lang:
        return False
    sl = stream_lang.strip().lower()
    tl = target_lang.strip().lower()
    if sl == tl:
        return True
    synonyms = LANGUAGE_SYNONYMS.get(tl, {tl})
    return sl in synonyms

def normalize_movie_filters(filters: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    if not filters:
        return {}
    normalized = dict(filters)
    if "min_runtime_minutes" in normalized and normalized["min_runtime_minutes"] is not None:
        try:
            normalized["min_runtime_minutes"] = int(normalized["min_runtime_minutes"])
        except (ValueError, TypeError):
            normalized["min_runtime_minutes"] = None
    if "max_runtime_minutes" in normalized and normalized["max_runtime_minutes"] is not None:
        try:
            normalized["max_runtime_minutes"] = int(normalized["max_runtime_minutes"])
        except (ValueError, TypeError):
            normalized["max_runtime_minutes"] = None
    if "min_community_rating" in normalized and normalized["min_community_rating"] is not None:
        try:
            normalized["min_community_rating"] = float(normalized["min_community_rating"])
        except (ValueError, TypeError):
            normalized["min_community_rating"] = None
    if "favorites_only" in normalized:
        normalized["favorites_only"] = bool(normalized["favorites_only"])
    return normalized

def matches_movie_constraints(item: Dict[str, Any], filters: Dict[str, Any]) -> bool:
    """Pure predicate evaluating Section 7 practical viewing constraints against a movie item."""
    if not filters or not item:
        return True

    runtime_ticks = item.get("RunTimeTicks")
    min_runtime = filters.get("min_runtime_minutes")
    max_runtime = filters.get("max_runtime_minutes")

    if min_runtime is not None or max_runtime is not None:
        if runtime_ticks is None or runtime_ticks <= 0:
            return False
        runtime_minutes = runtime_ticks / 600_000_000.0
        if min_runtime is not None and runtime_minutes < min_runtime:
            return False
        if max_runtime is not None and runtime_minutes > max_runtime:
            return False

    min_rating = filters.get("min_community_rating")
    if min_rating is not None and min_rating > 0:
        comm_rating = item.get("CommunityRating")
        if comm_rating is None:
            return False
        try:
            if float(comm_rating) < float(min_rating):
                return False
        except (ValueError, TypeError):
            return False

    if filters.get("favorites_only"):
        user_data = item.get("UserData") or {}
        if not user_data.get("IsFavorite", False):
            return False

    allowed_ratings = filters.get("allowed_content_ratings")
    if allowed_ratings:
        norm_allowed = {r.strip().lower() for r in allowed_ratings if r and r.strip()}
        if norm_allowed:
            off_rating = (item.get("OfficialRating") or "").strip().lower()
            if not off_rating:
                if "unrated" not in norm_allowed and "unknown" not in norm_allowed:
                    return False
            else:
                if off_rating not in norm_allowed:
                    return False

    audio_languages = filters.get("audio_languages")
    if audio_languages:
        media_streams = item.get("MediaStreams") or []
        audio_streams = [s for s in media_streams if s.get("Type") == "Audio"]
        matched_audio = False
        for req_lang in audio_languages:
            if any(language_matches(s.get("Language"), req_lang) for s in audio_streams):
                matched_audio = True
                break
        if not matched_audio:
            return False

    subtitle_languages = filters.get("subtitle_languages")
    if subtitle_languages:
        media_streams = item.get("MediaStreams") or []
        sub_streams = [s for s in media_streams if s.get("Type") == "Subtitle"]
        matched_sub = False
        for req_lang in subtitle_languages:
            if any(language_matches(s.get("Language"), req_lang) for s in sub_streams):
                matched_sub = True
                break
        if not matched_sub:
            return False

    return True

def find_movies(user_id: str, filters: Dict,
                media: client.MediaClient) -> List[Dict[str, str]]:
    """Finds movies based on a set of filters."""
    filters = normalize_movie_filters(filters)
    logger.info(f"Finding movies for user {user_id} with filters: {filters}")

    base_params = {
        "IncludeItemTypes": "Movie",
        "Recursive": "true",
        "Fields": "Genres,PremiereDate,UserData,RunTimeTicks,Studios,People,OfficialRating,CommunityRating,MediaStreams",
        "Limit": 2000
    }

    if filters.get("parent_ids"):
        base_params["ParentIds"] = ",".join(filters["parent_ids"])

    if filters.get("ids"):
        base_params["Ids"] = ",".join(filters["ids"])

    relative_days = filters.get("release_within_days")
    if relative_days and int(relative_days) > 0:
        start_date = datetime.now() - timedelta(days=int(relative_days))
        base_params["MinPremiereDate"] = start_date.strftime("%Y-%m-%d")
    elif filters.get("year_from"):
        base_params["MinPremiereDate"] = f"{filters['year_from']}-01-01"

    if filters.get("year_to"):
        base_params["MaxPremiereDate"] = f"{filters['year_to']}-12-31"

    watched_status = filters.get("watched_status")
    if watched_status == "unplayed":
        base_params["IsPlayed"] = "false"
    elif watched_status == "played":
        base_params["IsPlayed"] = "true"

    sort_by = filters.get("sort_by", "Random")
    if sort_by == "Random":
        base_params["SortBy"] = "Random"
    else:
        base_params["SortBy"] = sort_by
        # Added CommunityRating and CriticRating to force Descending order
        if sort_by in ("DateCreated", "CommunityRating", "CriticRating"):
            base_params["SortOrder"] = "Descending"

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
        endpoint_url = "/Items"
    else:
        endpoint_url = f"/Users/{user_id}/Items"

    r = media.get(endpoint_url, params=base_params, timeout=30)
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

    all_movies = [m for m in all_movies if matches_movie_constraints(m, filters)]

    final_list = all_movies
    logger.info(f"Local filtering complete. {len(final_list)} movies match criteria.")

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