"""
app/items.py - Generic playlist, collection, and item management.
"""

import logging
from datetime import datetime, timedelta
from typing import Dict, List
import random
import time

import requests

from . import client
from .movies import find_movies
from .music import get_songs_by_artist, get_songs_by_album, find_songs
from .tv import get_first_unwatched_episode, get_specific_episode

# Generic Item Functions
def delete_item_by_id(item_id: str, hdr: Dict[str, str]) -> bool:
    """Deletes a single Emby item by its ID. Returns True on success."""
    if not item_id:
        return False
    try:
        resp = client.SESSION.delete(f"{client.EMBY_URL}/Items/{item_id}", headers=hdr, timeout=10)
        resp.raise_for_status()
        return True
    except requests.RequestException:
        logging.error(f"Failed to delete item with ID {item_id}", exc_info=True)
        return False

def get_item_children(user_id: str, item_id: str, hdr: Dict[str, str]) -> List[Dict]:
    """Fetches the child items of a given playlist or collection."""
    params = {
        "UserId": user_id,
        "ParentId": item_id,
        "Fields": "RunTimeTicks,ParentId,IndexNumber,ParentIndexNumber", # Add fields for more context
    }
    r = client.SESSION.get(f"{client.EMBY_URL}/Users/{user_id}/Items", params=params, headers=hdr, timeout=15)
    r.raise_for_status()
    return r.json().get("Items", [])


def get_manageable_items(user_id: str, hdr: Dict[str, str]) -> List[Dict]:
    """Fetches and combines playlists and collections for the Manager tab."""
    if not user_id: return []
    params = {
        "Recursive": "true",
        "IncludeItemTypes": "Playlist,BoxSet",
        "Fields": "ChildCount,DateCreated",
    }
    r = client.SESSION.get(f"{client.EMBY_URL}/Users/{user_id}/Items", params=params, headers=hdr, timeout=15)
    r.raise_for_status()

    items = r.json().get("Items", [])

    for item in items:
        item["ItemCount"] = item.get("ChildCount", 0)
        item["DisplayType"] = "Collection" if item.get("Type") == "BoxSet" else "Playlist"

    return items

# Playlist Functions
def get_playlists(user_id: str, hdr: Dict[str, str]) -> List[Dict]:
    """Gets a list of all playlists for a user."""
    params = {
        "IncludeItemTypes": "Playlist",
        "Recursive": "true",
        "Fields": "Id,Name",
        "_": int(time.time() * 1000) # Cache-busting parameter
    }
    r = client.SESSION.get(f"{client.EMBY_URL}/Users/{user_id}/Items",
                           params=params, headers=hdr, timeout=10)
    r.raise_for_status()
    return r.json().get("Items", [])


def remove_item_from_playlist(playlist_id: str, item_id_to_remove: str, hdr: Dict[str, str]) -> bool:
    """Removes a single item from a playlist without deleting the item itself."""
    user_id = hdr.get("X-Emby-User-Id")
    # First, get all items to find the PlaylistItemId, which is what Emby uses as the EntryId
    params = {"UserId": user_id, "Fields": "Id"}
    try:
        r = client.SESSION.get(f"{client.EMBY_URL}/Playlists/{playlist_id}/Items", params=params, headers=hdr, timeout=10)
        r.raise_for_status()
        items = r.json().get("Items", [])

        playlist_item_id = None
        for item in items:
            if item.get("Id") == item_id_to_remove:
                playlist_item_id = item.get("PlaylistItemId")
                break

        if not playlist_item_id:
            logging.warning(f"Could not find item {item_id_to_remove} in playlist {playlist_id} to get its PlaylistItemId.")
            return False  # Item wasn't in the playlist

        # Now, delete using the PlaylistItemId (called EntryIds by the API)
        delete_params = {"EntryIds": playlist_item_id}
        del_resp = client.SESSION.delete(f"{client.EMBY_URL}/Playlists/{playlist_id}/Items", params=delete_params, headers=hdr, timeout=10)
        del_resp.raise_for_status()
        return True

    except requests.RequestException as e:
        logging.error(f"Failed to remove item {item_id_to_remove} from playlist {playlist_id}: {e}", exc_info=True)
        return False


def delete_playlist(name: str, user_id: str, hdr: Dict[str, str],
                    log: List[str]):
    """Deletes a playlist by its name."""
    targets = [pl for pl in get_playlists(user_id, hdr)
               if pl.get("Name") and pl.get("Name").strip().lower() == name.strip().lower()]
    if not targets:
        return
    for pl in targets:
        resp = client.SESSION.delete(f"{client.EMBY_URL}/Items/{pl['Id']}",
                                     headers=hdr, timeout=10)
        if resp.status_code in (200, 204):
            log.append(f"Deleted existing playlist '{name}'.")
        else:
            log.append(f"Failed deleting playlist '{name}': HTTP {resp.status_code}")


def add_items_to_playlist_by_ids(playlist_id: str, item_ids: List[str], user_id: str, hdr: Dict[str, str], log: List[str]) -> bool:
    """Appends a list of item IDs to an existing playlist."""
    if not item_ids:
        log.append("No new items to add.")
        return True

    params = {
        "UserId": user_id,
        "Ids": ",".join(item_ids)
    }
    try:
        resp = client.SESSION.post(f"{client.EMBY_URL}/Playlists/{playlist_id}/Items",
                                 params=params, headers=hdr, timeout=15)
        resp.raise_for_status()
        log.append(f"Successfully added {len(item_ids)} items to the playlist.")
        return True
    except requests.RequestException as e:
        error_msg = f"Failed to add items to playlist {playlist_id}: {e}"
        log.append(error_msg)
        logging.error(error_msg, exc_info=True)
        return False


def create_playlist(name: str, user_id: str, ids: List[str],
                    hdr: Dict[str, str], log: List[str]):
    """Creates a new playlist, deleting any existing one with the same name."""
    delete_playlist(name, user_id, hdr, log)
    resp = client.SESSION.post(f"{client.EMBY_URL}/Playlists",
                               headers=hdr,
                               params={"Name": name, "UserId": user_id,
                                       "Ids": ",".join(ids)},
                               timeout=10)
    if resp.ok:
        log.append(f"Playlist '{name}' created successfully.")
    else:
        log.append(f"Failed to create playlist (HTTP {resp.status_code}):")
        log.append(resp.text)

# "Quick Playlist" / Smart Playlist Functions
def create_recently_added_playlist(user_id: str, playlist_name: str, count: int, hdr: Dict[str, str], log: List[str]):
    """Creates a playlist of the most recently added movies and next-up episodes."""
    try:
        limit = count * 2 
        base_params = {
            "UserId": user_id,
            "SortBy": "DateCreated",
            "SortOrder": "Descending",
            "Recursive": "true",
            "Fields": "DateCreated,Id,SeriesId",
            "Limit": limit
        }

        movie_params = base_params.copy()
        movie_params["IncludeItemTypes"] = "Movie"
        r_movies = client.SESSION.get(f"{client.EMBY_URL}/Users/{user_id}/Items", params=movie_params, headers=hdr, timeout=15)
        r_movies.raise_for_status()
        recent_movies = r_movies.json().get("Items", [])
        log.append(f"Found {len(recent_movies)} recent movies.")

        episode_params = base_params.copy()
        episode_params["IncludeItemTypes"] = "Episode"
        r_episodes = client.SESSION.get(f"{client.EMBY_URL}/Users/{user_id}/Items", params=episode_params, headers=hdr, timeout=15)
        r_episodes.raise_for_status()
        recent_episodes = r_episodes.json().get("Items", [])

        recent_series_info = {}
        for ep in recent_episodes:
            series_id = ep.get("SeriesId")
            if series_id and series_id not in recent_series_info:
                recent_series_info[series_id] = ep.get("DateCreated")
        log.append(f"Found {len(recent_series_info)} unique recent series.")

        next_up_episodes = []
        for series_id, date_created in recent_series_info.items():
            next_ep_data = get_first_unwatched_episode(series_id, user_id, hdr)
            if next_ep_data and next_ep_data.get("Id"):
                next_ep_data["DateCreated"] = date_created
                next_up_episodes.append(next_ep_data)
        
        combined_items = recent_movies + next_up_episodes
        if not combined_items:
            log.append("No recently added items found. Playlist not created.")
            return {"status": "ok", "log": log}
        
        combined_items.sort(key=lambda x: x.get("DateCreated", ""), reverse=True)
        final_items = combined_items[:count]
        
        # This now correctly handles items with 'Id' from movies/episodes
        item_ids = [item["Id"] for item in final_items]

        log.append(f"Creating playlist with the top {len(final_items)} most recently added items (using next-up for shows).")
        create_playlist(name=playlist_name, user_id=user_id, ids=item_ids, hdr=hdr, log=log)
        return {"status": "ok", "log": log}

    except requests.RequestException as e:
        log.append(f"An API error occurred: {e}")
        return {"status": "error", "log": log}
    except Exception as e:
        log.append(f"An unexpected error occurred: {e}")
        logging.error("Error in create_recently_added_playlist", exc_info=True)
        return {"status": "error", "log": log}


def create_pilot_sampler_playlist(user_id: str, playlist_name: str, count: int, hdr: Dict[str, str], log: List[str]):
    """Creates a playlist of unwatched pilot episodes."""
    try:
        all_series_resp = client.SESSION.get(
            f"{client.EMBY_URL}/Users/{user_id}/Items",
            params={"IncludeItemTypes": "Series", "Recursive": "true", "Fields": "Id,Name"},
            headers=hdr,
            timeout=20
        )
        all_series_resp.raise_for_status()
        all_series = all_series_resp.json().get("Items", [])

        unwatched_pilots = []
        for series in all_series:
            series_id = series["Id"]
            series_stats_resp = client.SESSION.get(
                f"{client.EMBY_URL}/Shows/{series_id}/Episodes",
                params={"UserId": user_id, "IsPlayed": "false", "Limit": 1},
                headers=hdr, timeout=10
            )
            series_stats_resp.raise_for_status()
            unplayed_count = series_stats_resp.json().get("TotalRecordCount", 0)

            series_total_resp = client.SESSION.get(
                f"{client.EMBY_URL}/Shows/{series_id}/Episodes",
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
            log.append("No unstarted shows found. Playlist not created.")
            return {"status": "ok", "log": log}

        num_to_sample = min(count, len(unwatched_pilots))
        log.append(f"Found {len(unwatched_pilots)} unstarted shows. Creating playlist with {num_to_sample} random pilots.")

        selected_pilots = random.sample(unwatched_pilots, num_to_sample)
        pilot_ids = [ep["Id"] for ep in selected_pilots]
        create_playlist(name=playlist_name, user_id=user_id, ids=pilot_ids, hdr=hdr, log=log)
        return {"status": "ok", "log": log}

    except requests.RequestException as e:
        log.append(f"An error occurred: {e}")
        return {"status": "error", "log": log}

def create_continue_watching_playlist(user_id: str, playlist_name: str, count: int, hdr: Dict[str, str], log: List[str]):
    """Creates a playlist of the next unwatched episodes from in-progress shows."""
    try:
        resume_params = {
            "Recursive": "true",
            "Fields": "SeriesId",
            "IncludeItemTypes": "Episode",
            "SortBy": "DatePlayed",
            "SortOrder": "Descending"
        }
        r = client.SESSION.get(f"{client.EMBY_URL}/Users/{user_id}/Items/Resume", params=resume_params, headers=hdr, timeout=15)
        r.raise_for_status()
        resume_items = r.json().get("Items", [])

        if not resume_items:
            log.append("Could not find any in-progress shows. Playlist not created.")
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
            if next_ep and next_ep.get("Id"):
                next_episode_ids.append(next_ep["Id"])

        if not next_episode_ids:
            log.append("Found in-progress shows, but could not find any playable next episodes. Playlist not created.")
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
        r = client.SESSION.get(f"{client.EMBY_URL}/Users/{user_id}/Items", params=params, headers=hdr, timeout=20)
        r.raise_for_status()
        favorited_movies = r.json().get("Items", [])

        if not favorited_movies:
            log.append("No favorited movies found for this user. Playlist not created.")
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
            log.append("Found favorite movies, but all have been watched recently. Playlist not created.")
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

def create_movie_marathon_playlist(user_id: str, playlist_name: str, genre: str, count: int, hdr: Dict[str, str], log: List[str]):
    """Creates a playlist of random, unwatched movies from a specific genre."""
    try:
        filters = {
            "genres": [genre] if genre else [],
            "watched_status": "unplayed",
            "sort_by": "Random",
            "limit": count
        }
        found_movies = find_movies(user_id=user_id, filters=filters, hdr=hdr)

        if not found_movies:
            log.append(f"No unwatched movies found for genre '{genre}'. Playlist not created.")
            return {"status": "ok", "log": log}

        movie_ids = [m["Id"] for m in found_movies]
        log.append(f"Found {len(found_movies)} movies for your '{genre}' marathon.")
        create_playlist(name=playlist_name, user_id=user_id, ids=movie_ids, hdr=hdr, log=log)
        return {"status": "ok", "log": log}

    except requests.RequestException as e:
        log.append(f"An API error occurred: {e}")
        return {"status": "error", "log": log}
    except Exception as e:
        log.append(f"An unexpected error occurred: {e}")
        return {"status": "error", "log": log}

def create_artist_spotlight_playlist(user_id: str, playlist_name: str, artist_id: str, count: int, hdr: Dict[str, str], log: List[str]):
    """Creates a playlist of top tracks for a specific artist."""
    try:
        top_songs = get_songs_by_artist(artist_id, hdr, sort="Top", limit=count)

        if not top_songs:
            log.append(f"No songs found for the selected artist. Playlist not created.")
            return {"status": "ok", "log": log}

        song_ids = [song["Id"] for song in top_songs]
        log.append(f"Found {len(top_songs)} top songs for your artist spotlight.")
        create_playlist(name=playlist_name, user_id=user_id, ids=song_ids, hdr=hdr, log=log)
        return {"status": "ok", "log": log}

    except requests.RequestException as e:
        log.append(f"An API error occurred: {e}")
        return {"status": "error", "log": log}
    except Exception as e:
        log.append(f"An unexpected error occurred: {e}")
        return {"status": "error", "log": log}

def create_album_playlist(user_id: str, playlist_name: str, album_id: str, hdr: Dict[str, str], log: List[str]):
    """Creates a playlist from all the songs in a given album."""
    try:
        album_songs = get_songs_by_album(album_id, hdr)

        if not album_songs:
            log.append(f"Could not find any songs for the selected album. Playlist not created.")
            return {"status": "ok", "log": log}

        song_ids = [song["Id"] for song in album_songs]
        log.append(f"Found {len(album_songs)} songs for album playlist.")
        create_playlist(name=playlist_name, user_id=user_id, ids=song_ids, hdr=hdr, log=log)
        return {"status": "ok", "log": log}

    except requests.RequestException as e:
        log.append(f"An API error occurred: {e}")
        return {"status": "error", "log": log}
    except Exception as e:
        log.append(f"An unexpected error occurred: {e}")
        return {"status": "error", "log": log}

def create_music_genre_playlist(user_id: str, playlist_name: str, genre: str, count: int, hdr: Dict[str, str], log: List[str]):
    """Creates a playlist of random songs from a specific music genre."""
    try:
        filters = {
            "genres": [genre],
            "sort_by": "Random",
            "limit": count
        }
        found_songs = find_songs(user_id=user_id, filters=filters, hdr=hdr)

        if not found_songs:
            log.append(f"No songs found for genre '{genre}'. Playlist not created.")
            return {"status": "ok", "log": log}

        song_ids = [s["Id"] for s in found_songs]
        log.append(f"Found {len(found_songs)} songs for your '{genre}' genre sampler.")
        create_playlist(name=playlist_name, user_id=user_id, ids=song_ids, hdr=hdr, log=log)
        return {"status": "ok", "log": log}

    except requests.RequestException as e:
        log.append(f"An API error occurred: {e}")
        return {"status": "error", "log": log}
    except Exception as e:
        log.append(f"An unexpected error occurred: {e}")
        return {"status": "error", "log": log}

# Collection Functions
def get_collections(user_id: str, hdr: Dict[str, str]) -> List[Dict]:
    """Gets a list of all collections (BoxSets) for a user."""
    params = {
        "IncludeItemTypes": "BoxSet",
        "Recursive": "true",
        "Fields": "Id,Name"
    }
    r = client.SESSION.get(f"{client.EMBY_URL}/Users/{user_id}/Items",
                           params=params, headers=hdr, timeout=10)
    r.raise_for_status()
    return r.json().get("Items", [])


def delete_collection(name: str, user_id: str, hdr: Dict[str, str], log: List[str]):
    """Deletes a collection by its name."""
    targets = [c for c in get_collections(user_id, hdr)
               if c["Name"].strip().lower() == name.strip().lower()]
    if not targets:
        return
    for c in targets:
        resp = client.SESSION.delete(f"{client.EMBY_URL}/Items/{c['Id']}", headers=hdr, timeout=10)
        if resp.status_code in (200, 204):
            log.append(f"Deleted existing collection '{name}'.")
        else:
            log.append(f"Failed deleting collection '{name}': HTTP {resp.status_code}")

def create_movie_collection(user_id: str, collection_name: str, filters: Dict, hdr: Dict[str, str]) -> Dict:
    """Creates a movie collection from a set of movie filters."""
    log = []
    try:
        delete_collection(collection_name, user_id, hdr, log)

        found_movies = find_movies(user_id=user_id, filters=filters, hdr=hdr)
        if not found_movies:
            log.append("No movies found matching the specified filters. Collection not created.")
            return {"status": "ok", "log": log}

        item_ids = [movie["Id"] for movie in found_movies]
        log.append(f"Found {len(item_ids)} movies matching filters.")

        params = {
            "Name": collection_name,
            "Ids": ",".join(item_ids),
            "UserId": user_id,
        }

        request_headers = hdr.copy()
        request_headers["Content-Type"] = "application/json"

        r = client.SESSION.post(f"{client.EMBY_URL}/Collections", params=params, data="{}", headers=request_headers, timeout=15)
        r.raise_for_status()

        log.append(f"Successfully created collection '{collection_name}' with {len(item_ids)} items.")
        return {"status": "ok", "log": log}

    except Exception as e:
        error_message = f"Failed to create collection: {e}"
        log.append(error_message)
        logging.error(error_message)
        if hasattr(e, 'response') and e.response is not None:
            logging.error(f"Response Body: {e.response.text}")
        return {"status": "error", "log": log}