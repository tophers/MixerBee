"""
app/users.py - User-related functions.
"""

from typing import Dict, List, Optional

from . import client


def all_users(hdr: Dict[str, str]) -> List[dict]:
    """Fetches a list of all users on the Emby server."""
    r = client.SESSION.get(f"{client.EMBY_URL}/Users", headers=hdr, timeout=10)
    r.raise_for_status()
    return r.json()


def user_id_by_name(name: str, hdr: Dict[str, str]) -> Optional[str]:
    """Finds a user's ID by their username."""
    for u in all_users(hdr):
        if u.get("Name", "").lower() == name.lower():
            return u["Id"]
    return None