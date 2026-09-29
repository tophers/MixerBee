"""
app/ai/tools.py - Tools for AI playlist generation
"""

import difflib
import re
from typing import List, Dict
from app.cache import get_library_data
from app.logger import get_logger
from .vector_store import search_by_vibe

logger = get_logger("MixerBee.AI.Tools")

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

AVAILABLE_TOOLS = [
    get_valid_movie_genres, 
    get_valid_music_genres, 
    verify_tv_show, 
    verify_artist,
    search_by_vibe 
]


def tools_for_connection():
    """Capture context for SDKs that invoke tool callbacks on another thread."""
    return bind_tools(AVAILABLE_TOOLS)


# --- Playlist Assist tools -------------------------------------------------
#
# Phase 1 of Playlist Assist is movies-only. These tools hit the media server
# live rather than reading app/cache.py, because the library cache holds genre
# and series rollups, not a full movie catalogue.

# Hard bounds on what one tool invocation may ask for. The LLM picks these
# numbers, so they are clamped server-side rather than trusted.
MAX_ASSIST_TITLES = 20
MAX_ASSIST_VIBE_COUNT = 30
MAX_ASSIST_METADATA_IDS = 60
# Candidates pulled before a release-year window is applied. The window can reject
# most of a vibe pool, so filtering the default-sized pool would starve the result.
VIBE_YEAR_FILTER_POOL = 80


def _assist_movie_payload(item: Dict, media) -> Dict:
    """One movie in the shape both the LLM and the frontend canvas consume."""
    item_id = item.get("Id", "")
    return {
        "Id": item_id,
        "Name": item.get("Name", "Unknown"),
        "Type": "Movie",
        "Year": item.get("ProductionYear", "") or "",
        "Genres": ", ".join(item.get("Genres", []) or []),
        "RunTimeTicks": item.get("RunTimeTicks") or 0,
        "PosterUrl": media.image_url(item_id, tag=(item.get("ImageTags") or {}).get("Primary", "")),
    }


# The model often writes a title as "Tank Girl (1995)". The parenthesised year is a
# useful disambiguator but ruins the server-side SearchTerm, so it is split off.
_TITLE_YEAR_RE = re.compile(r"^(?P<title>.*?)\s*\((?P<year>(?:19|20)\d{2})\)\s*$")

# Max accepted matches for one requested title. The server's SearchTerm is a loose
# substring match, so the cap is on top of the relevance rules in _match_rank.
MAX_MATCHES_PER_TITLE = 3


def _normalize_title(value: str) -> str:
    return re.sub(r"[^a-z0-9 ]+", "", str(value or "").lower()).strip()


def _match_rank(query: str, candidate: str):
    """How well a library title answers a requested one; None means 'not a match'.

    Emby's SearchTerm is a bare substring match, so asking for "Tank Girl" also
    returns "Stolen Girl" and "Working Girl". A plain similarity ratio cannot separate
    those from a legitimate sequel -- "Tank Girl"/"Stolen Girl" scores 0.70 while
    "The Matrix"/"The Matrix Reloaded" scores 0.69. Prefix and whole-token containment
    do separate them, so that is what is used.
    """
    q, c = _normalize_title(query), _normalize_title(candidate)
    if not q or not c:
        return None
    if q == c:
        return 0
    if c.startswith(q) or q.startswith(c):
        return 1
    # Every word of the request must actually appear in the candidate: this keeps
    # "Alien" -> "Aliens" style hits while dropping incidental substring collisions.
    c_tokens = set(c.split())
    if all(tok in c_tokens for tok in q.split()):
        return 2
    return None


def _assist_search_movies(term: str, media, limit: int = 3) -> List[Dict]:
    """Resolve one requested title to its closest library matches."""
    match = _TITLE_YEAR_RE.match(term)
    search_term = (match.group("title") if match else term).strip() or term
    wanted_year = int(match.group("year")) if match else None

    params = {
        "SearchTerm": search_term,
        "IncludeItemTypes": "Movie",
        "Recursive": "true",
        "Limit": 20,
        "Fields": "ProductionYear,Genres,RunTimeTicks",
    }
    r = media.get(f"/Users/{media.user_id}/Items", params=params, timeout=15)
    r.raise_for_status()

    scored = []
    for item in r.json().get("Items", []):
        rank = _match_rank(search_term, item.get("Name", ""))
        if rank is None:
            continue
        # A year the model supplied only ever breaks ties; it never excludes a match,
        # since the model's recollection of a release year is not authoritative.
        year_miss = 0 if (wanted_year is None or item.get("ProductionYear") == wanted_year) else 1
        scored.append(((rank, year_miss, len(item.get("Name", ""))), item))

    scored.sort(key=lambda pair: pair[0])
    return [_assist_movie_payload(it, media) for _, it in scored[:limit]]


def batch_find_movies(titles: List[str]) -> List[Dict]:
    """
    Looks up specific movie titles in the user's library and returns the matches.
    Use this when you already know which films you want (by name) and need their
    library IDs. Pass every title you need in one call.
    """
    from app.media_client import current_media
    media = current_media()

    if isinstance(titles, str):
        titles = [titles]
    cleaned = [str(t).strip() for t in (titles or []) if str(t).strip()][:MAX_ASSIST_TITLES]

    results: List[Dict] = []
    seen = set()
    for title in cleaned:
        try:
            matches = _assist_search_movies(title, media, limit=MAX_MATCHES_PER_TITLE)
        except Exception as e:
            logger.warning("batch_find_movies failed for '%s': %s", title, e)
            continue
        if not matches:
            logger.info("batch_find_movies: no close match for '%s'.", title)
        for match in matches:
            if match["Id"] and match["Id"] not in seen:
                seen.add(match["Id"])
                results.append(match)
    return results


def _coerce_year(value) -> int:
    try:
        year = int(value)
    except (TypeError, ValueError):
        return 0
    return year if 1870 <= year <= 2200 else 0


def semantic_movie_vibe_search(prompt: str, count: int = 10, year_from: int = 0, year_to: int = 0) -> List[Dict]:
    """
    Finds movies in the user's library by vibe, theme or mood rather than by title.
    Use this for open-ended requests like "something bleak and rainy". Set year_from
    and year_to when the user asked for a period (e.g. 1990 and 1999 for "90s"); the
    release-year window is applied exactly. Returns matches with their library IDs.
    """
    from app.media_client import current_media
    media = current_media()

    query = str(prompt or "").strip()
    if not query:
        return []
    try:
        requested = int(count)
    except (TypeError, ValueError):
        requested = 10
    requested = max(1, min(MAX_ASSIST_VIBE_COUNT, requested))

    lo, hi = _coerce_year(year_from), _coerce_year(year_to)
    if lo and hi and lo > hi:
        lo, hi = hi, lo

    # The vector index has no usable notion of a release period -- a search for
    # "90s sci-fi" happily returns 2025 titles -- so the window is applied here, as
    # a hard filter on the authoritative ProductionYear. Over-fetch so the filter
    # still has material to work with.
    pool_size = VIBE_YEAR_FILTER_POOL if (lo or hi) else requested
    hits = search_by_vibe(query=query, media_type="Movie", limit=pool_size)
    ids = [h.get("Id") for h in hits if h.get("Id")]
    if not ids:
        return []

    # search_by_vibe answers from the vector index, which carries no artwork tag
    # and no runtime. One live lookup turns those hits into canvas-ready items.
    items = resolve_movies(ids)
    if lo or hi:
        items = [it for it in items if in_year_window(it.get("Year"), lo, hi)]
    return items[:requested]


def in_year_window(year, year_from: int, year_to: int) -> bool:
    """True when a release year falls inside an (optionally half-open) window.

    An unknown year is never excluded: the media server simply not having the
    metadata is not evidence that the film falls outside the user's period.
    """
    value = _coerce_year(year)
    if not value:
        return True
    if year_from and value < year_from:
        return False
    if year_to and value > year_to:
        return False
    return True


def resolve_movies(ids: List[str]) -> List[Dict]:
    """Live lookup of movie details for library IDs, preserving the caller's order.

    Uncapped on purpose. MAX_ASSIST_METADATA_IDS bounds what the *model* may ask
    for; MixerBee's own internal resolution (a vibe pool about to be year-filtered,
    or a whole canvas being validated) must not be silently truncated by it.
    """
    from app.media_client import current_media
    media = current_media()

    if isinstance(ids, str):
        ids = [ids]
    wanted, seen = [], set()
    for raw in (ids or []):
        item_id = str(raw).strip()
        if item_id and item_id not in seen:
            seen.add(item_id)
            wanted.append(item_id)
    if not wanted:
        return []

    found: Dict[str, Dict] = {}
    chunk_size = 30
    for i in range(0, len(wanted), chunk_size):
        chunk = wanted[i:i + chunk_size]
        params = {
            "Ids": ",".join(chunk),
            "IncludeItemTypes": "Movie",
            "Recursive": "true",
            "Fields": "ProductionYear,Genres,RunTimeTicks",
        }
        try:
            r = media.get(f"/Users/{media.user_id}/Items", params=params, timeout=15)
            r.raise_for_status()
        except Exception as e:
            logger.warning("get_movie_metadata lookup failed: %s", e)
            continue
        for it in r.json().get("Items", []):
            if it.get("Id"):
                found[it["Id"]] = _assist_movie_payload(it, media)

    # Preserve the caller's ordering; silently drop IDs the server no longer serves.
    return [found[i] for i in wanted if i in found]


def get_movie_metadata(ids: List[str]) -> List[Dict]:
    """
    Returns full details (title, year, genres, runtime) for movies already
    identified by library ID. Use this to check facts before deciding what to keep.
    """
    if isinstance(ids, str):
        ids = [ids]
    return resolve_movies(list(ids or [])[:MAX_ASSIST_METADATA_IDS])


ASSIST_TOOLS = [batch_find_movies, semantic_movie_vibe_search, get_movie_metadata]
# Omitted when the connection has no vibe index built (see assist_orchestrator).
ASSIST_VIBE_TOOL = semantic_movie_vibe_search


def bind_tools(tools):
    """Capture context for SDKs that invoke tool callbacks on another thread."""
    from contextvars import copy_context
    from functools import wraps
    context = copy_context()

    def bind(tool):
        @wraps(tool)
        def call(*args, **kwargs):
            return context.copy().run(tool, *args, **kwargs)
        return call

    return [bind(tool) for tool in tools]
