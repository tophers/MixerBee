"""
app/studios.py - Studio-related functions.
"""
import logging
from typing import Dict, List

from . import client

_studio_cache: set = set()

def get_studios(name: str, user_id: str, hdr: Dict[str, str]) -> List[Dict[str, str]]:
    """
    Searches for studios by name from an aggregated list of all studios
    in the user's library.
    """
    global _studio_cache

    if not _studio_cache:
        logging.info("Aggregating studio list for the first time...")
        params = {
            "IncludeItemTypes": "Movie",
            "Recursive": "true",
            "Fields": "Studios",
            "UserId": user_id,
        }
        try:
            r = client.SESSION.get(f"{client.EMBY_URL}/Users/{user_id}/Items", params=params, headers=hdr, timeout=60)
            r.raise_for_status()
            all_movies = r.json().get("Items", [])
            
            all_studio_names = set()
            for movie in all_movies:
                for studio in movie.get("Studios", []):
                    all_studio_names.add(studio.get("Name"))
            
            _studio_cache = all_studio_names
            logging.info(f"Cached {len(_studio_cache)} unique studio names.")

        except Exception as e:
            logging.error(f"Failed to aggregate studios: {e}", exc_info=True)
            return []

    if not name:
        return [{"Name": s} for s in sorted(list(_studio_cache))[:20]]

    search_name = name.lower()
    matching_studios = [s for s in _studio_cache if search_name in s.lower()]
    
    return [{"Name": s} for s in sorted(matching_studios)[:20]]