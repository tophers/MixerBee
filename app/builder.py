"""
app/builder.py - Logic for building mixed playlists from blocks.
"""

import logging
import random
from typing import Dict, List, Any, Optional
from itertools import zip_longest

from .items import create_playlist, add_items_to_playlist_by_ids
from .movies import find_movies
from .music import find_songs, get_songs_by_album, get_songs_by_artist
from .tv import episodes, get_first_unwatched_episode, series_id


def _process_tv_block(block: Dict[str, Any], user_id: str, hdr: Dict[str, str], log_messages: List[str], block_index: int) -> List[Dict[str, Any]]:
    """Handles the complex logic of fetching and interleaving TV episodes."""
    items = []
    try:
        should_interleave = block.get("interleave", True)
        groups: List[List[Dict[str, Any]]] = []
        mode = block.get("mode", "count")
        count = int(block.get("count", 1))
        
        end_season = int(block.get("end_season")) if block.get("end_season") else None
        end_episode = int(block.get("end_episode")) if block.get("end_episode") else None

        for raw_show in block.get("shows", []):
            if not isinstance(raw_show, dict) or not raw_show.get("name"):
                log_messages.append(f"Block {block_index}: Invalid show entry skipped.")
                continue
                
            show_name = raw_show["name"]
            sid = series_id(show_name, hdr)
            
            if not sid:
                log_messages.append(f"Block {block_index}: Show not found - {show_name}")
                continue

            s, e = None, None
            is_unwatched = raw_show.get("unwatched", False)
            
            if is_unwatched:
                ep_info = get_first_unwatched_episode(sid, user_id, hdr)
                if ep_info:
                    s = ep_info.get("ParentIndexNumber")
                    e = ep_info.get("IndexNumber")
            else:
                s = int(raw_show.get("season", 1))
                e = int(raw_show.get("episode", 1))

            if s is None or e is None:
                log_messages.append(f"Block {block_index}: Could not determine start episode for '{show_name}'")
                continue

            eps = episodes(sid, s, e, count, hdr, user_id=user_id, end_season=end_season, end_episode=end_episode, only_unwatched=is_unwatched)

            if len(eps) < count and mode == 'count':
                log_messages.append(f"Block {block_index}: Only found {len(eps)}/{count} requested eps for '{show_name}'")
            
            if eps:
                groups.append(eps)

        if groups:
            if should_interleave:
                for bundle in zip_longest(*groups):
                    items.extend(ep for ep in bundle if ep is not None)
                log_messages.append(f"Block {block_index} (TV): Added {len(items)} interleaved episodes.")
            else:
                for episode_group in groups:
                    items.extend(episode_group)
                log_messages.append(f"Block {block_index} (TV): Added {len(items)} sequential episodes.")
                
    except Exception as e:
        log_messages.append(f"Block {block_index} (TV): Failed with error - {e}")
        logging.error(f"Error processing TV block {block_index}: {e}", exc_info=True)
        
    return items


def _process_movie_block(block: Dict[str, Any], user_id: str, hdr: Dict[str, str], log_messages: List[str], block_index: int) -> List[Dict[str, Any]]:
    """Fetches movies based on block filters."""
    items = []
    try:
        filters = block.get("filters", {})
        found_movies = find_movies(user_id=user_id, filters=filters, hdr=hdr)
        items.extend(found_movies)
        log_messages.append(f"Block {block_index} (Movie): Added {len(found_movies)} movies.")
    except Exception as e:
        log_messages.append(f"Block {block_index} (Movie): Failed with error - {e}")
        logging.error(f"Error processing Movie block {block_index}: {e}", exc_info=True)
    return items


def _process_music_block(block: Dict[str, Any], user_id: str, hdr: Dict[str, str], log_messages: List[str], block_index: int) -> List[Dict[str, Any]]:
    """Fetches songs based on album, artist, or genre configurations."""
    items = []
    try:
        music_data = block.get("music", {})
        mode = music_data.get("mode")
        songs = []

        if mode == "album":
            if album_id := music_data.get("albumId"):
                songs = get_songs_by_album(album_id, hdr)
        elif mode == "artist_top":
            if artist_id := music_data.get("artistId"):
                count = int(music_data.get("count", 10))
                songs = get_songs_by_artist(artist_id, hdr, sort="Top", limit=count)
        elif mode == "artist_random":
            if artist_id := music_data.get("artistId"):
                count = int(music_data.get("count", 10))
                all_songs = get_songs_by_artist(artist_id, hdr, sort="Random")
                songs = random.sample(all_songs, min(count, len(all_songs))) if all_songs else []
        elif mode == "genre":
            filters = music_data.get("filters", {})
            songs = find_songs(user_id=user_id, filters=filters, hdr=hdr)

        if songs:
            items.extend(songs)
            log_messages.append(f"Block {block_index} (Music): Added {len(songs)} songs.")

    except Exception as e:
        log_messages.append(f"Block {block_index} (Music): Failed with error - {e}")
        logging.error(f"Error processing music block {block_index}: {e}", exc_info=True)
    
    return items


def generate_items_from_blocks(user_id: str, blocks: List[Dict[str, Any]], hdr: Dict[str, str], log_messages: List[str]) -> List[Dict[str, Any]]:
    """Master orchestrator to process blocks and return a flat list of full item dictionaries."""
    master_items_list: List[Dict[str, Any]] = []
    
    for i, block in enumerate(blocks, 1):
        block_type = block.get("type")

        if block_type == "tv":
            master_items_list.extend(_process_tv_block(block, user_id, hdr, log_messages, i))
        elif block_type == "movie":
            master_items_list.extend(_process_movie_block(block, user_id, hdr, log_messages, i))
        elif block_type == "music":
            master_items_list.extend(_process_music_block(block, user_id, hdr, log_messages, i))
        else:
            log_messages.append(f"Block {i}: Unknown block type '{block_type}' skipped.")
            
    return master_items_list


def format_items_for_preview(items: List[Dict[str, Any]]) -> List[Dict[str, str]]:
    """Formats a list of full item objects for the frontend preview modal."""
    formatted_list = []
    for item in items:
        item_type = item.get("Type")
        name = item.get("Name", "Unknown")
        context = ""

        if item_type == "Episode":
            s_num = item.get("ParentIndexNumber", 0)
            e_num = item.get("IndexNumber", 0)
            series_name = item.get('SeriesName', 'Unknown Series')
            context = f"{series_name} S{s_num:02d}E{e_num:02d}"
        elif item_type == "Movie":
            if year := item.get("ProductionYear"):
                name = f"{name} ({year})"
        elif item_type == "Audio":
            artist = ", ".join([a["Name"] for a in item.get("ArtistItems", [])])
            album = item.get("Album", "")
            if artist and album:
                context = f"{artist} — {album}"
            elif artist:
                context = artist

        formatted_list.append({"name": name, "context": context})

    return formatted_list


def create_mixed_playlist(user_id: str, playlist_name: str, blocks: List[Dict[str, Any]], hdr: Dict[str, str]) -> Dict[str, Any]:
    """Builds a playlist from a list of TV, Movie, and/or Music blocks."""
    log_messages: List[str] = []
    master_items = generate_items_from_blocks(user_id, blocks, hdr, log_messages)
    master_item_ids = [item["Id"] for item in master_items if item.get("Id")]

    if not master_item_ids:
        log_messages.append("No items were found to add. Playlist not created.")
        return {"status": "error", "log": log_messages}

    new_item_id = create_playlist(name=playlist_name, user_id=user_id, ids=master_item_ids, hdr=hdr, log=log_messages)
    return {
        "status": "ok" if new_item_id else "error", 
        "log": log_messages, 
        "new_item_id": new_item_id
    }


def add_items_to_playlist(user_id: str, playlist_id: str, blocks: List[Dict[str, Any]], hdr: Dict[str, str]) -> Dict[str, Any]:
    """Builds a list of items from blocks and adds them to an existing playlist."""
    log_messages: List[str] = []
    master_items = generate_items_from_blocks(user_id, blocks, hdr, log_messages)
    master_item_ids = [item["Id"] for item in master_items if item.get("Id")]

    if not master_item_ids:
        log_messages.append("No items were found to add. No changes made.")
        return {"status": "error", "log": log_messages}

    success = add_items_to_playlist_by_ids(
        playlist_id=playlist_id,
        item_ids=master_item_ids,
        user_id=user_id,
        hdr=hdr,
        log=log_messages
    )

    return {
        "status": "ok" if success else "error", 
        "log": log_messages
    }