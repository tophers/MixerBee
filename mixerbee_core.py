#!/usr/bin/env python3
"""
mixerbee_core – logic for creating / deleting interleaved Emby playlists.
"""

from __future__ import annotations

import argparse
import os
import re
import sys
from itertools import islice
from pathlib import Path
from typing import List, Dict, Tuple
import json
import random
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
import logging
from dotenv import load_dotenv
from datetime import datetime, timedelta
from pydantic import BaseModel, Field
from typing import Optional

logging.basicConfig(level=logging.INFO,
                    format='%(asctime)s - %(levelname)s - %(message)s')

# ---------------------------------------------------------------------------
# config / .env handling
# ---------------------------------------------------------------------------

_early = argparse.ArgumentParser(add_help=False)
_early.add_argument("--config", "--env", metavar="FILE")
_cfg_arg, _ = _early.parse_known_args()

SCRIPT_PATH = Path(__file__).resolve()
SCRIPT_STEM = SCRIPT_PATH.stem

if _cfg_arg.config:
    ENV_PATH = Path(_cfg_arg.config).expanduser()
elif os.getenv("MIXERBEE_ENV"):
    ENV_PATH = Path(os.environ["MIXERBEE_ENV"]).expanduser()
else:
    ENV_PATH = SCRIPT_PATH.with_name(".mixerbee.env")
    if not ENV_PATH.exists():
        xdg = Path(os.getenv("XDG_CONFIG_HOME", "~/.config")).expanduser()
        ENV_PATH = xdg / "mixerbee" / ".env"

if not load_dotenv(ENV_PATH):
    sys.stderr.write(f"[mixerbee] warning: no .env file found at {ENV_PATH}\n")

try:
    EMBY_URL = os.environ["EMBY_URL"].rstrip("/")
    EMBY_USER = os.environ["EMBY_USER"]
    EMBY_PASS = os.environ["EMBY_PASS"]
except KeyError as m:
    raise RuntimeError(f"Missing {m} in environment settings") from None

CLIENT_NAME = os.getenv("CLIENT_NAME", "MixerBee")
DEVICE_ID = os.getenv("DEVICE_ID", "MixerBee_CLI")

class MixArgs(BaseModel):
    shows: List[str] = []
    count: int = 5
    playlist: str = "MixerBee Playlist"
    delete: bool = False
    verbose: bool = False
    target_uid: Optional[str] = None

# ---------------------------------------------------------------------------
# requests session with retries
# ---------------------------------------------------------------------------

SESSION = requests.Session()
_retry = Retry(total=3, backoff_factor=0.3, status_forcelist=(502, 503, 504))
_adapter = HTTPAdapter(max_retries=_retry)
SESSION.mount("http://", _adapter)
SESSION.mount("https://", _adapter)

# ---------------------------------------------------------------------------
# helpers talking to Emby
# ---------------------------------------------------------------------------

def authenticate(username: str, password: str) -> Tuple[str, str]:
    hdr = {"X-Emby-Authorization":
           f'MediaBrowser Client="{CLIENT_NAME}",Device="script",'
           f'DeviceId="{DEVICE_ID}",Version="1.0"'}
    r = SESSION.post(f"{EMBY_URL}/Users/AuthenticateByName",
                     data={"Username": username, "Pw": password},
                     headers=hdr, timeout=10)
    r.raise_for_status()
    j = r.json()
    return j["User"]["Id"], j["AccessToken"]


def auth_headers(token: str, user_id: str) -> Dict[str, str]:
    return {
        "X-Emby-Token": token,
        "X-Emby-User-Id": user_id,
        "X-Emby-Authorization":
            f'MediaBrowser Client="{CLIENT_NAME}",Device="script",'
            f'DeviceId="{DEVICE_ID}",Version="1.0",UserId="{user_id}",'
            f'Token="{token}"'
    }

# ---------------------------------------------------------------------------
# TV helpers
# ---------------------------------------------------------------------------

def parse_show(arg: str) -> Tuple[str, int, int]:
    m = re.match(r"^(.*?)::S(\d+)E(\d+)$", arg, re.IGNORECASE)
    if not m:
        raise ValueError(f"Invalid format: '{arg}', expected 'Show::S3E1'")
    return m.group(1).strip(), int(m.group(2)), int(m.group(3))


def series_id(name: str, hdr: Dict[str, str]) -> str | None:
    r = SESSION.get(f"{EMBY_URL}/Items",
                    params={"IncludeItemTypes": "Series",
                            "SearchTerm": name, "Recursive": "true"},
                    headers=hdr, timeout=10)
    for it in r.json().get("Items", []):
        if it["Name"].lower() == name.lower():
            return it["Id"]
    return None


def episodes(sid: str, season: int, episode: int, count: int,
             hdr: Dict[str, str]):
    r = SESSION.get(f"{EMBY_URL}/Shows/{sid}/Episodes",
                    headers=hdr, timeout=10)
    all_eps = sorted(r.json()["Items"],
                     key=lambda x: (x.get("ParentIndexNumber", 0),
                                    x.get("IndexNumber", 0)))
    eligible = [ep for ep in all_eps
                if ep.get("ParentIndexNumber", 0) > season
                or (ep.get("ParentIndexNumber", 0) == season
                    and ep.get("IndexNumber", 0) >= episode)]
    return list(islice(eligible, count))


def interleave(groups: List[List[dict]]) -> List[str]:
    out = []
    for bundle in zip(*groups):
        out.extend(ep["Id"] for ep in bundle)
    return out


def get_specific_episode(series_id: str, season: int,
                         episode: int, hdr: Dict[str, str]) -> Dict | None:
    r = SESSION.get(f"{EMBY_URL}/Shows/{series_id}/Episodes",
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
                                hdr: Dict[str, str]) -> Dict | None:
    params = {
        "userId": user_id,
        "Fields": "UserData,ParentIndexNumber,IndexNumber"
    }
    r = SESSION.get(f"{EMBY_URL}/Shows/{series_id}/Episodes",
                    params=params, headers=hdr, timeout=15)
    r.raise_for_status()
    all_eps = sorted(r.json().get("Items", []),
                     key=lambda x: (x.get("ParentIndexNumber", 0),
                                    x.get("IndexNumber", 0)))
    regular_eps = [ep for ep in all_eps if ep.get("ParentIndexNumber", 0) > 0]
    for ep in regular_eps:
        user_data = ep.get("UserData", {})
        if not user_data.get("Played"):
            return {
                "id": ep.get("Id"),
                "season": ep.get("ParentIndexNumber", 1),
                "episode": ep.get("IndexNumber", 1)
            }
    if regular_eps:
        first_ep = regular_eps[0]
        return {
            "id": first_ep.get("Id"),
            "season": first_ep.get("ParentIndexNumber", 1),
            "episode": first_ep.get("IndexNumber", 1)
        }
    return None

def get_random_unwatched_episode(series_id: str, user_id: str,
                                 hdr: Dict[str, str]) -> Dict | None:
    params = {
        "userId": user_id,
        "Fields": "UserData,ParentIndexNumber,IndexNumber"
    }
    r = SESSION.get(f"{EMBY_URL}/Shows/{series_id}/Episodes",
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

# ---------------------------------------------------------------------------
# playlists
# ---------------------------------------------------------------------------

def get_playlists(user_id: str, hdr: Dict[str, str]) -> List[Dict]:
    params = {
        "IncludeItemTypes": "Playlist",
        "Recursive": "true",
        "Fields": "Id,Name"
    }
    r = SESSION.get(f"{EMBY_URL}/Users/{user_id}/Items",
                    params=params, headers=hdr, timeout=10)
    r.raise_for_status()
    return r.json().get("Items", [])


def delete_playlist(name: str, user_id: str, hdr: Dict[str, str],
                    log: List[str]):
    targets = [pl for pl in get_playlists(user_id, hdr)
               if pl["Name"].strip().lower() == name.strip().lower()]
    if not targets:
        log.append(f"No playlist named '{name}' found.")
        return
    for pl in targets:
        resp = SESSION.delete(f"{EMBY_URL}/Items/{pl['Id']}",
                              headers=hdr, timeout=10)
        if resp.status_code in (200, 204):
            log.append(f"Deleted playlist '{name}'.")
        else:
            log.append(f"Failed deleting '{name}': HTTP {resp.status_code}")
            log.append(resp.text)


def create_playlist(name: str, user_id: str, ids: List[str],
                    hdr: Dict[str, str], log: List[str]):
    delete_playlist(name, user_id, hdr, log)
    resp = SESSION.post(f"{EMBY_URL}/Playlists",
                        headers=hdr,
                        params={"Name": name, "UserId": user_id,
                                "Ids": ",".join(ids)},
                        timeout=10)
    if resp.ok:
        log.append(f"Playlist '{name}' created successfully.")
    else:
        log.append(f"Failed to create playlist (HTTP {resp.status_code}):")
        log.append(resp.text)

def create_pilot_sampler_playlist(user_id: str, playlist_name: str, count: int, hdr: Dict[str, str], log: List[str]):
    try:
        all_series_resp = SESSION.get(
            f"{EMBY_URL}/Users/{user_id}/Items",
            params={"IncludeItemTypes": "Series", "Recursive": "true", "Fields": "Id,Name"},
            headers=hdr,
            timeout=20
        )
        all_series_resp.raise_for_status()
        all_series = all_series_resp.json().get("Items", [])

        unwatched_pilots = []
        for series in all_series:
            series_id = series["Id"]
            series_stats_resp = SESSION.get(
                f"{EMBY_URL}/Shows/{series_id}/Episodes",
                params={"UserId": user_id, "IsPlayed": "false", "Limit": 1},
                headers=hdr, timeout=10
            )
            series_stats_resp.raise_for_status()
            unplayed_count = series_stats_resp.json().get("TotalRecordCount", 0)

            series_total_resp = SESSION.get(
                f"{EMBY_URL}/Shows/{series_id}/Episodes",
                params={"UserId": user_id, "Limit": 1},
                headers=hdr, timeout=10
            )
            series_total_resp.raise_for_status()
            total_count = series_total_resp.json().get("TotalRecordCount", 0)

            if unplayed_count == total_count and total_count > 0:
                pilot_ep = get_specific_episode(series_id, 1, 1, hdr)
                if pilot_ep:
                    unwatched_pilots.append(pilot_ep)

        if not unwatched_pilots:
            log.append("No shows with unwatched pilot episodes found.")
            return {"status": "ok", "log": log}

        num_to_sample = min(count, len(unwatched_pilots))
        log.append(f"Found {len(unwatched_pilots)} unstarted shows. Randomly selecting {num_to_sample}.")

        selected_pilots = random.sample(unwatched_pilots, num_to_sample)
        pilot_ids = [ep["Id"] for ep in selected_pilots]
        create_playlist(name=playlist_name, user_id=user_id, ids=pilot_ids, hdr=hdr, log=log)
        return {"status": "ok", "log": log}

    except requests.RequestException as e:
        log.append(f"An error occurred: {e}")
        return {"status": "error", "log": log}

def create_continue_watching_playlist(user_id: str, playlist_name: str, count: int, hdr: Dict[str, str], log: List[str]):
    try:
        resume_params = {
            "Recursive": "true",
            "Fields": "SeriesId",
            "IncludeItemTypes": "Episode",
            "SortBy": "DatePlayed",
            "SortOrder": "Descending"
        }
        r = SESSION.get(f"{EMBY_URL}/Users/{user_id}/Items/Resume", params=resume_params, headers=hdr, timeout=15)
        r.raise_for_status()
        resume_items = r.json().get("Items", [])

        if not resume_items:
            log.append("Could not find any in-progress shows.")
            return {"status": "ok", "log": log}

        in_progress_series_ids = []
        seen_ids = set()
        for item in resume_items:
            series_id = item.get("SeriesId")
            if series_id and series_id not in seen_ids:
                seen_ids.add(series_id)
                in_progress_series_ids.append(series_id)

        series_to_process = in_progress_series_ids[:count]
        log.append(f"Found {len(series_to_process)} in-progress shows to process.")

        next_episode_ids = []
        for series_id in series_to_process:
            next_ep = get_first_unwatched_episode(series_id, user_id, hdr)
            if next_ep and next_ep.get("id"):
                next_episode_ids.append(next_ep["id"])

        if not next_episode_ids:
            log.append("Found in-progress shows, but could not find any playable next episodes.")
            return {"status": "ok", "log": log}

        create_playlist(name=playlist_name, user_id=user_id, ids=next_episode_ids, hdr=hdr, log=log)
        return {"status": "ok", "log": log}

    except requests.RequestException as e:
        log.append(f"An error occurred: {e}")
        return {"status": "error", "log": log}

def create_forgotten_favorites_playlist(user_id: str, playlist_name: str, count: int, hdr: Dict[str, str], log: List[str]):
    """Creates a playlist of favorited movies the user has not watched in a year."""
    try:
        params = {
            "IncludeItemTypes": "Movie",
            "Recursive": "true",
            "Filters": "IsFavorite",
            "Fields": "UserData,DateCreated",
            "UserId": user_id
        }
        r = SESSION.get(f"{EMBY_URL}/Users/{user_id}/Items", params=params, headers=hdr, timeout=20)
        r.raise_for_status()
        favorited_movies = r.json().get("Items", [])

        if not favorited_movies:
            log.append("No favorited movies found for this user.")
            return {"status": "ok", "log": log}

        one_year_ago = datetime.now() - timedelta(days=365)
        forgotten_movies = []
        for movie in favorited_movies:
            last_played_str = movie.get("UserData", {}).get("LastPlayedDate")
            if last_played_str:
                try:
                    last_played_date = datetime.fromisoformat(last_played_str.replace('Z', '+00:00'))
                    if last_played_date.replace(tzinfo=None) < one_year_ago:
                        forgotten_movies.append(movie)
                except ValueError:
                    log.append(f"Warning: Could not parse date '{last_played_str}' for movie '{movie.get('Name')}'.")
                    continue
            else:
                forgotten_movies.append(movie)

        if not forgotten_movies:
            log.append("Found favorite movies, but all have been watched recently.")
            return {"status": "ok", "log": log}

        random.shuffle(forgotten_movies)
        num_to_select = min(count, len(forgotten_movies))
        selected_movies = forgotten_movies[:num_to_select]
        movie_ids = [m["Id"] for m in selected_movies]

        log.append(f"Found {len(forgotten_movies)} forgotten favorites. Creating a playlist with {len(selected_movies)} of them.")
        create_playlist(name=playlist_name, user_id=user_id, ids=movie_ids, hdr=hdr, log=log)
        return {"status": "ok", "log": log}

    except requests.RequestException as e:
        log.append(f"An API error occurred: {e}")
        return {"status": "error", "log": log}
    except Exception as e:
        log.append(f"An unexpected error occurred: {e}")
        return {"status": "error", "log": log}

# ---------------------------------------------------------------------------
# users
# ---------------------------------------------------------------------------

def all_users(hdr: Dict[str, str]) -> List[dict]:
    r = SESSION.get(f"{EMBY_URL}/Users", headers=hdr, timeout=10)
    r.raise_for_status()
    return r.json()


def user_id_by_name(name: str, hdr: Dict[str, str]) -> str | None:
    for u in all_users(hdr):
        if u.get("Name", "").lower() == name.lower():
            return u["Id"]
    return None


def search_series(name: str, hdr: Dict[str, str]) -> List[Dict[str, str]]:
    r = SESSION.get(f"{EMBY_URL}/Items",
                    params={"IncludeItemTypes": "Series",
                            "SearchTerm": name,
                            "Recursive": "true"},
                    headers=hdr, timeout=10)
    r.raise_for_status()
    items = r.json().get("Items", [])
    return [{"Id": it["Id"], "Name": it["Name"]} for it in items]

# ---------------------------------------------------------------------------
# movies
# ---------------------------------------------------------------------------

def get_movie_genres(hdr: Dict[str, str]) -> List[Dict[str, str]]:
    params = {"IncludeItemTypes": "Movie"}
    r = SESSION.get(f"{EMBY_URL}/Genres",
                    params=params, headers=hdr, timeout=10)
    r.raise_for_status()
    return r.json().get("Items", [])


def find_movies(user_id: str, filters: Dict,
                hdr: Dict[str, str]) -> List[Dict[str, str]]:
    base_params = {
        "IncludeItemTypes": "Movie",
        "Recursive": "true",
        "Fields": "Genres,PremiereDate,UserData,RunTimeTicks"
    }
    base_params["UserId"] = user_id

    if filters.get("watched_status") == "played":
        base_params["IsPlayed"] = "true"
    elif filters.get("watched_status") == "unplayed":
        base_params["IsPlayed"] = "false"

    if filters.get("year_from"):
        base_params["MinPremiereDate"] = f"{filters['year_from']}-01-01"
    if filters.get("year_to"):
        base_params["MaxPremiereDate"] = f"{filters['year_to']}-12-31"

    genres_to_search = filters.get("genres")
    genre_match_type = filters.get("genre_match", "any")

    potential_movies = []

    if genres_to_search and genre_match_type == "any":
        all_movies_dict = {}
        for genre in genres_to_search:
            search_params = base_params.copy()
            search_params["Genres"] = genre
            r = SESSION.get(f"{EMBY_URL}/Users/{user_id}/Items", params=search_params, headers=hdr, timeout=15)
            r.raise_for_status()
            for movie in r.json().get("Items", []):
                all_movies_dict[movie["Id"]] = movie
        potential_movies = list(all_movies_dict.values())
    else:
        search_params = base_params.copy()
        r = SESSION.get(f"{EMBY_URL}/Users/{user_id}/Items", params=search_params, headers=hdr, timeout=15)
        r.raise_for_status()
        potential_movies = r.json().get("Items", [])

    if genres_to_search and genre_match_type == "all":
        required_genres = set(g.lower() for g in genres_to_search)
        final_list = []
        for movie in potential_movies:
            movie_genres = set(g.lower() for g in movie.get("Genres", []))
            if required_genres.issubset(movie_genres):
                final_list.append(movie)
    else:
        final_list = potential_movies


    sort_by = filters.get("sort_by", "Random")
    if sort_by == "Random":
        random.shuffle(final_list)
    else:
        reverse = sort_by in ("PremiereDate", "DateCreated")
        final_list.sort(key=lambda m: m.get(sort_by, ""), reverse=reverse)

    target_duration_minutes = filters.get("duration_minutes")
    if target_duration_minutes:
        target_duration_ticks = int(target_duration_minutes) * 60 * 10000000
        playlist_movies = []
        current_duration_ticks = 0
        for movie in final_list:
            runtime_ticks = movie.get("RunTimeTicks")
            if runtime_ticks:
                if current_duration_ticks + runtime_ticks <= target_duration_ticks:
                    playlist_movies.append(movie)
                    current_duration_ticks += runtime_ticks
        return playlist_movies

    limit = filters.get("limit")
    if limit is not None:
        return final_list[:int(limit)]

    return final_list

# ---------------------------------------------------------------------------
# mixed playlist builder
# ---------------------------------------------------------------------------

def create_mixed_playlist(user_id: str, playlist_name: str,
                          blocks: List[Dict], hdr: Dict[str, str]) -> Dict:
    master_item_ids: List[str] = []
    log_messages: List[str] = []

    for i, block in enumerate(blocks, 1):
        block_type = block.get("type")

        if block_type == "tv":
            try:
                should_interleave = block.get("interleave", True)
                groups: List[List[dict]] = []

                for raw_show in block.get("shows", []):
                    s, e = None, None
                    show_name = None

                    if isinstance(raw_show, dict):
                        show_name = raw_show.get("name")
                        if raw_show.get("unwatched"):
                            sid_lookup = series_id(show_name, hdr)
                            if sid_lookup:
                                ep_info = get_first_unwatched_episode(sid_lookup, user_id, hdr)
                                if ep_info:
                                    s = ep_info.get("season")
                                    e = ep_info.get("episode")
                        else:
                            s = int(raw_show.get("season", 1))
                            e = int(raw_show.get("episode", 1))
                    
                    elif isinstance(raw_show, str):
                        show_name, s, e = parse_show(raw_show)

                    if not all([show_name, s is not None, e is not None]):
                        log_messages.append(f"Block {i}: Could not process show entry: {raw_show}")
                        continue
                    
                    sid = series_id(show_name, hdr)
                    if not sid:
                        log_messages.append(f"Block {i}: Show not found - {show_name}")
                        continue
                    count = int(block.get("count", 1))
                    eps = episodes(sid, s, e, count, hdr)
                    if len(eps) < count:
                        log_messages.append(f"Block {i}: Only found "
                                            f"{len(eps)}/{count} eps for '{show_name}'")
                    groups.append(eps)

                if groups:
                    if should_interleave:
                        min_len = min(len(g) for g in groups) if groups else 0
                        trimmed = [list(islice(g, min_len)) for g in groups]
                        interleaved_ids = interleave(trimmed)
                        master_item_ids.extend(interleaved_ids)
                        log_messages.append(f"Block {i} (TV): Added "
                                            f"{len(interleaved_ids)} interleaved episodes.")
                    else:
                        total_added = 0
                        for episode_group in groups:
                            gids = [ep["Id"] for ep in episode_group]
                            master_item_ids.extend(gids)
                            total_added += len(gids)
                        log_messages.append(f"Block {i} (TV): Added "
                                            f"{total_added} sequential episodes.")
            except Exception as e:
                log_messages.append(f"Block {i} (TV): Failed with error - {e}")

        elif block_type == "movie":
            try:
                found_movies = find_movies(user_id=user_id,
                                           filters=block.get("filters", {}),
                                           hdr=hdr)
                movie_ids = [m["Id"] for m in found_movies]
                master_item_ids.extend(movie_ids)
                log_messages.append(f"Block {i} (Movie): Added {len(movie_ids)} movies.")
            except Exception as e:
                log_messages.append(f"Block {i} (Movie): Failed with error - {e}")

    if not master_item_ids:
        log_messages.append("No items were found to add. Playlist not created.")
        return {"status": "error", "log": log_messages}

    create_playlist(name=playlist_name, user_id=user_id,
                    ids=master_item_ids, hdr=hdr, log=log_messages)
    return {"status": "ok", "log": log_messages}

# ---------------------------------------------------------------------------
# simple mix (TV only) – legacy route
# ---------------------------------------------------------------------------

def mix(*,
        shows: List[str],
        count: int,
        playlist: str,
        target_uid: str | None = None,
        delete: bool = False,
        verbose: bool = False) -> Dict[str, object]:
    log: List[str] = []
    try:
        login_uid, token = authenticate(EMBY_USER, EMBY_PASS)
    except requests.HTTPError as err:
        return {"status": "error",
                "log": [f"Login failed: {err.response.text}"]}

    hdr = auth_headers(token, login_uid)
    tgt = target_uid or login_uid

    if verbose:
        log.append(f"Authenticated as {EMBY_USER} → uid={login_uid}")
        if target_uid:
            log.append(f"Acting on behalf of user id {tgt}")

    if delete:
        delete_playlist(playlist, tgt, hdr, log)
        return {"status": "ok", "log": log,
                "details": {"deleted": playlist, "user_id": tgt}}

    if not shows:
        return {"status": "error",
                "log": ["No shows specified; nothing to do."]}

    groups: List[List[dict]] = []
    for raw in shows:
        try:
            name, s, e = parse_show(raw)
        except ValueError as err:
            return {"status": "error", "log": [str(err)]}
        sid = series_id(name, hdr)
        if not sid:
            return {"status": "error",
                    "log": [f"Show not found: {name}"]}

        eps = episodes(sid, s, e, count, hdr)
        if len(eps) < count:
            log.append(f"Warning: only {len(eps)} eps found for "
                       f"'{name}' starting S{s}E{e}")
        groups.append(eps)

    min_len = min(len(g) for g in groups) if groups else 0
    groups = [list(islice(g, min_len)) for g in groups]
    total = min_len * len(groups)

    if verbose:
        log.append(f"Creating playlist with {total} episodes…")

    create_playlist(playlist, tgt, interleave(groups), hdr, log)
    return {"status": "ok", "log": log,
            "details": {"episodes": total,
                        "playlist": playlist,
                        "user_id": tgt}}


# ---------------------------------------------------------------------------
# graceful shutdown
# ---------------------------------------------------------------------------

import atexit
atexit.register(SESSION.close)

