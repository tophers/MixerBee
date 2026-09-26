"""
app/users.py - User-related functions
"""

from typing import Dict, List, Optional

from . import client


def all_users(media: client.MediaClient) -> List[dict]:
    """Fetches a list of all users on the Emby server."""
    r = media.get("/Users", timeout=10)
    r.raise_for_status()
    return r.json()


def user_id_by_name(name: str, media: client.MediaClient) -> Optional[str]:
    """Finds a user's ID by their username."""
    for u in all_users(media):
        if u.get("Name", "").lower() == name.lower():
            return u["Id"]
    return None