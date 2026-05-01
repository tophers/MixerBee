"""
app/studios.py - Studio-related functions
"""

from typing import Dict, List, Any
from . import client
from app.logger import get_logger

logger = get_logger("MixerBee.Studios")

def aggregate_all_studios(user_id: str, hdr: Dict[str, str]) -> List[str]:
    """Called by the background cache refresher to get all studios."""
    logger.info(f"Fetching all movie studios for user {user_id} using native endpoint...")
    
    try:
        params = {
            "UserId": user_id,
            "Limit": 5000 
        }
        
        r = client.SESSION.get(f"{client.EMBY_URL}/Studios", params=params, headers=hdr, timeout=30)
        r.raise_for_status()
        
        studios_batch = r.json().get("Items", [])
        studio_names = [s.get("Name") for s in studios_batch if s.get("Name")]
        
        logger.info(f"Successfully fetched {len(studio_names)} unique studios.")
        return sorted(studio_names)
        
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
        return [{"Name": s} for s in cached_studios[:100]]

    search_name = name.lower()
    matching_studios = [s for s in cached_studios if search_name in s.lower()]

    return [{"Name": s} for s in matching_studios[:100]]