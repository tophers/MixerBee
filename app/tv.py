"""
app/tv.py - All TV show and episode related logic.
"""

import re
import random
from typing import Tuple, Dict, List, Optional

from . import client

def get_all_series(user_id: str, hdr: Dict[str, str]) -> List[Dict[str, str]]:
    """Fetches a complete list of all TV Series for a given user."""
    r = client.SESSION.get(
        f"{client.EMBY_URL}/Users/{user_id}/Items",
        params={"IncludeItemTypes": "Series", "Recursive": "true"},
        headers=hdr, timeout=10,
    )
    r.raise_for_status()
    items = r.json().get("Items", [])
    return [{"id": it["Id"], "name": it["Name"]} for it in items]

def search_series(name: str, hdr: Dict[str, str]) -> List[Dict[str, str]]:
    """Searches for a series by name and returns a list of matches."""
    r = client.SESSION.get(f"{client.EMBY_URL}/Items",
                           params={"IncludeItemTypes": "Series",
                                   "SearchTerm": name,
                                   "Recursive": "true"},
                           headers=hdr, timeout=10)
    r.raise_for_status()
    items = r.json().get("Items", [])
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
        "userId": user_id,
        "Fields": "UserData,ParentIndexNumber,IndexNumber"
    }
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
        
        if only_unwatched:
            return [ep for ep in ranged_eps if not ep.get("UserData", {}).get("Played", False)]
        return ranged_eps
    else:
        result_eps = []
        for ep in start_eps:
            is_played = ep.get("UserData", {}).get("Played", False)
            if not only_unwatched or not is_played:
                result_eps.append(ep)
            if len(result_eps) >= count:
                break
        return result_eps


def get_specific_episode(series_id: str, season: int,
                         episode: int, hdr: Dict[str, str]) -> Optional[Dict]:
    """Gets data for a single, specific episode."""
    r = client.SESSION.get(f"{client.EMBY_URL}/Shows/{series_id}/Episodes",
                           params={"Season": season,
                                   "Fields": "Name,ParentIndexNumber,IndexNumber"},
                           headers=hdr, timeout=10)
    r.raise_for_status()
    items = r.json().get("Items", [])

    for item in items:
        if item.get("IndexNumber") == episode:
            return item

    return None

def get_first_unwatched_episode(series_id: str, user_id: str,
                                hdr: Dict[str, str]) -> Optional[Dict]:
    """Finds the first unwatched episode for a series for a given user."""
    params = {
        "userId": user_id,
        "Fields": "Name,UserData,ParentIndexNumber,IndexNumber,DateCreated"
    }
    r = client.SESSION.get(f"{client.EMBY_URL}/Shows/{series_id}/Episodes",
                           params=params, headers=hdr, timeout=15)
    r.raise_for_status()
    all_eps = sorted(r.json().get("Items", []),
                     key=lambda x: (x.get("ParentIndexNumber") or 0,
                                    x.get("IndexNumber") or 0))
    regular_eps = [ep for ep in all_eps if ep.get("ParentIndexNumber", 0) > 0]
    for ep in regular_eps:
        user_data = ep.get("UserData", {})
        if not user_data.get("Played"):
            return ep

    if regular_eps:
        return regular_eps[0]

    return None

def get_random_unwatched_episode(series_id: str, user_id: str,
                                 hdr: Dict[str, str]) -> Optional[Dict]:
    """Finds a random unwatched episode for a series for a given user."""
    params = {
        "userId": user_id,
        "Fields": "UserData,ParentIndexNumber,IndexNumber"
    }
    r = client.SESSION.get(f"{client.EMBY_URL}/Shows/{series_id}/Episodes",
                           params=params, headers=hdr, timeout=15)
    r.raise_for_status()
    all_eps = r.json().get("Items", [])
    unwatched_eps = [
        ep for ep in all_eps
        if ep.get("ParentIndexNumber", 0) > 0 and not ep.get("UserData", {}).get("Played")
    ]
    if unwatched_eps:
        random_ep = random.choice(unwatched_eps)
        return {
            "season": random_ep.get("ParentIndexNumber", 1),
            "episode": random_ep.get("IndexNumber", 1)
        }
    regular_eps = [ep for ep in all_eps if ep.get("ParentIndexNumber", 0) > 0]
    if regular_eps:
        random_ep = random.choice(regular_eps)
        return {
            "season": random_ep.get("ParentIndexNumber", 1),
            "episode": random_ep.get("IndexNumber", 1)
        }
    return None
