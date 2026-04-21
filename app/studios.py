"""
app/studios.py - Studio-related functions
"""

from typing import Dict, List, Any
from . import client
from app.logger import get_logger

logger = get_logger("MixerBee.Studios")

def aggregate_all_studios(user_id: str, hdr: Dict[str, str]) -> List[str]:
    """Called by the background cache refresher to get all studios."""
    logger.info(f"Aggregating movie studios for user {user_id}. Using pagination to optimize payload...")
    
    all_studio_names = set()
    start_index = 0
    limit = 5000
    total_movies_processed = 0

    try:
        while True:
            params = {
                "IncludeItemTypes": "Movie",
                "Recursive": "true",
                "Fields": "Studios",
                "UserId": user_id,
                "StartIndex": start_index,
                "Limit": limit
            }
            
            r = client.SESSION.get(f"{client.EMBY_URL}/Users/{user_id}/Items", params=params, headers=hdr, timeout=60)
            r.raise_for_status()
            
            movies_batch = r.json().get("Items", [])
            if not movies_batch:
                break 
                
            for movie in movies_batch:
                for studio in (movie.get("Studios") or []):
                    if name := studio.get("Name"):
                        all_studio_names.add(name)
                        
            total_movies_processed += len(movies_batch)
            
            if len(movies_batch) < limit:
                break  
                
            start_index += limit

        logger.info(f"Successfully aggregated {len(all_studio_names)} unique studios across {total_movies_processed} movies.")
        return sorted(list(all_studio_names))
        
    except Exception as e:
        logger.error(f"Failed to aggregate studios: {e}", exc_info=True)
        return []

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