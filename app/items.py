"""
app/items.py - Generic playlist, collection, and item management
"""

from datetime import datetime, timedelta
from typing import Dict, List, Any, Optional
import random
import time
import re

import requests

from . import client
from app.logger import get_logger

from .movies import find_movies
from .music import get_songs_by_artist, get_songs_by_album, find_songs
from .tv import get_first_unwatched_episode, get_specific_episode

logger = get_logger("MixerBee.Items")

def sanitize_id(raw_id: Any) -> str:
    """Helper to sanitize movie/tv ids on an item."""
    if not raw_id:
        return ""
 
    s = str(raw_id).strip()
    s = s.lstrip('[').rstrip(']')
    s = re.sub(r'^(id|item id|item)[:\s]+', '', s, flags=re.IGNORECASE)
    
    return s.strip()

def construct_item_url(item_id: Optional[str], media: client.MediaClient) -> Optional[str]:
    return media.item_url(item_id)


def delete_item_by_id(item_id: str, media: client.MediaClient) -> bool:
    """Deletes a single Emby item by its ID. Returns True on success."""
    if not item_id:
        return False
    try:
        logger.info(f"Deleting item {item_id} from server.")
        resp = media.delete(f"/Items/{item_id}", timeout=10)
        resp.raise_for_status()
        return True
    except requests.RequestException:
        logger.error(f"Failed to delete item with ID {item_id}", exc_info=True)
        return False

def get_item_details_by_ids(user_id: str, item_ids: List[str], media: client.MediaClient) -> Dict[str, Dict[str, Any]]:
    """Fetches Genres/Cast/Director/RunTimeTicks for specific item IDs, keyed by Id, for AI refine grounding."""
    details: Dict[str, Dict[str, Any]] = {}
    chunk_size = 200
    for i in range(0, len(item_ids), chunk_size):
        chunk = item_ids[i:i + chunk_size]
        params = {
            "UserId": user_id,
            "Ids": ",".join(chunk),
            "Fields": "Genres,People,RunTimeTicks",
        }
        try:
            r = media.get(f"/Users/{user_id}/Items", params=params, timeout=15)
            r.raise_for_status()
            for item in r.json().get("Items", []):
                item_id = item.get("Id")
                if not item_id:
                    continue
                people = item.get("People", [])
                details[item_id] = {
                    "Genres": item.get("Genres", []),
                    "Cast": [p["Name"] for p in people if p.get("Type") == "Actor" and p.get("Name")][:8],
                    "Directors": [p["Name"] for p in people if p.get("Type") == "Director" and p.get("Name")],
                    "RunTimeTicks": item.get("RunTimeTicks") or 0,
                }
        except requests.RequestException:
            logger.error("Failed to fetch item details for AI refine grounding", exc_info=True)
    return details

def get_item_children(user_id: str, item_id: str, media: client.MediaClient) -> List[Dict]:
    """Fetches the child items of a given playlist or collection."""
    params = {
        "UserId": user_id,
        "ParentId": item_id,
        "Fields": "RunTimeTicks,ParentId,IndexNumber,ParentIndexNumber",
    }
    r = media.get(f"/Users/{user_id}/Items", params=params, timeout=15)
    r.raise_for_status()
    return r.json().get("Items", [])

def get_manageable_items(user_id: str, media: client.MediaClient) -> List[Dict]:
    """Fetches and combines playlists and collections for the Manager tab."""
    if not user_id: return []
    params = {
        "Recursive": "true",
        "IncludeItemTypes": "Playlist,BoxSet,Collection",
        "Fields": "ChildCount,DateCreated,RunTimeTicks",
    }
    r = media.get(f"/Users/{user_id}/Items", params=params, timeout=15)
    r.raise_for_status()

    items = r.json().get("Items", [])

    for item in items:
        item["ItemCount"] = item.get("ChildCount", 0)
        item_type = item.get("Type")
        item["DisplayType"] = "Collection" if item_type in ["BoxSet", "Collection"] else "Playlist"
        item_id = item.get("Id")
        item["ServerUrl"] = media.item_url(item_id) if item_id else ""
        ticks = item.get("RunTimeTicks", 0) or 0
        if ticks > 0:
            total_minutes = int(ticks / 10_000_000 / 60)
            hours, minutes = divmod(total_minutes, 60)
            item["FormattedRuntime"] = f"{hours}h {minutes}m" if hours else f"{minutes}m"
        else:
            item["FormattedRuntime"] = ""

    return items


def remove_item_from_collection(collection_id: str, item_id: str, media: client.MediaClient) -> bool:
    """
    Removes a specific item from an Emby/Jellyfin Collection (BoxSet).
    """
    try:
        url = f"/Collections/{collection_id}/Items"
        params = {"Ids": item_id}
        response = media.delete(url, params=params, timeout=10)
        if response.status_code in [200, 204]:
            logger.info(f"Successfully removed item {item_id} from collection {collection_id}")
            return True
        else:
            logger.error(f"Failed to remove item from collection. Status: {response.status_code}, Response: {response.text}")
            return False
    except Exception as e:
        logger.error(f"Error in remove_item_from_collection: {e}", exc_info=True)
        return False

def get_playlists(user_id: str, media: client.MediaClient) -> List[Dict]:
    """Gets a list of all playlists for a user."""
    params = {
        "IncludeItemTypes": "Playlist",
        "Recursive": "true",
        "Fields": "Id,Name",
        "_": int(time.time() * 1000)
    }
    r = media.get(f"/Users/{user_id}/Items",
                           params=params, timeout=10)
    r.raise_for_status()
    return r.json().get("Items", [])

def remove_item_from_playlist(playlist_id: str, item_id_to_remove: str, media: client.MediaClient) -> bool:
    """Removes a single item from a playlist without deleting the item itself."""
    user_id = media.user_id
    params = {"UserId": user_id, "Fields": "Id"}
    try:
        r = media.get(f"/Playlists/{playlist_id}/Items", params=params, timeout=10)
        r.raise_for_status()
        items = r.json().get("Items", [])
        playlist_item_id = None
        for item in items:
            if item.get("Id") == item_id_to_remove:
                playlist_item_id = item.get("PlaylistItemId")
                break
        if not playlist_item_id:
            logger.warning(f"Could not find item {item_id_to_remove} in playlist {playlist_id} to get its PlaylistItemId.")
            return False
        delete_params = {"EntryIds": playlist_item_id}
        del_resp = media.delete(f"/Playlists/{playlist_id}/Items", params=delete_params, timeout=10)
        del_resp.raise_for_status()
        logger.info(f"Removed item {item_id_to_remove} from playlist {playlist_id}.")
        return True
    except requests.RequestException as e:
        logger.error(f"Failed to remove item {item_id_to_remove} from playlist {playlist_id}: {e}", exc_info=True)
        return False

def _delete_item_by_name(name: str, item_types: str, user_id: str, media: client.MediaClient, log: List[str]):
    """Internal helper to delete items of specific types by their name."""
    params = {
        "IncludeItemTypes": item_types,
        "Recursive": "true",
        "Fields": "Id,Name",
        "_": int(time.time() * 1000)
    }
    try:
        r = media.get(f"/Users/{user_id}/Items", params=params, timeout=10)
        r.raise_for_status()
        
        items = r.json().get("Items") or []
        targets = [i for i in items if i.get("Id") and i.get("Name", "").strip().lower() == name.strip().lower()]
        
        if not targets:
            return
        
        display_type = "collection" if "Collection" in item_types else "playlist"
        for item in targets:
            resp = media.delete(f"/Items/{item.get('Id')}", timeout=10)
            if resp.status_code in (200, 204):
                msg = f"Deleted existing {display_type} '{name}'."
                logger.info(msg)
                log.append(msg)
            else:
                msg = f"Failed deleting {display_type} '{name}': HTTP {resp.status_code}"
                logger.error(msg)
                log.append(msg)
    except Exception as e:
        logger.error(f"Error in _delete_item_by_name for {name}: {e}", exc_info=True)

def delete_playlist(name: str, user_id: str, media: client.MediaClient, log: List[str]):
    """Deletes a playlist by its name."""
    _delete_item_by_name(name, "Playlist", user_id, media, log)

def _restore_items(playlist_id: str, media_ids: List[str], user_id: str, media: client.MediaClient, log: List[str]):
    """Helper to restore items in chunks during a rollback."""
    chunk_size = 50
    failed_restores = 0
    for i in range(0, len(media_ids), chunk_size):
        chunk = media_ids[i:i + chunk_size]
        params = {"UserId": user_id, "Ids": ",".join(chunk)}
        try:
            resp = media.post(
                f"/Playlists/{playlist_id}/Items",
                params=params, timeout=15
            )
            resp.raise_for_status()
        except requests.RequestException as e:
            logger.error(f"Rollback chunk failed: {e}")
            failed_restores += len(chunk)
    if failed_restores > 0:
        msg = f"Rollback incomplete: {failed_restores} items could not be restored."
        logger.error(msg)
        log.append(msg)
    else:
        msg = "Rollback successful. Original items were restored to the playlist."
        logger.info(msg)
        log.append(msg)

def clear_playlist_items(
    playlist_id: str,
    user_id: str,
    media: client.MediaClient,
    log: List[str],
    restore_on_failure: bool = True
) -> bool:
    """
    Removes all items from an existing playlist in safe chunks.
    If a chunk permanently fails, it optionally restores the already-deleted items
    and returns False.
    """
    try:
        # Request with minimal fields to ensure PlaylistItemId is present in root of response items
        r = media.get(f"/Playlists/{playlist_id}/Items",
                               params={"UserId": user_id, "Fields": "Id"}, timeout=10)
        r.raise_for_status()
        items = r.json().get("Items", [])
    except requests.RequestException as e:
        msg = f"Failed to fetch items for playlist {playlist_id}: {e}"
        logger.error(msg, exc_info=True)
        log.append(msg)
        return False

    playlist_entries = [{"media_id": item.get("Id"), "entry_id": item.get("PlaylistItemId")}
                        for item in items if item.get("PlaylistItemId")]
    
    if not playlist_entries:
        logger.info(f"Clear Playlist: No items with PlaylistItemId found in playlist {playlist_id}. Assuming it is already empty.")
        return True
    
    logger.info(f"Clear Playlist: Identified {len(playlist_entries)} entries to remove from playlist {playlist_id}.")
    
    successfully_removed_media_ids = []
    chunk_size = 50
    max_attempts = 3
    for i in range(0, len(playlist_entries), chunk_size):
        chunk = playlist_entries[i:i + chunk_size]
        entry_ids = [c["entry_id"] for c in chunk]
        media_ids = [c["media_id"] for c in chunk]
        chunk_success = False
        for attempt in range(max_attempts):
            try:
                delete_params = {"EntryIds": ",".join(entry_ids)}
                del_resp = media.delete(
                    f"/Playlists/{playlist_id}/Items",
                    params=delete_params, timeout=10
                )
                del_resp.raise_for_status()
                chunk_success = True
                successfully_removed_media_ids.extend(media_ids)
                break
            except requests.RequestException as e:
                logger.warning(f"Failed to delete chunk (Attempt {attempt + 1}/{max_attempts}): {e}")
                time.sleep(1)
        if not chunk_success:
            error_msg = "Failed to clear playlist completely. Initiating rollback to restore removed items..."
            logger.error(error_msg)
            log.append(error_msg)
            if restore_on_failure and successfully_removed_media_ids:
                _restore_items(playlist_id, successfully_removed_media_ids, user_id, media, log)
            return False
            
    logger.info(f"Clear Playlist: Successfully removed all {len(successfully_removed_media_ids)} items.")
    return True

def add_items_to_playlist_by_ids(playlist_id: str, item_ids: List[str], user_id: str, media: client.MediaClient, log: List[str]) -> bool:
    """Appends a list of item IDs to an existing playlist using safe chunks. Fails fast on network errors to prevent duplicates."""
    if not item_ids:
        log.append("No new items to add.")
        return True
    chunk_size = 50
    total_added = 0
    for i in range(0, len(item_ids), chunk_size):
        chunk = item_ids[i:i + chunk_size]
        params = {"UserId": user_id, "Ids": ",".join(chunk)}
        try:
            resp = media.post(f"/Playlists/{playlist_id}/Items",
                                     params=params, timeout=15)
            resp.raise_for_status()
            total_added += len(chunk)
        except requests.RequestException as e:
            error_msg = f"Failed to add a chunk of items ({e}). Aborting to prevent duplicates."
            log.append(error_msg)
            logger.error(error_msg)
            return False
    msg = f"Successfully added {total_added} items to the playlist."
    logger.info(msg)
    log.append(msg)
    return True

def create_playlist(name: str, user_id: str, ids: List[str], media: client.MediaClient, log: List[str]):
    """Creates a new playlist, or updates an existing one in-place to preserve its ID, with full rollback protection."""
    existing_playlists = get_playlists(user_id, media)
    target_playlist = next((p for p in existing_playlists if p.get("Name", "").strip().lower() == name.strip().lower()), None)
    if target_playlist:
        playlist_id = target_playlist["Id"]
        msg = f"Playlist '{name}' already exists. Updating in-place (ID preserved)."
        logger.info(msg)
        log.append(msg)
        try:
            r = media.get(f"/Playlists/{playlist_id}/Items",
                                   params={"UserId": user_id, "Fields": "Id"}, timeout=10)
            r.raise_for_status()
            old_media_ids = [item.get("Id") for item in r.json().get("Items", []) if item.get("Id")]
        except requests.RequestException as e:
            msg = "Failed to backup existing playlist items. Update aborted to prevent data loss."
            logger.error(msg)
            log.append(msg)
            return None
        if clear_playlist_items(playlist_id, user_id, media, log):
            success = add_items_to_playlist_by_ids(playlist_id, ids, user_id, media, log)
            if success:
                return playlist_id
            else:
                msg = "Addition phase failed. Rolling back to original playlist state..."
                logger.error(msg)
                log.append(msg)
                clear_success = clear_playlist_items(playlist_id, user_id, media, log, restore_on_failure=False)
                if clear_success:
                    _restore_items(playlist_id, old_media_ids, user_id, media, log)
                else:
                    msg = "CRITICAL: Could not wipe partial additions during rollback. Aborting restore to prevent a corrupted/mixed playlist."
                    logger.error(msg)
                    log.append(msg)
                return None
        else:
            log.append("Failed to clear existing playlist items. Update aborted.")
            return None
    else:
        first_chunk = ids[:50] if ids else []
        logger.info(f"Creating new playlist '{name}' on server.")
        resp = media.post(
            "/Playlists",
            params={"Name": name, "UserId": user_id, "Ids": ",".join(first_chunk)},
            timeout=10
        )
        if resp.ok:
            new_id = resp.json().get("Id")
            msg = f"Playlist '{name}' created successfully."
            logger.info(msg)
            log.append(msg)
            if len(ids) > 50:
                success = add_items_to_playlist_by_ids(new_id, ids[50:], user_id, media, log)
                if not success:
                    msg = "Failed to append all items. Rolling back by deleting incomplete playlist."
                    logger.error(msg)
                    log.append(msg)
                    delete_success = delete_item_by_id(new_id, media)
                    if not delete_success:
                        msg = f"CRITICAL: Failed to delete incomplete playlist (ID: {new_id}) during rollback. Orphaned playlist remains on server."
                        logger.error(msg)
                        log.append(msg)
                    return None
            return new_id
        else:
            msg = f"Failed to create playlist (HTTP {resp.status_code}): {resp.text}"
            logger.error(msg)
            log.append(msg)
            return None

def delete_playlist_by_id(playlist_id: str, media: client.MediaClient, log: List[str]) -> bool:
    """Deletes exactly one playlist by ID.

    Rollbacks must use this, never delete_playlist(): that one searches by name and
    would happily destroy a pre-existing user playlist that merely shares the name.
    """
    if not playlist_id:
        return False
    if delete_item_by_id(playlist_id, media):
        log.append(f"Removed incomplete playlist (ID: {playlist_id}).")
        return True
    msg = f"CRITICAL: Failed to delete incomplete playlist (ID: {playlist_id}). Orphaned playlist remains on server."
    logger.error(msg)
    log.append(msg)
    return False

def set_playlist_overview(playlist_id: str, user_id: str, overview: str, media: client.MediaClient, log: List[str]) -> bool:
    """Writes a description onto an existing playlist.

    POST /Playlists takes no Overview, so the description needs a second call that
    posts back the full item DTO. This is cosmetic: callers must treat failure as a
    partial success and keep the playlist rather than rolling it back.
    """
    if overview is None:
        return True
    try:
        r = media.get(f"/Users/{user_id}/Items", params={"Ids": playlist_id}, timeout=10)
        r.raise_for_status()
        items = r.json().get("Items", [])
        if not items:
            log.append("Playlist created, but its description could not be applied (item not found).")
            return False
        dto = items[0]
        dto["Overview"] = overview
        resp = media.post(f"/Items/{playlist_id}", json=dto, timeout=15)
        resp.raise_for_status()
        return True
    except requests.RequestException as e:
        msg = f"Playlist created, but the description could not be saved: {e}"
        logger.warning(msg)
        log.append(msg)
        return False

def create_playlist_exclusive(name: str, user_id: str, ids: List[str], media: client.MediaClient, log: List[str]) -> Optional[str]:
    """Creates a brand-new playlist and never touches an existing one.

    create_playlist() adopts a same-named playlist and replaces its contents. Playlist
    Assist must not do that: the user curated this list by hand, and silently wiping
    an unrelated playlist that happens to share the name is unrecoverable. On a failure
    after creation, the rollback deletes by the ID we just created.
    """
    if not ids:
        log.append("No items to add. Playlist not created.")
        return None

    first_chunk = ids[:50]
    logger.info(f"Creating new playlist '{name}' on server (exclusive create).")
    try:
        resp = media.post(
            "/Playlists",
            params={"Name": name, "UserId": user_id, "Ids": ",".join(first_chunk)},
            timeout=15
        )
    except requests.RequestException as e:
        msg = f"Failed to create playlist '{name}': {e}"
        logger.error(msg)
        log.append(msg)
        return None

    if not resp.ok:
        msg = f"Failed to create playlist (HTTP {resp.status_code}): {resp.text}"
        logger.error(msg)
        log.append(msg)
        return None

    new_id = resp.json().get("Id")
    if not new_id:
        msg = "Media server created the playlist but returned no ID."
        logger.error(msg)
        log.append(msg)
        return None

    log.append(f"Playlist '{name}' created successfully.")

    if len(ids) > 50:
        if not add_items_to_playlist_by_ids(new_id, ids[50:], user_id, media, log):
            log.append("Failed to append all items. Rolling back by deleting the new playlist.")
            delete_playlist_by_id(new_id, media, log)
            return None

    return new_id

def create_recently_added_playlist(user_id: str, playlist_name: str, count: int, media: client.MediaClient, log: List[str]):
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
        r_movies = media.get(f"/Users/{user_id}/Items", params=movie_params, timeout=15)
        r_movies.raise_for_status()
        recent_movies = r_movies.json().get("Items", [])
        log.append(f"Found {len(recent_movies)} recent movies.")
        episode_params = base_params.copy()
        episode_params["IncludeItemTypes"] = "Episode"
        r_episodes = media.get(f"/Users/{user_id}/Items", params=episode_params, timeout=15)
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
            next_ep_data = get_first_unwatched_episode(series_id, user_id, media)
            if next_ep_data and next_ep_data.get("Id"):
                next_ep_data["DateCreated"] = date_created
                next_up_episodes.append(next_ep_data)
        combined_items = recent_movies + next_up_episodes
        if not combined_items:
            log.append("No recently added items found. Playlist not created.")
            return {"status": "ok", "log": log}
        combined_items.sort(key=lambda x: x.get("DateCreated", ""), reverse=True)
        final_items = combined_items[:count]
        item_ids = [item["Id"] for item in final_items]
        log.append(f"Creating playlist with the top {len(final_items)} most recently added items (using next-up for shows).")
        new_item_id = create_playlist(name=playlist_name, user_id=user_id, ids=item_ids, media=media, log=log)
        return {"status": "ok" if new_item_id else "error", "log": log, "new_item_id": new_item_id}
    except requests.RequestException as e:
        log.append(f"An API error occurred: {e}")
        return {"status": "error", "log": log}
    except Exception as e:
        log.append(f"An unexpected error occurred: {e}")
        logger.error("Error in create_recently_added_playlist", exc_info=True)
        return {"status": "error", "log": log}

def create_pilot_sampler_playlist(user_id: str, playlist_name: str, count: int, media: client.MediaClient, log: List[str]):
    """Creates a playlist of unwatched pilot episodes."""
    try:
        all_series_resp = media.get(
            f"/Users/{user_id}/Items",
            params={"IncludeItemTypes": "Series", "Recursive": "true", "Fields": "Id,Name"},
            timeout=20
        )
        all_series_resp.raise_for_status()
        all_series = all_series_resp.json().get("Items", [])
        unwatched_pilots = []
        for series in all_series:
            series_id = series["Id"]
            series_stats_resp = media.get(
                f"/Shows/{series_id}/Episodes",
                params={"UserId": user_id, "IsPlayed": "false", "Limit": 1},
                timeout=10
            )
            series_stats_resp.raise_for_status()
            unplayed_count = series_stats_resp.json().get("TotalRecordCount", 0)
            series_total_resp = media.get(
                f"/Shows/{series_id}/Episodes",
                params={"UserId": user_id, "Limit": 1},
                timeout=10
            )
            series_total_resp.raise_for_status()
            total_count = series_total_resp.json().get("TotalRecordCount", 0)
            if unplayed_count == total_count and total_count > 0:
                pilot_ep = get_specific_episode(series_id, 1, 1, media)
                if pilot_ep:
                    unwatched_pilots.append(pilot_ep)
        if not unwatched_pilots:
            log.append("No unstarted shows found. Playlist not created.")
            return {"status": "ok", "log": log}
        num_to_sample = min(count, len(unwatched_pilots))
        log.append(f"Found {len(unwatched_pilots)} unstarted shows. Creating playlist with {num_to_sample} random pilots.")
        selected_pilots = random.sample(unwatched_pilots, num_to_sample)
        pilot_ids = [ep["Id"] for ep in selected_pilots]
        new_item_id = create_playlist(name=playlist_name, user_id=user_id, ids=pilot_ids, media=media, log=log)
        return {"status": "ok" if new_item_id else "error", "log": log, "new_item_id": new_item_id}
    except requests.RequestException as e:
        log.append(f"An error occurred: {e}")
        return {"status": "error", "log": log}

def create_continue_watching_playlist(user_id: str, playlist_name: str, count: int, media: client.MediaClient, log: List[str]):
    """Creates a playlist of the next unwatched episodes from in-progress shows."""
    try:
        resume_params = {
            "Recursive": "true",
            "Fields": "SeriesId",
            "IncludeItemTypes": "Episode",
            "SortBy": "DatePlayed",
            "SortOrder": "Descending"
        }
        r = media.get(f"/Users/{user_id}/Items/Resume", params=resume_params, timeout=15)
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
            next_ep = get_first_unwatched_episode(series_id, user_id, media)
            if next_ep and next_ep.get("Id"):
                next_episode_ids.append(next_ep["Id"])
        if not next_episode_ids:
            log.append("Found in-progress shows, but could not find any playable next episodes. Playlist not created.")
            return {"status": "ok", "log": log}
        new_item_id = create_playlist(name=playlist_name, user_id=user_id, ids=next_episode_ids, media=media, log=log)
        return {"status": "ok" if new_item_id else "error", "log": log, "new_item_id": new_item_id}
    except requests.RequestException as e:
        log.append(f"An error occurred: {e}")
        return {"status": "error", "log": log}

def create_forgotten_favorites_playlist(user_id: str, playlist_name: str, count: int, media: client.MediaClient, log: List[str]):
    """Creates a playlist of favorited movies the user has not watched in a year."""
    try:
        params = {
            "IncludeItemTypes": "Movie",
            "Recursive": "true",
            "Filters": "IsFavorite",
            "Fields": "UserData,DateCreated",
            "UserId": user_id
        }
        r = media.get(f"/Users/{user_id}/Items", params=params, timeout=20)
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
        new_item_id = create_playlist(name=playlist_name, user_id=user_id, ids=movie_ids, media=media, log=log)
        return {"status": "ok" if new_item_id else "error", "log": log, "new_item_id": new_item_id}
    except requests.RequestException as e:
        log.append(f"An API error occurred: {e}")
        return {"status": "error", "log": log}
    except Exception as e:
        log.append(f"An unexpected error occurred: {e}")
        return {"status": "error", "log": log}

def create_movie_marathon_playlist(user_id: str, playlist_name: str, genre: str, count: int, media: client.MediaClient, log: List[str]):
    """Creates a playlist of random, unwatched movies from a specific genre."""
    try:
        filters = {
            "genres_any": [genre] if genre else [],
            "watched_status": "unplayed",
            "sort_by": "Random",
            "limit": count
        }
        found_movies = find_movies(user_id=user_id, filters=filters, media=media)
        if not found_movies:
            log.append(f"No unwatched movies found for genre '{genre}'. Playlist not created.")
            return {"status": "ok", "log": log}
        movie_ids = [m["Id"] for m in found_movies]
        log.append(f"Found {len(found_movies)} movies for your '{genre}' marathon.")
        new_item_id = create_playlist(name=playlist_name, user_id=user_id, ids=movie_ids, media=media, log=log)
        return {"status": "ok" if new_item_id else "error", "log": log, "new_item_id": new_item_id}
    except requests.RequestException as e:
        log.append(f"An API error occurred: {e}")
        return {"status": "error", "log": log}
    except Exception as e:
        log.append(f"An unexpected error occurred: {e}")
        return {"status": "error", "log": log}

def create_artist_spotlight_playlist(user_id: str, playlist_name: str, artist_id: str, count: int, media: client.MediaClient, log: List[str]):
    """Creates a playlist of top tracks for a specific artist."""
    try:
        top_songs = get_songs_by_artist(artist_id, media, sort="Top", limit=count)
        if not top_songs:
            log.append(f"No songs found for the selected artist. Playlist not created.")
            return {"status": "ok", "log": log}
        song_ids = [song["Id"] for song in top_songs]
        log.append(f"Found {len(top_songs)} top songs for your artist spotlight.")
        new_item_id = create_playlist(name=playlist_name, user_id=user_id, ids=song_ids, media=media, log=log)
        return {"status": "ok" if new_item_id else "error", "log": log, "new_item_id": new_item_id}
    except requests.RequestException as e:
        log.append(f"An API error occurred: {e}")
        return {"status": "error", "log": log}
    except Exception as e:
        log.append(f"An unexpected error occurred: {e}")
        return {"status": "error", "log": log}

def create_album_playlist(user_id: str, playlist_name: str, album_id: str, media: client.MediaClient, log: List[str]):
    """Creates a playlist from all the songs in a given album."""
    try:
        album_songs = get_songs_by_album(album_id, media)
        if not album_songs:
            log.append(f"Could not find any songs for the selected album. Playlist not created.")
            return {"status": "ok", "log": log}
        song_ids = [song["Id"] for song in album_songs]
        log.append(f"Found {len(album_songs)} songs for album playlist.")
        new_item_id = create_playlist(name=playlist_name, user_id=user_id, ids=song_ids, media=media, log=log)
        return {"status": "ok" if new_item_id else "error", "log": log, "new_item_id": new_item_id}
    except requests.RequestException as e:
        log.append(f"An API error occurred: {e}")
        return {"status": "error", "log": log}
    except Exception as e:
        log.append(f"An unexpected error occurred: {e}")
        return {"status": "error", "log": log}

def create_music_genre_playlist(user_id: str, playlist_name: str, genre: str, count: int, media: client.MediaClient, log: List[str]):
    """Creates a playlist of random songs from a specific music genre."""
    try:
        filters = {
            "genres": [genre],
            "sort_by": "Random",
            "limit": count
        }
        found_songs = find_songs(user_id=user_id, filters=filters, media=media)
        if not found_songs:
            log.append(f"No songs found for genre '{genre}'. Playlist not created.")
            return {"status": "ok", "log": log}
        song_ids = [s["Id"] for s in found_songs]
        log.append(f"Found {len(found_songs)} songs for your '{genre}' genre sampler.")
        new_item_id = create_playlist(name=playlist_name, user_id=user_id, ids=song_ids, media=media, log=log)
        return {"status": "ok" if new_item_id else "error", "log": log, "new_item_id": new_item_id}
    except requests.RequestException as e:
        log.append(f"An API error occurred: {e}")
        return {"status": "error", "log": log}
    except Exception as e:
        log.append(f"An unexpected error occurred: {e}")
        return {"status": "error", "log": log}
def create_top_community_unwatched_playlist(user_id: str, playlist_name: str, count: int, media: client.MediaClient, log: List[str]):
    """Creates a playlist of the top community-rated unwatched movies."""
    try:
        filters = {
            "watched_status": "unplayed",
            "sort_by": "CommunityRating",
            "limit": count
        }
        found_movies = find_movies(user_id=user_id, filters=filters, media=media)
        if not found_movies:
            log.append("No unwatched movies found. Playlist not created.")
            return {"status": "ok", "log": log}
        
        movie_ids = [m["Id"] for m in found_movies]
        log.append(f"Found {len(found_movies)} top community-rated movies.")
        new_item_id = create_playlist(name=playlist_name, user_id=user_id, ids=movie_ids, media=media, log=log)
        return {"status": "ok" if new_item_id else "error", "log": log, "new_item_id": new_item_id}
    except requests.RequestException as e:
        log.append(f"An API error occurred: {e}")
        return {"status": "error", "log": log}
    except Exception as e:
        log.append(f"An unexpected error occurred: {e}")
        return {"status": "error", "log": log}

def create_top_critic_unwatched_playlist(user_id: str, playlist_name: str, count: int, media: client.MediaClient, log: List[str]):
    """Creates a playlist of the top critic-rated unwatched movies."""
    try:
        filters = {
            "watched_status": "unplayed",
            "sort_by": "CriticRating",
            "limit": count
        }
        found_movies = find_movies(user_id=user_id, filters=filters, media=media)
        if not found_movies:
            log.append("No unwatched movies found. Playlist not created.")
            return {"status": "ok", "log": log}
        
        movie_ids = [m["Id"] for m in found_movies]
        log.append(f"Found {len(found_movies)} top critic-rated movies.")
        new_item_id = create_playlist(name=playlist_name, user_id=user_id, ids=movie_ids, media=media, log=log)
        return {"status": "ok" if new_item_id else "error", "log": log, "new_item_id": new_item_id}
    except requests.RequestException as e:
        log.append(f"An API error occurred: {e}")
        return {"status": "error", "log": log}
    except Exception as e:
        log.append(f"An unexpected error occurred: {e}")
        return {"status": "error", "log": log}

def get_collections(user_id: str, media: client.MediaClient) -> List[Dict]:
    """Gets a list of all collections (BoxSets/Collections) for a user."""
    params = {
        "IncludeItemTypes": "BoxSet,Collection",
        "Recursive": "true",
        "Fields": "Id,Name"
    }
    r = media.get(f"/Users/{user_id}/Items",
                           params=params, timeout=10)
    r.raise_for_status()
    return r.json().get("Items", [])

def delete_collection(name: str, user_id: str, media: client.MediaClient, log: List[str]):
    """Deletes a collection by its name, checking for both Emby and Jellyfin types."""
    _delete_item_by_name(name, "BoxSet,Collection", user_id, media, log)

def resolve_collection_selection(filters: Dict[str, Any], user_id: str, media: client.MediaClient) -> List[str]:
    """Resolves matching movie IDs for a collection before modifying server state."""
    found_movies = find_movies(user_id=user_id, filters=filters, media=media)
    return [movie["Id"] for movie in found_movies if movie.get("Id")]

def create_movie_collection(user_id: str, collection_name: str, filters: Dict, media: client.MediaClient) -> Dict:
    """
    Non-destructive collection build:
    1. Resolves candidate movie selection first; refuses if empty (leaving existing collection intact).
    2. Captures prior membership for rollback if recreate is necessary.
    3. Tries in-place membership update (preserving collection ID) before falling back to recreate.
    4. Distinguishes 'replaced', 'refused', and 'failed' outcomes.
    """
    log: List[str] = []
    try:
        new_ids = resolve_collection_selection(filters, user_id, media)
        if not new_ids:
            msg = "No movies found matching collection filters. Collection build refused; existing collection left unchanged."
            log.append(msg)
            logger.info(msg)
            return {"status": "refused", "log": log, "collection_name": collection_name}

        log.append(f"Resolved {len(new_ids)} movies for collection '{collection_name}'.")

        existing_collections = get_collections(user_id, media)
        existing = next((c for c in existing_collections if (c.get("Name") or "").strip().lower() == collection_name.strip().lower()), None)

        if existing:
            collection_id = existing["Id"]
            old_children = get_item_children(user_id, collection_id, media)
            old_ids = [c["Id"] for c in old_children if c.get("Id")]

            # Try in-place replacement
            to_remove = [x for x in old_ids if x not in new_ids]
            to_add = [x for x in new_ids if x not in old_ids]

            in_place_success = True
            if to_remove:
                del_resp = media.delete(f"/Collections/{collection_id}/Items", params={"Ids": ",".join(to_remove)}, timeout=15)
                if not del_resp.ok:
                    in_place_success = False
            if in_place_success and to_add:
                add_resp = media.post(f"/Collections/{collection_id}/Items", params={"Ids": ",".join(to_add)}, timeout=15)
                if not add_resp.ok:
                    in_place_success = False

            if in_place_success:
                msg = f"Successfully updated collection '{collection_name}' in-place with {len(new_ids)} items (server ID preserved)."
                logger.info(msg)
                log.append(msg)
                return {"status": "replaced", "log": log, "new_item_id": collection_id}

            # Fallback to delete-and-recreate with restore capability
            logger.warning(f"In-place collection update not fully supported for '{collection_name}'; falling back to recreate with rollback protection.")
            delete_collection(collection_name, user_id, media, log)
            new_id = create_collection_from_ids(user_id, collection_name, new_ids, media, log)
            if new_id:
                msg = f"Successfully recreated collection '{collection_name}' with {len(new_ids)} items."
                log.append(msg)
                return {"status": "replaced", "log": log, "new_item_id": new_id}

            # Attempt rollback
            logger.error(f"Recreate failed for '{collection_name}'. Attempting restore of {len(old_ids)} prior items...")
            restored_id = create_collection_from_ids(user_id, collection_name, old_ids, media, log)
            if restored_id:
                msg = f"CRITICAL: Failed to recreate collection, but successfully restored original {len(old_ids)} members."
                logger.warning(msg)
                log.append(msg)
                return {"status": "failed", "log": log}
            else:
                msg = f"CRITICAL: Failed to recreate collection '{collection_name}' and restore failed. Collection may be missing."
                logger.error(msg)
                log.append(msg)
                return {"status": "failed", "log": log}

        # Brand new collection
        new_id = create_collection_from_ids(user_id, collection_name, new_ids, media, log)
        if new_id:
            msg = f"Successfully created collection '{collection_name}' with {len(new_ids)} items."
            log.append(msg)
            return {"status": "replaced", "log": log, "new_item_id": new_id}
        else:
            return {"status": "failed", "log": log}

    except Exception as e:
        error_message = f"Failed to build collection: {e}"
        log.append(error_message)
        logger.error(error_message, exc_info=True)
        return {"status": "failed", "log": log}

def create_collection_from_ids(user_id: str, collection_name: str, item_ids: List[str], media: client.MediaClient, log: List[str]) -> str:
    """Creates a collection directly from a list of explicit item IDs."""
    try:
        params = {
            "Name": collection_name,
            "Ids": ",".join(item_ids),
            "UserId": user_id,
        }
        request_headers = {"Content-Type": "application/json"}
        r = media.post("/Collections", params=params, data="{}", headers=request_headers, timeout=15)
        r.raise_for_status()
        new_id = r.json().get("Id")
        msg = f"Successfully created collection '{collection_name}'."
        logger.info(msg)
        log.append(msg)
        return new_id
    except Exception as e:
        log.append(f"Failed to create collection: {e}")
        logger.error(f"Failed to create collection from IDs: {e}", exc_info=True)
        return None