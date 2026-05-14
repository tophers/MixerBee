"""
app/builder.py - Logic for building mixed playlists from blocks with randomized Echo sampling.
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

                s = raw_show.get("season")
                e = raw_show.get("episode")
                is_unwatched = raw_show.get("unwatched", False)

                if s is not None: s = int(s)
                if e is not None: e = int(e)

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

                # Resolve and force the order provided by the incoming list
                resolved_items = find_movies(user_id=user_id, filters=id_filters, hdr=hdr)
                item_map = {item.get("Id"): item for item in resolved_items}
                for rid in id_list:
                    if rid in item_map:
                        items.append(item_map[rid])
        else:
            items = find_movies(user_id=user_id, filters=filters, hdr=hdr)

    except Exception as e:
        logging.error(f"Error processing Movie block {block_index}: {e}", exc_info=True)
    return items

def _process_mirror_block(block: Dict[str, Any], user_id: str, hdr: Dict[str, str], log_messages: List[str], block_index: int) -> List[Dict[str, Any]]:
    """
    Handles logic for the Echo (Mirror) block.
    """
    items = []
    try:
        from .ai.vector_store import search_by_composite_similarity

        filters = block.get("filters", {})
        
        # If specific IDs are provided (cached from frontend preview or Snapshot), resolve them in exact order
        if "ids" in filters and filters["ids"]:
            target_ids = filters["ids"]
            resolved_map = {}
            
            # 1. Resolve as movies first
            resolved_movies = find_movies(user_id=user_id, filters={"ids": target_ids}, hdr=hdr)
            for m in resolved_movies:
                resolved_map[m["Id"]] = m
            
            # 2. Resolve remaining IDs as generic items (episodes)
            remaining_ids = [tid for tid in target_ids if tid not in resolved_map]
            for rid in remaining_ids:
                item_info = items_api.get_item_children(user_id, rid, hdr) # Fallback resolving
                if not item_info: # Try direct get if not children
                    item_resp = client.SESSION.get(f"{client.EMBY_URL}/Users/{user_id}/Items/{rid}", headers=hdr, timeout=5)
                    if item_resp.ok:
                        resolved_map[rid] = item_resp.json()
            
            # 3. Reconstruct the list in the exact order requested by the block
            ordered_items = []
            for tid in target_ids:
                if tid in resolved_map:
                    ordered_items.append(resolved_map[tid])
            
            return ordered_items

        seeds_pos = [s['Id'] for s in filters.get("seeds_positive", [])]
        seeds_neg = [s['Id'] for s in filters.get("seeds_negative", [])]
        mixed_echo = filters.get("mixed_echo", False)
        include_seeds = filters.get("include_seeds", False)

        target_limit = int(block.get("limit", 10))
        threshold = float(block.get("threshold", 0.65))

        if not seeds_pos:
            return []

        pool_size = max(40, target_limit * 4)
        similar_pool = search_by_composite_similarity(
            positive_ids=seeds_pos,
            negative_ids=seeds_neg,
            limit=pool_size,
            threshold=threshold,
            mixed_echo=mixed_echo
        )

        if similar_pool:
            sampled_matches = random.sample(similar_pool, min(target_limit, len(similar_pool)))

            movie_ids = []
            series_ids = []

            for match in sampled_matches:
                m_type = match.get("Type")
                m_id = match.get("Id")
                if m_type == "Movie":
                    movie_ids.append(m_id)
                elif m_type == "Series":
                    series_ids.append(m_id)

            if movie_ids:
                resolved_movies = find_movies(user_id=user_id, filters={"ids": movie_ids}, hdr=hdr)
                items.extend(resolved_movies)

            for sid in series_ids:
                next_ep = get_first_unwatched_episode(sid, user_id, hdr)
                if not next_ep:
                    next_ep = get_first_available_episode(sid, user_id, hdr)
                if next_ep:
                    items.append(next_ep)

            random.shuffle(items)

        if include_seeds:
            master_items = []
            from .ai.vector_store import media_collection
            seed_data = media_collection.get(ids=seeds_pos, include=["metadatas"])

            if seed_data and seed_data.get("ids"):
                for i, sid in enumerate(seed_data["ids"]):
                    meta = seed_data["metadatas"][i]
                    m_type = meta.get("type")

                    if m_type == "Movie":
                        m_list = find_movies(user_id=user_id, filters={"ids": [sid]}, hdr=hdr)
                        if m_list: master_items.append(m_list[0])
                    elif m_type == "Series":
                        next_ep = get_first_unwatched_episode(sid, user_id, hdr)
                        if not next_ep:
                            next_ep = get_first_available_episode(sid, user_id, hdr)
                        if next_ep: master_items.append(next_ep)

            items = master_items + items

    except Exception as e:
        logging.error(f"Error processing Echo block {block_index}: {e}", exc_info=True)
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
        elif block_type == "mirror" or block_type == "echo":
            master_items_list.extend(_process_mirror_block(block, user_id, hdr, log_messages, i))

    return master_items_list


def format_items_for_preview(items: List[Dict[str, Any]]) -> List[Dict[str, str]]:
    formatted_list = []
    for item in items:
        item_id = item.get("Id")
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

        formatted_list.append({"Id": item_id, "name": name, "context": context})

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