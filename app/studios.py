"""
app/studios.py - Studio-related functions.
"""

import logging
from typing import Dict, List, Any
from . import client

def aggregate_all_studios(user_id: str, hdr: Dict[str, str]) -> List[str]:
    """Called by the background cache refresher to get all studios."""
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

        all_studio_names = {
            studio.get("Name") 
            for movie in all_movies 
            for studio in (movie.get("Studios") or [])
            if studio.get("Name")
        }
        
        logging.info(f"STUDIO CACHE: Successfully aggregated {len(all_studio_names)} unique studios.")
        return sorted(list(all_studio_names))
        
    except Exception as e:
        logging.error(f"STUDIO CACHE: Failed to aggregate studios: {e}", exc_info=True)
        return []

# app/studios.py

def get_studios(name: str, library_data: Dict[str, Any]) -> List[Dict[str, str]]:
    """
    Utility: Searches a provided library data dictionary for studios.
    No longer needs user_id or hdr because it doesn't touch the network.
    """
    cached_studios = library_data.get("studioData", [])

    if not name:
        return [{"Name": s} for s in cached_studios[:20]]

    search_name = name.lower()
    matching_studios = [s for s in cached_studios if search_name in s.lower()]

    return [{"Name": s} for s in matching_studios[:20]]