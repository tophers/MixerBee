"""
app/tv.py - All TV show and episode related logic.
"""
import re
import random
from itertools import islice
from typing import Tuple, Dict, List, Optional

from . import client

# TV helpers
def parse_show(arg: str) -> Tuple[str, int, int]:
    """Parses a string like 'Show::S01E01' into its components."""
    m = re.match(r"^(.*?)::S(\d+)E(\d+)$", arg, re.IGNORECASE)
    if not m:
        raise ValueError(f"Invalid format: '{arg}', expected 'Show::S3E1'")
    return m.group(1).strip(), int(m.group(2)), int(m.group(3))


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
             hdr: Dict[str, str], end_season: Optional[int] = None,
             end_episode: Optional[int] = None) -> List[Dict]:
    """Gets a list of episodes for a series, either by count or within a specified S/E range."""
    r = client.SESSION.get(f"{client.EMBY_URL}/Shows/{sid}/Episodes",
                           headers=hdr, timeout=10)
    all_eps = sorted(r.json()["Items"],
                   key=lambda x: (x.get("ParentIndexNumber", 0),
                                  x.get("IndexNumber", 0)))

    # Filter out specials, which have a season number of 0
    all_eps = [ep for ep in all_eps if ep.get("ParentIndexNumber", 0) > 0]

    start_eps = [ep for ep in all_eps
                 if ep.get("ParentIndexNumber", 0) > season
                 or (ep.get("ParentIndexNumber", 0) == season
                     and ep.get("IndexNumber", 0) >= episode)]

    if end_season is not None and end_episode is not None:
        end_eps = [ep for ep in start_eps
                     if ep.get("ParentIndexNumber", 0) < end_season
                     or (ep.get("ParentIndexNumber", 0) == end_season
                         and ep.get("IndexNumber", 0) <= end_episode)]
        return end_eps
    else:
        return list(islice(start_eps, count))


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
        "Fields": "UserData,ParentIndexNumber,IndexNumber,DateCreated"
    }
    r = client.SESSION.get(f"{client.EMBY_URL}/Shows/{series_id}/Episodes",
                           params=params, headers=hdr, timeout=15)
    r.raise_for_status()
    all_eps = sorted(r.json().get("Items", []),
                     key=lambda x: (x.get("ParentIndexNumber", 0),
                                    x.get("IndexNumber", 0)))
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


def interleave(groups: List[List[dict]]) -> List[str]:
    """Interleaves items from multiple lists and returns their IDs."""
    out = []
    for bundle in zip(*groups):
        out.extend(ep["Id"] for ep in bundle)
    return out