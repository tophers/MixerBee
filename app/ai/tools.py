import difflib
from typing import List, Dict
from app.cache import get_library_data
from .vector_store import search_by_vibe # <-- Import the new tool

def get_valid_movie_genres() -> List[str]:
    """Returns a list of all valid movie genres available in the user's library."""
    data = get_library_data()
    return [g['Name'] for g in data.get("movieGenreData", [])]

def get_valid_music_genres() -> List[str]:
    """Returns a list of all valid music genres available in the user's library."""
    data = get_library_data()
    return [g['Name'] for g in data.get("musicGenreData", [])]

def verify_tv_show(query: str) -> List[str]:
    """
    Searches for a TV show by name. 
    Use this to verify the exact spelling of a show before adding it to a playlist.
    """
    data = get_library_data()
    shows = [s['name'] for s in data.get("seriesData", [])]
    return difflib.get_close_matches(query, shows, n=3, cutoff=0.4)

def verify_artist(query: str) -> List[Dict[str, str]]:
    """
    Searches for a music artist by name. 
    Returns a list of dictionaries containing the exact 'Name' and internal 'Id'.
    Always use this tool to get the exact 'Id' when an artist is requested.
    """
    data = get_library_data()
    artists = data.get("artistData", [])
    names = [a['Name'] for a in artists]
    matches = difflib.get_close_matches(query, names, n=3, cutoff=0.4)
    return [{"Name": a["Name"], "Id": a["Id"]} for a in artists if a["Name"] in matches]

# Add search_by_vibe to the list!
AVAILABLE_TOOLS = [
    get_valid_movie_genres, 
    get_valid_music_genres, 
    verify_tv_show, 
    verify_artist,
    search_by_vibe 
]
