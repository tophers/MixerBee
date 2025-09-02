"""
app/builder.py - Logic for building mixed playlists from blocks.
"""

import logging
import random
from typing import Dict, List
from itertools import zip_longest

from .items import create_playlist, add_items_to_playlist_by_ids
from .movies import find_movies
from .music import find_songs, get_songs_by_album, get_songs_by_artist
from .tv import (episodes, get_first_unwatched_episode, parse_show,
                 series_id)


def generate_items_from_blocks(user_id: str, blocks: List[Dict], hdr: Dict[str, str], log_messages: List[str]) -> List[Dict]:
    """Internal helper to process blocks and return a list of full item dictionaries."""
    master_items_list: List[Dict] = []
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
                                    s = ep_info.get("ParentIndexNumber")
                                    e = ep_info.get("IndexNumber")
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

                    mode = block.get("mode", "count")
                    count = int(block.get("count", 1))
                    end_season = None
                    end_episode = None

                    if mode == 'range':
                        end_season_str = block.get("end_season")
                        end_episode_str = block.get("end_episode")
                        if end_season_str and end_episode_str:
                            end_season = int(end_season_str)
                            end_episode = int(end_episode_str)

                    eps = episodes(sid, s, e, count, hdr, user_id=user_id, end_season=end_season, end_episode=end_episode)

                    if len(eps) < count and mode == 'count':
                        log_messages.append(f"Block {i}: Only found {len(eps)}/{count} unwatched eps for '{show_name}'")
                    groups.append(eps)

                if groups:
                    if should_interleave:
                        interleaved_items = []
                        for bundle in zip_longest(*groups):
                            interleaved_items.extend(ep for ep in bundle if ep is not None)
                        master_items_list.extend(interleaved_items)
                        log_messages.append(f"Block {i} (TV): Added {len(interleaved_items)} interleaved episodes.")
                    else:
                        total_added = 0
                        for episode_group in groups:
                            master_items_list.extend(episode_group)
                            total_added += len(episode_group)
                        log_messages.append(f"Block {i} (TV): Added {total_added} sequential episodes.")
            except Exception as e:
                log_messages.append(f"Block {i} (TV): Failed with error - {e}")
                logging.error(f"Error processing TV block {i}: {e}", exc_info=True)

        elif block_type == "movie":
            try:
                found_movies = find_movies(user_id=user_id, filters=block.get("filters", {}), hdr=hdr)
                master_items_list.extend(found_movies)
                log_messages.append(f"Block {i} (Movie): Added {len(found_movies)} movies.")
            except Exception as e:
                log_messages.append(f"Block {i} (Movie): Failed with error - {e}")
                logging.error(f"Error processing Movie block {i}: {e}", exc_info=True)

        elif block_type == "music":
            try:
                music_data = block.get("music", {})
                mode = music_data.get("mode")
                songs = []

                if mode == "album":
                    album_id = music_data.get("albumId")
                    if album_id:
                        songs = get_songs_by_album(album_id, hdr)
                elif mode == "artist_top":
                    artist_id = music_data.get("artistId")
                    if artist_id:
                        count = int(music_data.get("count", 10))
                        songs = get_songs_by_artist(artist_id, hdr, sort="Top", limit=count)
                elif mode == "artist_random":
                    artist_id = music_data.get("artistId")
                    if artist_id:
                        count = int(music_data.get("count", 10))
                        all_songs = get_songs_by_artist(artist_id, hdr, sort="Random")
                        songs = random.sample(all_songs, min(count, len(all_songs)))
                elif mode == "genre":
                    filters = music_data.get("filters", {})
                    songs = find_songs(user_id=user_id, filters=filters, hdr=hdr)

                if songs:
                    master_items_list.extend(songs)
                    log_messages.append(f"Block {i} (Music): Added {len(songs)} songs.")

            except Exception as e:
                log_messages.append(f"Block {i} (Music): Failed with error - {e}")
                logging.error(f"Error processing music block {i}: {e}", exc_info=True)
    return master_items_list


def format_items_for_preview(items: List[Dict]) -> List[Dict]:
    """Formats a list of full item objects for the preview modal."""
    formatted_list = []
    for item in items:
        item_type = item.get("Type")
        name = item.get("Name", "Unknown")
        context = ""

        if item_type == "Episode":
            s_num = item.get("ParentIndexNumber", 0)
            e_num = item.get("IndexNumber", 0)
            context = f"{item.get('SeriesName', 'Unknown Series')} S{s_num:02d}E{e_num:02d}"
        elif item_type == "Movie":
            year = item.get("ProductionYear")
            if year:
                name = f"{name} ({year})"
        elif item_type == "Audio":
            artist = ""
            if item.get("ArtistItems"):
                artist = ", ".join([a["Name"] for a in item["ArtistItems"]])
            album = item.get("Album", "")
            if artist and album:
                context = f"{artist} — {album}"
            elif artist:
                context = artist

        formatted_list.append({"name": name, "context": context})

    return formatted_list


def create_mixed_playlist(user_id: str, playlist_name: str,
                          blocks: List[Dict], hdr: Dict[str, str]) -> Dict:
    """Builds a playlist from a list of TV, Movie, and/or Music blocks."""
    log_messages: List[str] = []
    master_items = generate_items_from_blocks(user_id, blocks, hdr, log_messages)
    master_item_ids = [item["Id"] for item in master_items]

    if not master_item_ids:
        log_messages.append("No items were found to add. Playlist not created.")
        return {"status": "error", "log": log_messages}

    new_item_id = create_playlist(name=playlist_name, user_id=user_id, ids=master_item_ids, hdr=hdr, log=log_messages)
    return {"status": "ok" if new_item_id else "error", "log": log_messages, "new_item_id": new_item_id}


def add_items_to_playlist(user_id: str, playlist_id: str,
                          blocks: List[Dict], hdr: Dict[str, str]) -> Dict:
    """Builds a list of items from blocks and adds them to an existing playlist."""
    log_messages: List[str] = []
    master_items = generate_items_from_blocks(user_id, blocks, hdr, log_messages)
    master_item_ids = [item["Id"] for item in master_items]

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

    if success:
        return {"status": "ok", "log": log_messages}
    else:
        return {"status": "error", "log": log_messages}