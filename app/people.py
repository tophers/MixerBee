"""
app/people.py - Person-related functions (actors, directors, etc.).
"""
from typing import Dict, List

from . import client


def get_people(name: str, hdr: Dict[str, str]) -> List[Dict[str, str]]:
    """
    Searches for people in the library by name.

    Returns a list of dictionaries, each containing the person's
    Id, Name, and primary role (e.g., Actor, Director).
    """
    params = {
        "searchTerm": name,
        "Fields": "PrimaryImageTag",
        "Limit": 20  # Limit to a reasonable number for autocomplete
    }
    r = client.SESSION.get(f"{client.EMBY_URL}/Persons", params=params, headers=hdr, timeout=10)
    r.raise_for_status()
    items = r.json().get("Items", [])

    # Format the response for the frontend
    formatted_people = [
        {
            "Id": p.get("Id"),
            "Name": p.get("Name"),
            # The 'PrimaryImageTag' often contains the role, like 'Actor' or 'Director'
            "Role": p.get("PrimaryImageTag")
        }
        for p in items
    ]
    return formatted_people