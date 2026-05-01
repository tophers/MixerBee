"""
app/tv.py - All TV show and episode related logic
"""

import random
from typing import Dict, List, Optional

from . import client
from app.logger import get_logger

logger = get_logger("MixerBee.TV")

def get_all_series(user_id: str, hdr: Dict[str, str]) -> List[Dict[str, str]]:
    """Fetches a complete list of all TV Series for a given user."""
    logger.info(f"Fetching all TV series for user {user_id}...")
    r = client.SESSION.get(
        f"{client.EMBY_URL}/Users/{user_id}/Items",
        params={"IncludeItemTypes": "Series", "Recursive": "true"},
        headers=hdr, timeout=10,
    )
    r.raise_for_status()
    items = r.json().get("Items", [])
    logger.info(f"Found {len(items)} TV series.")
    return [{"id": it["Id"], "name": it["Name"]} for it in items]

def search_series(name: str, hdr: Dict[str, str]) -> List[Dict[str, str]]:
    """Searches for a series by name and returns a list of matches."""
    logger.info(f"Searching for TV series matching: '{name}'")
    r = client.SESSION.get(f"{client.EMBY_URL}/Items",
                           params={"IncludeItemTypes": "Series",
                                   "SearchTerm": name,
                                   "Recursive": "true"},
                           headers=hdr, timeout=10)
    r.raise_for_status()
    items = r.json().get("Items", [])
    logger.info(f"Found {len(items)} matches for '{name}'.")
    return [{"Id": it["Id"], "Name": it["Name"]} for it in items]

def series_id(name: str, hdr: Dict[str, str]) -> Optional[str]:
    """Finds the exact series ID for a given name."""
    r = client.SESSION.get(f"{client.EMBY_URL}/Items",
                           params={"IncludeItemTypes": "Series",
                                   "SearchTerm": name, "Recursive": "true"},
                           headers=hdr, timeout=10)
    for it in r.json().get("Items", []):
        if it["Name"].lower() == name.lower():
            return it["Id"]
    return None

def episodes(sid: str, season: int, episode: int, count: int,
             hdr: Dict[str, str], user_id: str, end_season: Optional[int] = None,
             end_episode: Optional[int] = None, only_unwatched: bool = True) -> List[Dict]:
    """
    Gets a list of episodes for a series, either by count or within a specified S/E range.
    Respects the only_unwatched flag to allow for rewatches.
    """
    params = {
        "UserId": user_id,
        "Fields": "UserData,ParentIndexNumber,IndexNumber"
    }

    if only_unwatched:
        params["IsPlayed"] = "false"

    try:
        r = client.SESSION.get(f"{client.EMBY_URL}/Shows/{sid}/Episodes",
                               params=params, headers=hdr, timeout=10)
        r.raise_for_status()

        all_eps = sorted(r.json()["Items"],
                         key=lambda x: (x.get("ParentIndexNumber") or 0,
                                        x.get("IndexNumber") or 0))

        all_eps = [ep for ep in all_eps if ep.get("ParentIndexNumber", 0) > 0]

        start_eps = [ep for ep in all_eps
                     if ep.get("ParentIndexNumber", 0) > season
                     or (ep.get("ParentIndexNumber", 0) == season
                         and ep.get("IndexNumber", 0) >= episode)]

        if end_season is not None and end_episode is not None:
            ranged_eps = [ep for ep in start_eps
                          if ep.get("ParentIndexNumber", 0) < end_season
                          or (ep.get("ParentIndexNumber", 0) == end_season
                              and ep.get("IndexNumber", 0) <= end_episode)]

            return ranged_eps
        else:
            return start_eps[:count]

    except Exception as e:
        logger.warning(f"TV: Failed to fetch episodes for series {sid}: {e}")
        return []

def get_specific_episode(series_id: str, season: int,
                         episode: int, hdr: Dict[str, str]) -> Optional[Dict]:
    """Gets data for a single, specific episode."""
    try:
        r = client.SESSION.get(f"{client.EMBY_URL}/Shows/{series_id}/Episodes",
                               params={"Season": season,
                                       "Fields": "Name,ParentIndexNumber,IndexNumber"},
                               headers=hdr, timeout=10)
        r.raise_for_status()
        items = r.json().get("Items", [])

        for item in items:
            if item.get("IndexNumber") == episode:
                return item
    except Exception:
        pass
    return None

def get_first_available_episode(series_id: str, user_id: str, hdr: Dict[str, str]) -> Optional[Dict]:
    """Finds the very first available episode for a series in the user's library (e.g. if they only have S9)."""
    params = {
        "UserId": user_id,
        "Fields": "Name,ParentIndexNumber,IndexNumber"
    }
    try:
        r = client.SESSION.get(f"{client.EMBY_URL}/Shows/{series_id}/Episodes",
                               params=params, headers=hdr, timeout=15)
        r.raise_for_status()

        all_eps = sorted(r.json().get("Items", []),
                         key=lambda x: (x.get("ParentIndexNumber") or 0,
                                        x.get("IndexNumber") or 0))

        for ep in all_eps:
            if ep.get("ParentIndexNumber", 0) > 0:
                return ep

    except Exception as e:
        logger.warning(f"TV: Failed to find first available episode for series {series_id}: {e}")

    return None

def get_first_unwatched_episode(series_id: str, user_id: str,
                                hdr: Dict[str, str]) -> Optional[Dict]:
    """Finds the first unwatched episode for a series for a given user."""
    params = {
        "UserId": user_id,
        "IsPlayed": "false",
        "Fields": "Name,UserData,ParentIndexNumber,IndexNumber,DateCreated"
    }
    try:
        r = client.SESSION.get(f"{client.EMBY_URL}/Shows/{series_id}/Episodes",
                               params=params, headers=hdr, timeout=15)
        r.raise_for_status()

        all_eps = sorted(r.json().get("Items", []),
                         key=lambda x: (x.get("ParentIndexNumber") or 0,
                                        x.get("IndexNumber") or 0))

        for ep in all_eps:
            if ep.get("ParentIndexNumber", 0) > 0:
                return ep

    except Exception as e:
        logger.warning(f"TV: Failed to find unwatched episodes for series {series_id}: {e}")

    return None

def get_random_unwatched_episode(series_id: str, user_id: str,
                                 hdr: Dict[str, str]) -> Optional[Dict]:
    """Finds a random unwatched episode for a series for a given user."""
    params = {
        "UserId": user_id,
        "IsPlayed": "false",
        "SortBy": "Random",
        "Limit": 20,
        "Fields": "UserData,ParentIndexNumber,IndexNumber"
    }
    try:
        r = client.SESSION.get(f"{client.EMBY_URL}/Shows/{series_id}/Episodes",
                               params=params, headers=hdr, timeout=15)
        r.raise_for_status()
        all_eps = r.json().get("Items", [])

        valid_eps = [ep for ep in all_eps if ep.get("ParentIndexNumber", 0) > 0]

        if valid_eps:
            random_ep = valid_eps[0]
            return {
                "season": random_ep.get("ParentIndexNumber", 1),
                "episode": random_ep.get("IndexNumber", 1)
            }

        params.pop("IsPlayed")
        r = client.SESSION.get(f"{client.EMBY_URL}/Shows/{series_id}/Episodes",
                               params=params, headers=hdr, timeout=15)
        r.raise_for_status()
        all_eps = r.json().get("Items", [])
        valid_eps = [ep for ep in all_eps if ep.get("ParentIndexNumber", 0) > 0]

        if valid_eps:
            random_ep = valid_eps[0]
            return {
                "season": random_ep.get("ParentIndexNumber", 1),
                "episode": random_ep.get("IndexNumber", 1)
            }

    except Exception as e:
        logger.warning(f"TV: Failed to find random episode for series {series_id}: {e}")

    return None

def mark_unplayed(series_id: str, user_id: str, hdr: Dict[str, str], season_number: Optional[int] = None) -> bool:
    """Removes the watch history for an entire series or a specific season."""
    target_id = series_id

    if season_number is not None:
        try:
            r = client.SESSION.get(f"{client.EMBY_URL}/Shows/{series_id}/Seasons",
                                   params={"UserId": user_id}, headers=hdr, timeout=10)
            r.raise_for_status()
            seasons = r.json().get("Items", [])

            for s in seasons:
                if s.get("IndexNumber") == season_number:
                    target_id = s.get("Id")
                    break

            if target_id == series_id:
                return False
        except Exception:
            return False

    logger.info(f"Marking item {target_id} as unplayed for user {user_id}")
    r = client.SESSION.delete(f"{client.EMBY_URL}/Users/{user_id}/PlayedItems/{target_id}", headers=hdr, timeout=10)
    r.raise_for_status()
    return True
