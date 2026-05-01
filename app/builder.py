"""
app/builder.py - Logic for building mixed playlists from blocks
"""

import logging
import random
from typing import Dict, List, Any, Optional
from itertools import zip_longest

from . import client
from . import items as items_api
from .items import create_playlist, add_items_to_playlist_by_ids
from .movies import find_movies
from .music import find_songs, get_songs_by_album, get_songs_by_artist
from .tv import episodes, get_first_unwatched_episode, get_random_unwatched_episode, get_first_available_episode, series_id


def _process_tv_block(block: Dict[str, Any], user_id: str, hdr: Dict[str, str], log_messages: List[str], block_index: int) -> List[Dict[str, Any]]:
    items = []
    try:
        should_interleave = block.get("interleave", True)
        groups: List[List[Dict[str, Any]]] = []
        count = int(block.get("count", 1))

        for raw_show in block.get("shows", []):
            try:
                if not isinstance(raw_show, dict):
                    continue

                show_name = raw_show.get("name")
                sid = items_api.sanitize_id(raw_show.get("id"))

                if not sid and show_name:
                    sid = series_id(show_name, hdr)

                if not sid:
                    continue

                # Trust the UI's selected season/episode unconditionally to guarantee stability
                s = raw_show.get("season")
                e = raw_show.get("episode")
                is_unwatched = raw_show.get("unwatched", False)

                if s is not None: s = int(s)
                if e is not None: e = int(e)

                # ONLY run smart resolution if the payload is missing S/E data
                if s is None or e is None:
                    if is_unwatched:
                        ep_info = get_first_unwatched_episode(sid, user_id, hdr)
                        if ep_info:
                            s = ep_info.get("ParentIndexNumber")
                            e = ep_info.get("IndexNumber")
                    
                    if s is None or e is None:
                        first_ep = get_first_available_episode(sid, user_id, hdr)
                        if first_ep:
                            s = first_ep.get("ParentIndexNumber")
                            e = first_ep.get("IndexNumber")
                        else:
                            s, e = 1, 1

                # Fetch episodes sequentially starting from strictly locked S/E
                eps = episodes(sid, s, e, count, hdr, user_id=user_id, only_unwatched=is_unwatched)

                if eps:
                    groups.append(eps)
            except Exception as inner_e:
                logging.warning(f"Skipping series in block {block_index} due to error: {inner_e}")
                continue

        if groups:
            if should_interleave:
                for bundle in zip_longest(*groups):
                    items.extend(ep for ep in bundle if ep is not None)
            else:
                for episode_group in groups:
                    items.extend(episode_group)

    except Exception as e:
        logging.error(f"Error processing TV block {block_index}: {e}", exc_info=True)

    return items


def _process_movie_block(block: Dict[str, Any], user_id: str, hdr: Dict[str, str], log_messages: List[str], block_index: int) -> List[Dict[str, Any]]:
    items = []
    try:
        filters = block.get("filters", {}).copy()

        if "ids" in filters and filters["ids"]:
            raw_ids = filters["ids"]
            id_list = []
            if isinstance(raw_ids, list):
                id_list = [items_api.sanitize_id(x) for x in raw_ids if x]
            else:
                id_list = [items_api.sanitize_id(raw_ids)]

            if id_list:
                id_filters = {"ids": id_list}

                limit_val = filters.get("limit")
                if limit_val is not None:
                    id_filters["limit"] = int(limit_val)
                    
                # Preserve sort properties if UI provided them
                if "sort_by" in filters:
                    id_filters["sort_by"] = filters["sort_by"]

                items = find_movies(user_id=user_id, filters=id_filters, hdr=hdr)
        else:
            items = find_movies(user_id=user_id, filters=filters, hdr=hdr)

    except Exception as e:
        logging.error(f"Error processing Movie block {block_index}: {e}", exc_info=True)
    return items


def _process_music_block(block: Dict[str, Any], user_id: str, hdr: Dict[str, str], log_messages: List[str], block_index: int) -> List[Dict[str, Any]]:
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

    except Exception as e:
        logging.error(f"Error processing music block {block_index}: {e}", exc_info=True)

    return items


def generate_items_from_blocks(user_id: str, blocks: List[Dict[str, Any]], hdr: Dict[str, str], log_messages: List[str]) -> List[Dict[str, Any]]:
    master_items_list: List[Dict[str, Any]] = []

    for i, block in enumerate(blocks, 1):
        block_type = block.get("type")
        if block_type == "tv" or (block_type == "vibe" and block.get("vibe_type") == "tv"):
            master_items_list.extend(_process_tv_block(block, user_id, hdr, log_messages, i))
        elif block_type == "movie" or (block_type == "vibe" and block.get("vibe_type") == "movie"):
            master_items_list.extend(_process_movie_block(block, user_id, hdr, log_messages, i))
        elif block_type == "music":
            master_items_list.extend(_process_music_block(block, user_id, hdr, log_messages, i))

    return master_items_list


def format_items_for_preview(items: List[Dict[str, Any]]) -> List[Dict[str, str]]:
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