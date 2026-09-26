"""
app/builder.py -  module for constructing mixed playlists from content blocks.
"""

import logging
import random
import uuid
from datetime import datetime, timedelta
from typing import Dict, List, Any, Optional
from itertools import zip_longest

from . import client
from .media_client import media_operation
from . import items as items_api
from .movies import find_movies, matches_movie_constraints, normalize_movie_filters
from .music import find_songs, get_songs_by_album, get_songs_by_artist
from .tv import episodes, get_first_unwatched_episode, get_random_unwatched_episode, get_first_available_episode, series_id
from . import build_history


def _process_tv_block(block: Dict[str, Any], user_id: str, media: client.MediaClient, log_messages: List[str], block_index: int) -> List[Dict[str, Any]]:
    """Process a TV block: resolve shows to episodes with optional interleave."""
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
                    sid = series_id(show_name, media)

                if not sid:
                    continue

                s = raw_show.get("season")
                e = raw_show.get("episode")
                is_unwatched = raw_show.get("unwatched", False)

                # Fix: If the intent is unwatched, ignore any cached S/E numbers from the preset
                # and dynamically fetch the true next unwatched episode right now.
                if is_unwatched:
                    ep_info = get_first_unwatched_episode(sid, user_id, media)
                    if ep_info:
                        s = ep_info.get("ParentIndexNumber")
                        e = ep_info.get("IndexNumber")
                    else:
                        s, e = None, None
                else:
                    if s is not None: s = int(s)
                    if e is not None: e = int(e)

                # Fallback if we still don't have a starting point
                if s is None or e is None:
                    first_ep = get_first_available_episode(sid, user_id, media)
                    if first_ep:
                        s = first_ep.get("ParentIndexNumber")
                        e = first_ep.get("IndexNumber")
                    else:
                        s, e = 1, 1

                eps = episodes(sid, s, e, count, media, user_id=user_id, only_unwatched=is_unwatched)

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


def _process_movie_block(block: Dict[str, Any], user_id: str, media: client.MediaClient, log_messages: List[str], block_index: int) -> List[Dict[str, Any]]:
    """Process a movie block: resolve by explicit IDs or general filters."""
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

                resolved_items = find_movies(user_id=user_id, filters=id_filters, media=media)
                item_map = {item.get("Id"): item for item in resolved_items}
                for rid in id_list:
                    if rid in item_map:
                        items.append(item_map[rid])
        else:
            items = find_movies(user_id=user_id, filters=filters, media=media)

    except Exception as e:
        logging.error(f"Error processing Movie block {block_index}: {e}", exc_info=True)
    return items


def _process_mirror_block(block: Dict[str, Any], user_id: str, media: client.MediaClient, log_messages: List[str], block_index: int) -> List[Dict[str, Any]]:
    """Process an Echo (Mirror) block: AI-similarity-based content sampling."""
    items = []
    try:
        from .ai.vector_store import search_by_composite_similarity

        filters = block.get("filters", {})

        if "ids" in filters and filters["ids"]:
            target_ids = filters["ids"]
            resolved_map = {}

            resolved_movies = find_movies(user_id=user_id, filters={"ids": target_ids}, media=media)
            for m in resolved_movies:
                resolved_map[m["Id"]] = m

            remaining_ids = [tid for tid in target_ids if tid not in resolved_map]
            for rid in remaining_ids:
                item_info = items_api.get_item_children(user_id, rid, media) # Fallback resolving
                if item_info:
                    resolved_map[rid] = item_info[0]
                else: # Try direct get if not children
                    item_resp = media.get(f"/Users/{user_id}/Items/{rid}",
                                                    params={"Fields": "RunTimeTicks"}, timeout=5)
                    if item_resp.ok:
                        resolved_map[rid] = item_resp.json()

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
            album_ids = []

            for match in sampled_matches:
                m_type = match.get("Type")
                m_id = match.get("Id")
                if m_type == "Movie":
                    movie_ids.append(m_id)
                elif m_type == "Series":
                    series_ids.append(m_id)
                elif m_type in ("MusicAlbum", "Album"):
                    album_ids.append(m_id)

            if movie_ids:
                movie_filter_dict = {"ids": movie_ids}
                for k in ("min_runtime_minutes", "max_runtime_minutes", "min_community_rating", "favorites_only", "allowed_content_ratings", "audio_languages", "subtitle_languages"):
                    if k in filters:
                        movie_filter_dict[k] = filters[k]
                resolved_movies = find_movies(user_id=user_id, filters=movie_filter_dict, media=media)
                items.extend(resolved_movies)

            for sid in series_ids:
                next_ep = get_first_unwatched_episode(sid, user_id, media)
                if not next_ep:
                    next_ep = get_first_available_episode(sid, user_id, media)
                if next_ep:
                    items.append(next_ep)

            for aid in album_ids:
                try:
                    album_songs = get_songs_by_album(aid, media)
                    if album_songs:
                        items.extend(album_songs)
                except Exception as music_err:
                    logging.warning(f"Failed to expand album {aid} in Echo block: {music_err}")

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
                        m_list = find_movies(user_id=user_id, filters={"ids": [sid]}, media=media)
                        if m_list: master_items.append(m_list[0])
                    elif m_type == "Series":
                        next_ep = get_first_unwatched_episode(sid, user_id, media)
                        if not next_ep:
                            next_ep = get_first_available_episode(sid, user_id, media)
                        if next_ep: master_items.append(next_ep)

            items = master_items + items

    except Exception as e:
        logging.error(f"Error processing Echo block {block_index}: {e}", exc_info=True)
    return items


def _process_music_block(block: Dict[str, Any], user_id: str, media: client.MediaClient, log_messages: List[str], block_index: int) -> List[Dict[str, Any]]:
    """Process a music block: resolve songs by album, artist, or genre."""
    items = []
    try:
        music_data = block.get("music", {})
        mode = music_data.get("mode")
        songs = []

        if mode == "album":
            if album_id := music_data.get("albumId"):
                songs = get_songs_by_album(album_id, media)
        elif mode == "artist_top":
            if artist_id := music_data.get("artistId"):
                count = int(music_data.get("count", 10))
                songs = get_songs_by_artist(artist_id, media, sort="Top", limit=count)
        elif mode == "artist_random":
            if artist_id := music_data.get("artistId"):
                count = int(music_data.get("count", 10))
                all_songs = get_songs_by_artist(artist_id, media, sort="Random")
                songs = random.sample(all_songs, min(count, len(all_songs))) if all_songs else []
        elif mode == "genre":
            filters = music_data.get("filters", {})
            songs = find_songs(user_id=user_id, filters=filters, media=media)

        if songs:
            items.extend(songs)

    except Exception as e:
        logging.error(f"Error processing music block {block_index}: {e}", exc_info=True)

    return items


def _process_curated_block(block: Dict[str, Any], user_id: str, media: client.MediaClient, log_messages: List[str], block_index: int) -> List[Dict[str, Any]]:
    """Process a curated block: combine explicit movies and TV shows with controlled ordering."""
    items = []
    try:
        # Snapshotted bypass
        filters = block.get("filters", {})
        if block.get("isSnapshot") and filters.get("ids"):
            return _process_movie_block({"filters": {"ids": filters["ids"]}}, user_id, media, log_messages, block_index)

        movies_list = []
        movie_ids = [m.get("Id") for m in block.get("movies", []) if m.get("Id")]
        if movie_ids:
            resolved_movies = find_movies(user_id=user_id, filters={"ids": movie_ids}, media=media)
            # Maintain explicit order
            movie_map = {m["Id"]: m for m in resolved_movies}
            movies_list = [movie_map[mid] for mid in movie_ids if mid in movie_map]

        tv_list = []
        shows = block.get("shows", [])
        if shows:
            groups = []
            for raw_show in shows:
                show_name = raw_show.get("name")
                sid = items_api.sanitize_id(raw_show.get("id"))
                if not sid and show_name:
                    sid = series_id(show_name, media)
                if not sid: continue

                s = raw_show.get("season")
                e = raw_show.get("episode")
                is_unwatched = raw_show.get("unwatched", True)
                count = int(raw_show.get("count", 1))

                # Fix: Same logic applied here for Curated Blocks
                if is_unwatched:
                    ep_info = get_first_unwatched_episode(sid, user_id, media)
                    if ep_info:
                        s, e = ep_info.get("ParentIndexNumber"), ep_info.get("IndexNumber")
                    else:
                        s, e = None, None
                else:
                    if s is not None: s = int(s)
                    if e is not None: e = int(e)

                if s is None or e is None:
                    first_ep = get_first_available_episode(sid, user_id, media)
                    if first_ep:
                        s, e = first_ep.get("ParentIndexNumber"), first_ep.get("IndexNumber")
                    else:
                        s, e = 1, 1

                eps = episodes(sid, s, e, count, media, user_id=user_id, only_unwatched=is_unwatched)
                if eps: groups.append(eps)

            if block.get("tv_interleave", False):
                for bundle in zip_longest(*groups):
                    tv_list.extend(ep for ep in bundle if ep is not None)
            else:
                for group in groups:
                    tv_list.extend(group)

        # Merge according to block rule
        order = block.get("playback_order", "movies_first")
        if order == "movies_first":
            items = movies_list + tv_list
        elif order == "tv_first":
            items = tv_list + movies_list
        elif order == "interleaved":
            for m, t in zip_longest(movies_list, tv_list):
                if m: items.append(m)
                if t: items.append(t)
        else:
            items = movies_list + tv_list

    except Exception as e:
        logging.error(f"Error processing Curated block {block_index}: {e}", exc_info=True)
    return items


class MixResolutionResult:
    def __init__(self, rows: Optional[List[Dict[str, Any]]] = None, warnings: Optional[List[str]] = None, log: Optional[List[str]] = None):
        self.rows = rows or []
        self.warnings = warnings or []
        self.log = log or []
        self.total_duration_ticks = sum(int(r.get("RunTimeTicks") or r.get("runtime_ticks") or 0) for r in self.rows)
        self.total_count = len(self.rows)

    @property
    def total_items(self) -> int:
        return self.total_count

    @property
    def total_duration_minutes(self) -> int:
        return int(self.total_duration_ticks / 10_000_000 / 60)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "rows": self.rows,
            "data": self.rows,
            "warnings": self.warnings,
            "log": self.log,
            "total_count": self.total_count,
            "total_duration_ticks": self.total_duration_ticks,
            "total_duration_formatted": format_duration_ticks(self.total_duration_ticks)
        }


def format_item_for_display(item: Dict[str, Any]) -> Dict[str, Any]:
    """Format item with title, context, runtime, and unique occurrence identity."""
    item_id = item.get("Id") or item.get("media_id")
    item_type = item.get("Type") or item.get("media_type") or "Unknown"
    name = item.get("Name") or item.get("name") or "Unknown"
    context = item.get("context") or ""

    if not context:
        if item_type == "Episode":
            s_num = item.get("ParentIndexNumber", 0)
            e_num = item.get("IndexNumber", 0)
            series_name = item.get('SeriesName', 'Unknown Series')
            context = f"{series_name} S{s_num:02d}E{e_num:02d}"
        elif item_type == "Movie":
            if year := item.get("ProductionYear"):
                name = f"{name} ({year})"
        elif item_type == "Audio":
            artist = ", ".join([a["Name"] for a in item.get("ArtistItems", []) if isinstance(a, dict) and a.get("Name")])
            album = item.get("Album", "")
            if artist and album:
                context = f"{artist} — {album}"
            elif artist:
                context = artist
    elif item_type == "Movie" and "(" not in name:
        if year := item.get("ProductionYear"):
            name = f"{name} ({year})"

    runtime_ticks = item.get("RunTimeTicks") or item.get("runtime_ticks") or 0

    return {
        "entry_id": item.get("entry_id") or uuid.uuid4().hex,
        "Id": item_id,
        "media_id": str(item_id) if item_id else "",
        "Name": name,
        "name": name,
        "context": context,
        "Type": item_type,
        "media_type": item_type,
        "RunTimeTicks": runtime_ticks,
        "runtime_ticks": runtime_ticks,
        "source_block_id": item.get("source_block_id") or "",
        "source_series_id": item.get("SeriesId") or item.get("source_series_id") or "",
        "selection_reason": item.get("selection_reason") or "Matched block filter criteria",
        "raw_item": item.get("raw_item") or item
    }


def apply_sequencing(
    rows_by_block: Dict[str, List[Dict[str, Any]]],
    block_order: List[str],
    seq_opt: Optional[Dict[str, Any]]
) -> List[Dict[str, Any]]:
    """Applies pure sequencing rules: sequential, round-robin, or weighted pattern."""
    if not seq_opt:
        ordered = []
        for b_id in block_order:
            ordered.extend(rows_by_block.get(b_id, []))
        return ordered

    mode = seq_opt.get("mode", "sequential")
    exhaustion = seq_opt.get("exhaustion_policy", "continue")

    if mode == "sequential":
        ordered = []
        for b_id in block_order:
            ordered.extend(rows_by_block.get(b_id, []))
        return ordered

    if mode in ("round_robin", "interleave"):
        queues = {b: list(rows_by_block.get(b, [])) for b in block_order}
        active_blocks = [b for b in block_order if queues[b]]
        ordered = []
        while active_blocks:
            to_remove = []
            for b in list(active_blocks):
                if queues[b]:
                    ordered.append(queues[b].pop(0))
                if not queues[b]:
                    to_remove.append(b)
            if exhaustion == "stop" and to_remove:
                break
            for b in to_remove:
                if b in active_blocks:
                    active_blocks.remove(b)
        return ordered

    if mode in ("weighted", "pattern") or seq_opt.get("pattern"):
        pattern = seq_opt.get("pattern") or []
        if not pattern:
            pattern = [{"block_id": b, "take": 1} for b in block_order]

        queues = {b: list(rows_by_block.get(b, [])) for b in block_order}
        ordered = []
        made_progress = True

        while made_progress:
            made_progress = False
            for step in pattern:
                b = step.get("block_id")
                take = int(step.get("take", 1))
                if b not in queues or not queues[b]:
                    if exhaustion == "stop":
                        made_progress = False
                        break
                    continue
                for _ in range(take):
                    if queues[b]:
                        ordered.append(queues[b].pop(0))
                        made_progress = True
                    else:
                        break

        if exhaustion == "continue":
            for b in block_order:
                if b in queues and queues[b]:
                    ordered.extend(queues[b])

        return ordered

    ordered = []
    for b_id in block_order:
        ordered.extend(rows_by_block.get(b_id, []))
    return ordered


def apply_duplicate_and_freshness(
    rows: List[Dict[str, Any]],
    dup_opt: Optional[Dict[str, Any]],
    freshness_opt: Optional[Dict[str, Any]],
    connection_id: str,
    warnings: List[str],
    series_key: Optional[str] = None
) -> List[Dict[str, Any]]:
    """Applies cross-block duplicate suppression, franchise caps, and freshness cooldowns."""
    dup_opt = dup_opt or {}
    freshness_opt = freshness_opt or {}

    dup_mode = dup_opt.get("mode", "suppress")
    max_franchise = int(dup_opt.get("max_movies_per_franchise", 0) or 0)

    # 1. Freshness exclusion
    history_builds = int(freshness_opt.get("last_successful_builds", 0) or 0)
    history_scope = freshness_opt.get("history_scope", "series")
    exhaustion_policy = freshness_opt.get("exhaustion_policy", "shorter")

    history_media_ids: Set[str] = set()
    if history_builds > 0 and connection_id:
        history_media_ids = build_history.get_history_media_ids(
            connection_id=connection_id,
            scope=history_scope,
            last_n_builds=history_builds,
            series_key=series_key
        )

    watched_within_days = int(freshness_opt.get("watched_within_days", 0) or 0)
    cutoff_dt = None
    if watched_within_days > 0:
        cutoff_dt = datetime.now(timezone.utc) - timedelta(days=watched_within_days)

    filtered_candidates = []
    excluded_by_history = []

    for r in rows:
        mid = str(r.get("media_id") or r.get("Id") or "")
        raw = r.get("raw_item") or {}

        # Check watched within days
        if cutoff_dt:
            last_played = (raw.get("UserData") or {}).get("LastPlayedDate")
            if last_played:
                try:
                    # Emby/Jellyfin ISO timestamps
                    lp_dt = datetime.fromisoformat(last_played.replace("Z", "+00:00"))
                    if lp_dt >= cutoff_dt:
                        continue
                except Exception:
                    pass

        # Check history cooldown
        if history_media_ids and mid in history_media_ids:
            excluded_by_history.append(r)
            continue

        filtered_candidates.append(r)

    # Exhaustion handling
    if not filtered_candidates and excluded_by_history:
        if exhaustion_policy == "relax_cooldown":
            warnings.append("Recommendation cooldown relaxed due to candidate exhaustion.")
            filtered_candidates = excluded_by_history
        else:
            warnings.append(f"Excluded {len(excluded_by_history)} items due to recent build history cooldown.")

    # 2. Duplicate suppression and franchise caps
    seen_ids = set()
    franchise_counts: Dict[str, int] = {}
    result = []

    for r in filtered_candidates:
        mid = str(r.get("media_id") or r.get("Id") or "")
        if dup_mode == "suppress":
            if mid in seen_ids:
                continue
            seen_ids.add(mid)

        if max_franchise > 0 and (r.get("Type") == "Movie" or r.get("media_type") == "Movie"):
            raw = r.get("raw_item") or {}
            franchise = raw.get("SeriesName") or raw.get("CollectionName") or ""
            if not franchise and ":" in r.get("Name", ""):
                franchise = r.get("Name", "").split(":")[0]
            if franchise:
                f_key = franchise.strip().lower()
                if franchise_counts.get(f_key, 0) >= max_franchise:
                    continue
                franchise_counts[f_key] = franchise_counts.get(f_key, 0) + 1

        result.append(r)

    return result


def apply_runtime_budget(
    rows: List[Dict[str, Any]],
    budget_opt: Optional[Dict[str, Any]],
    warnings: List[str]
) -> List[Dict[str, Any]]:
    """Applies whole-mix time budget limits."""
    if not budget_opt:
        return rows

    mode = budget_opt.get("mode", "off")
    if mode == "off":
        return rows

    target_minutes = int(budget_opt.get("target_minutes", 0) or 0)
    allowed_overrun = int(budget_opt.get("allowed_overrun_minutes", 15) or 15)

    if mode == "end_time":
        end_time_str = budget_opt.get("end_local_time")
        if end_time_str:
            try:
                now = datetime.now()
                parts = [int(p) for p in end_time_str.split(":")]
                target_dt = now.replace(hour=parts[0], minute=parts[1], second=0, microsecond=0)
                if target_dt <= now:
                    target_dt += timedelta(days=1)
                target_minutes = int((target_dt - now).total_seconds() / 60)
            except Exception as e:
                logging.warning(f"Could not parse end_local_time '{end_time_str}': {e}")

    if target_minutes <= 0:
        return rows

    max_allowed_ticks = (target_minutes + allowed_overrun) * 600_000_000
    accumulated_ticks = 0
    accepted_rows = []

    for r in rows:
        ticks = int(r.get("RunTimeTicks") or r.get("runtime_ticks") or 0)
        if ticks <= 0:
            accepted_rows.append(r)
            continue
        if accumulated_ticks + ticks <= max_allowed_ticks:
            accepted_rows.append(r)
            accumulated_ticks += ticks
        else:
            warnings.append(
                f"Excluded '{r.get('Name') or r.get('name')}' to respect runtime budget of {target_minutes}m (total reached {accumulated_ticks // 600_000_000}m)"
            )

    return accepted_rows


@media_operation
def resolve_mix(
    user_id: str,
    blocks: List[Dict[str, Any]],
    media: client.MediaClient,
    log_messages: Optional[List[str]] = None,
    mix_options: Optional[Dict[str, Any]] = None,
    series_key: Optional[str] = None
) -> MixResolutionResult:
    """Core transformation engine converting blocks + mix_options into resolved rows with provenance."""
    media.require_user(user_id)
    if log_messages is None:
        log_messages = []
    warnings: List[str] = []

    mix_opt = mix_options or {}
    freshness_opt = mix_opt.get("freshness") or {}
    dup_opt = mix_opt.get("duplicate_policy") or {}
    seq_opt = mix_opt.get("sequencing") or {}
    budget_opt = mix_opt.get("runtime_budget") or {}

    rows_by_block: Dict[str, List[Dict[str, Any]]] = {}
    block_order: List[str] = []

    for i, block in enumerate(blocks, 1):
        block_id = block.get("block_id") or block.get("_uid") or f"block_{i}"
        block_order.append(block_id)
        block_type = block.get("type")

        raw_items: List[Dict[str, Any]] = []
        if block_type == "tv" or (block_type == "vibe" and block.get("vibe_type") == "tv"):
            raw_items = _process_tv_block(block, user_id, media, log_messages, i)
        elif block_type == "movie" or (block_type == "vibe" and block.get("vibe_type") == "movie"):
            raw_items = _process_movie_block(block, user_id, media, log_messages, i)
        elif block_type == "music":
            raw_items = _process_music_block(block, user_id, media, log_messages, i)
        elif block_type == "mirror" or block_type == "echo":
            raw_items = _process_mirror_block(block, user_id, media, log_messages, i)
        elif block_type == "curated":
            raw_items = _process_curated_block(block, user_id, media, log_messages, i)

        block_rows = []
        for item in raw_items:
            formatted = format_item_for_display(item)
            formatted["source_block_id"] = block_id
            formatted["raw_item"] = item
            formatted["selection_reason"] = f"Resolved from block '{block.get('title') or block_type}'"
            block_rows.append(formatted)

        rows_by_block[block_id] = block_rows

    ordered_rows = apply_sequencing(rows_by_block, block_order, seq_opt)
    ordered_rows = apply_duplicate_and_freshness(
        ordered_rows, dup_opt, freshness_opt, media.connection.id, warnings, series_key
    )
    ordered_rows = apply_runtime_budget(ordered_rows, budget_opt, warnings)

    return MixResolutionResult(rows=ordered_rows, warnings=warnings, log=log_messages)


@media_operation
def generate_items_from_blocks(
    user_id: str,
    blocks: List[Dict[str, Any]],
    media: client.MediaClient,
    log_messages: List[str],
    mix_options: Optional[Dict[str, Any]] = None
) -> List[Dict[str, Any]]:
    """Dispatch block definitions to their respective processors with provenance resolution."""
    resolution = resolve_mix(user_id=user_id, blocks=blocks, media=media, log_messages=log_messages, mix_options=mix_options)
    return [r.get("raw_item") or r for r in resolution.rows]


def format_items_for_preview(items: List[Dict[str, Any]]) -> List[Dict[str, str]]:
    """Format items into a display-friendly preview with episode numbers, years, and artist context."""
    formatted_list = []
    for item in items:
        formatted = format_item_for_display(item)
        formatted_list.append({
            "Id": formatted["Id"],
            "media_id": formatted["media_id"],
            "entry_id": formatted["entry_id"],
            "name": formatted["Name"],
            "Name": formatted["Name"],
            "context": formatted["context"],
            "Type": formatted["Type"],
            "source_block_id": formatted["source_block_id"]
        })
    return formatted_list


def format_duration_ticks(ticks: int) -> str:
    """Formats a RunTimeTicks value (100-nanosecond units) as a human-readable duration, e.g. '3h 15m'."""
    if not ticks:
        return "0m"

    total_minutes = int(ticks / 10_000_000 / 60)
    hours, minutes = divmod(total_minutes, 60)

    if hours and minutes:
        return f"{hours}h {minutes}m"
    if hours:
        return f"{hours}h"
    return f"{minutes}m"


def create_mixed_playlist(
    user_id: str,
    playlist_name: str,
    blocks: List[Dict[str, Any]],
    media: client.MediaClient,
    mix_options: Optional[Dict[str, Any]] = None,
    trigger_source: str = "manual",
    schedule_id: Optional[str] = None,
    preset_id: Optional[str] = None
) -> Dict[str, Any]:
    """Create a new playlist from resolved block items, recording build history."""
    log_messages: List[str] = []
    run_id = build_history.record_build_start(
        connection_id=media.connection.id,
        operation="playlist",
        user_id=user_id,
        trigger_source=trigger_source,
        schedule_id=schedule_id,
        preset_id=preset_id,
        series_key=preset_id or schedule_id or playlist_name,
        definition_snapshot={"blocks": blocks, "mix_options": mix_options}
    )

    resolution = resolve_mix(
        user_id=user_id,
        blocks=blocks,
        media=media,
        log_messages=log_messages,
        mix_options=mix_options,
        series_key=preset_id or schedule_id or playlist_name
    )
    master_item_ids = [item.get("media_id") or item.get("Id") for item in resolution.rows if (item.get("media_id") or item.get("Id"))]

    if not master_item_ids:
        log_messages.append("No items were found to add. Playlist not created.")
        build_history.record_build_finish(run_id=run_id, output_id=None, outcome="error", summary="No items found to add", rows=[])
        return {"status": "error", "log": log_messages, "warnings": resolution.warnings}

    new_item_id = items_api.create_playlist(name=playlist_name, user_id=user_id, ids=master_item_ids, media=media, log=log_messages)
    outcome = "ok" if new_item_id else "error"
    build_history.record_build_finish(
        run_id=run_id,
        output_id=new_item_id,
        outcome=outcome,
        summary=f"Created playlist '{playlist_name}' with {len(resolution.rows)} items",
        rows=resolution.rows
    )

    return {
        "status": outcome,
        "log": log_messages,
        "warnings": resolution.warnings,
        "new_item_id": new_item_id,
        "run_id": run_id
    }


def add_items_to_playlist(
    user_id: str,
    playlist_id: str,
    blocks: List[Dict[str, Any]],
    media: client.MediaClient,
    mix_options: Optional[Dict[str, Any]] = None,
    trigger_source: str = "manual",
    schedule_id: Optional[str] = None,
    preset_id: Optional[str] = None
) -> Dict[str, Any]:
    """Add items from block definitions to an existing playlist, recording build history."""
    log_messages: List[str] = []
    run_id = build_history.record_build_start(
        connection_id=media.connection.id,
        operation="playlist_append",
        user_id=user_id,
        trigger_source=trigger_source,
        schedule_id=schedule_id,
        preset_id=preset_id,
        series_key=preset_id or schedule_id or playlist_id,
        definition_snapshot={"blocks": blocks, "mix_options": mix_options}
    )

    resolution = resolve_mix(
        user_id=user_id,
        blocks=blocks,
        media=media,
        log_messages=log_messages,
        mix_options=mix_options,
        series_key=preset_id or schedule_id or playlist_id
    )
    master_item_ids = [item.get("media_id") or item.get("Id") for item in resolution.rows if (item.get("media_id") or item.get("Id"))]

    if not master_item_ids:
        log_messages.append("No items were found to add. No changes made.")
        build_history.record_build_finish(run_id=run_id, output_id=playlist_id, outcome="error", summary="No items found to add", rows=[])
        return {"status": "error", "log": log_messages, "warnings": resolution.warnings}

    success = items_api.add_items_to_playlist_by_ids(
        playlist_id=playlist_id,
        item_ids=master_item_ids,
        user_id=user_id,
        media=media,
        log=log_messages
    )

    outcome = "ok" if success else "error"
    build_history.record_build_finish(
        run_id=run_id,
        output_id=playlist_id,
        outcome=outcome,
        summary=f"Appended {len(resolution.rows)} items to playlist {playlist_id}",
        rows=resolution.rows
    )

    return {
        "status": outcome,
        "log": log_messages,
        "warnings": resolution.warnings,
        "run_id": run_id
    }
