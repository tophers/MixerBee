"""
routers/library.py – APIRouter
"""

import logging
from typing import Dict, Any, List
from fastapi import APIRouter, HTTPException, Depends, Body
from fastapi.responses import JSONResponse
from pydantic import BaseModel

import app as core
import models
import app_state
from app import ai_policy
from app.cache import get_library_data
from app.ai.vector_store import calculate_library_iq, get_discovery_tags
from .dependencies import (get_current_auth_headers, media_for_user, require_collection_permission,
                           require_generative_ai)

router = APIRouter()

# start_enrichment rechecks policy at the service layer, and RuntimeError is already
# mapped to a 409 "already running" below. AINotConfigured subclasses RuntimeError, so
# these have to be caught ahead of it or a missing setup reads as a busy worker.
ai_policy_errors = (ai_policy.AIDisabled, ai_policy.AINotConfigured)


def policy_http(exc):
    status = 403 if isinstance(exc, ai_policy.AIDisabled) else 409
    reason = ai_policy.REASON_DISABLED if status == 403 else "ai_not_configured"
    return HTTPException(status, {"detail": str(exc), "reason": reason})

@router.get("/api/library_data")
def api_library_data(auth_deps: dict = Depends(get_current_auth_headers)) -> Dict[str, Any]:
    """Returns a consolidated dictionary of all necessary library data for the UI."""
    cached_data = get_library_data(auth_deps["media"])
    if not cached_data:
        raise HTTPException(
            status_code=503,
            detail="Library data is not yet available. The cache may still be warming up. Please try again in a moment."
        )
    return cached_data

@router.get("/api/library/iq")
def api_library_iq(auth_deps: dict = Depends(get_current_auth_headers)) -> JSONResponse:
    """Enrichment progress. Belongs to the enrichment feature, so it follows its policy.

    Reported as unavailable without opening the vector store, so a disabled account
    never pays a Chroma read for a panel it cannot see.
    """
    if not ai_policy.generative_available(auth_deps["connection_id"]):
        return JSONResponse(content={"total": 0, "enriched": 0, "available": False},
                            headers={"Cache-Control": "no-store"})
    stats = calculate_library_iq(media=auth_deps["media"])
    return JSONResponse(
        content=stats,
        headers={
            "Cache-Control": "no-cache, no-store, must-revalidate",
            "Pragma": "no-cache",
            "Expires": "0",
        }
    )

@router.get("/api/library/mood_discovery")
def api_mood_discovery(auth_deps: dict = Depends(get_current_auth_headers)):
    """Prompt starters built from enrichment tags, so they belong to the AI generator.

    Returns an empty pool rather than an error: these are decorative suggestions and a
    hidden generator has nothing to show them in.
    """
    if not ai_policy.generative_available(auth_deps["connection_id"]):
        return {"status": "ok", "tags": [], "available": False}
    tags = get_discovery_tags(limit=60, media=auth_deps["media"])
    return {"status": "ok", "tags": tags}

@router.get("/api/default_user")
def api_default_user(auth_deps: dict = Depends(get_current_auth_headers)) -> Dict[str, Any]:
    media = auth_deps["media"]
    return {"id": media.user_id, "name": media.connection.username,
            "connection_id": auth_deps["connection_id"],
            "can_manage_collections": media.can_manage_collections()}

@router.get("/api/episode_lookup")
def api_episode_lookup(series_id: str, season: int, episode: int, auth_deps: dict = Depends(get_current_auth_headers)) -> Dict[str, Any]:
    ep_data = core.get_specific_episode(series_id, season, episode, auth_deps["media"])
    if ep_data:
        return {
            "name": ep_data.get("Name", "Unknown Episode"),
            "season": season,
            "episode": episode
        }
    
    if season == 1 and episode == 1:
        first_ep = core.get_first_available_episode(series_id, auth_deps["login_uid"], auth_deps["media"])
        if first_ep:
            return {
                "name": first_ep.get("Name", "Unknown Episode"),
                "season": first_ep.get("ParentIndexNumber"),
                "episode": first_ep.get("IndexNumber")
            }

    raise HTTPException(status_code=404, detail="Specific episode not found.")

@router.get("/api/shows/{series_id}/first_unwatched")
def api_get_first_unwatched(series_id: str, user_id: str, auth_deps: dict = Depends(get_current_auth_headers)) -> Dict[str, Any]:
    media = media_for_user(auth_deps, user_id)
    ep_data = core.get_first_unwatched_episode(series_id, user_id, media)
    if not ep_data:
        raise HTTPException(status_code=404, detail="Could not find an unwatched episode.")
    return ep_data

@router.get("/api/shows/{series_id}/random_unwatched")
def api_get_random_unwatched(series_id: str, user_id: str, auth_deps: dict = Depends(get_current_auth_headers)) -> Dict[str, Any]:
    media = media_for_user(auth_deps, user_id)
    ep_data = core.get_random_unwatched_episode(series_id, user_id, media)
    if not ep_data:
        raise HTTPException(status_code=404, detail="Could not find a random episode.")
    return ep_data

@router.get("/api/users/{user_id}/playlists")
def api_get_playlists(user_id: str, auth_deps: dict = Depends(get_current_auth_headers)) -> List[Dict[str, Any]]:
    media = media_for_user(auth_deps, user_id)
    return core.get_playlists(user_id, media)

@router.get("/api/music/artists/{artist_id}/albums")
def api_music_artist_albums(artist_id: str, auth_deps: dict = Depends(get_current_auth_headers)) -> List[Dict[str, Any]]:
    return core.get_albums_by_artist(artist_id, auth_deps["media"])

@router.get("/api/people")
def api_get_people(name: str = "", auth_deps: dict = Depends(get_current_auth_headers)) -> List[Dict[str, str]]:
    """Searches for people (actors, directors, etc.) by name."""
    return core.get_people(name, auth_deps["media"])

@router.get("/api/studios")
def api_get_studios(name: str = "", auth_deps: dict = Depends(get_current_auth_headers)) -> List[Dict[str, str]]:
    """Searches for studios by name using the cached library data."""
    library_data = get_library_data(auth_deps["media"])
    return core.get_studios(name, library_data)

@router.get("/api/media/search")
def api_search_media(query: str, auth_deps: dict = Depends(get_current_auth_headers)) -> List[Dict[str, Any]]:
    """Global search for media (movies/shows/collections) using indexed server search."""
    search_term = query.strip()
    if not search_term:
        return []

    user_id = auth_deps["login_uid"]
    media = media_for_user(auth_deps, user_id)
    results = []

    # 1. Search Collections first
    try:
        collections = core.get_collections(user_id, media)
        for c in collections:
            if search_term.lower() in c.get("Name", "").lower():
                results.append({
                    "Id": c.get("Id"),
                    "Name": c.get("Name"),
                    "Year": "",
                    "Type": "Collection"
                })
    except Exception as ce:
        logging.warning(f"Failed to fetch collections for search: {ce}")

    # 2. Native indexed server search for Movies and TV Series
    try:
        params = {
            "SearchTerm": search_term,
            "IncludeItemTypes": "Movie,Series",
            "Recursive": "true",
            "Limit": 20,
            "Fields": "ProductionYear,Type"
        }
        r = auth_deps["media"].get(
            f"/Users/{user_id}/Items",
            params=params,
            timeout=10
        )
        r.raise_for_status()
        items = r.json().get("Items", [])

        for it in items:
            it_type = it.get("Type", "")
            results.append({
                "Id": it.get("Id"),
                "Name": it.get("Name"),
                "Year": it.get("ProductionYear", ""),
                "Type": it_type
            })
    except HTTPException:
        raise
    except Exception as e:
        logging.error(f"Native media search failed: {e}")

    return results

@router.get("/api/music/random_artist")
def api_get_random_artist(auth_deps: dict = Depends(get_current_auth_headers)) -> Dict[str, str]:
    artist = core.get_random_artist(auth_deps["media"])
    if not artist:
        raise HTTPException(status_code=404, detail="No artists found in the library.")
    return artist

@router.get("/api/music/random_album")
def api_get_random_album(auth_deps: dict = Depends(get_current_auth_headers)) -> Dict[str, str]:
    album = core.get_random_album(auth_deps["media"])
    if not album:
        raise HTTPException(status_code=404, detail="No albums found in the library.")
    return album

@router.get("/api/manageable_items")
def api_manageable_items(user_id: str, auth_deps: dict = Depends(get_current_auth_headers)) -> JSONResponse:
    media = media_for_user(auth_deps, user_id)
    items = core.get_manageable_items(user_id, media)
    cache_headers = {
        "Cache-Control": "no-cache, no-store, must-revalidate",
        "Pragma": "no-cache",
        "Expires": "0",
    }
    return JSONResponse(content=items, headers=cache_headers)

@router.get("/api/items/{item_id}/children")
def api_get_item_children(item_id: str, user_id: str, auth_deps: dict = Depends(get_current_auth_headers)) -> List[Dict[str, Any]]:
    media = media_for_user(auth_deps, user_id)
    try:
        return core.get_item_children(user_id, item_id, media)
    except HTTPException:
        raise
    except Exception as e:
        logging.error(f"Error fetching children for item {item_id}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/api/items/{item_id}/reorder")
def api_reorder_item_children(item_id: str, req: models.ReorderItemsRequest, auth_deps: dict = Depends(get_current_auth_headers)):
    """
    Reorders children of a playlist or collection. 
    It clears existing items and re-adds them in the new order.
    """
    media = media_for_user(auth_deps, req.user_id)
    log = []
    
    try:
        params = {"Ids": item_id, "UserId": req.user_id}
        r = media.get(f"/Users/{req.user_id}/Items", params=params, timeout=10)
        r.raise_for_status()
        items = r.json().get("Items", [])
        if not items:
            raise HTTPException(404, "Parent item not found.")
        
        parent_item = items[0]
        parent_type = parent_item.get("Type")
        parent_name = parent_item.get("Name")
        
        if parent_type == "Playlist":
            if core.items.clear_playlist_items(item_id, req.user_id, media, log):
                success = core.items.add_items_to_playlist_by_ids(item_id, req.item_ids, req.user_id, media, log)
                if not success:
                    raise HTTPException(500, "Failed to re-add items to playlist.")
            else:
                raise HTTPException(500, "Failed to clear playlist for reordering.")
        elif parent_type in ["BoxSet", "Collection"]:
            require_collection_permission(media)
            if core.delete_item_by_id(item_id, media):
                new_id = core.items.create_collection_from_ids(req.user_id, parent_name, req.item_ids, media, log)
                if not new_id:
                    raise HTTPException(500, "Failed to recreate collection with new order.")
            else:
                raise HTTPException(500, "Failed to delete collection for reordering.")
        else:
            raise HTTPException(400, f"Unsupported item type for reordering: {parent_type}")

        return {"status": "ok", "log": ["Items reordered successfully."]}
        
    except HTTPException:
        raise
    except Exception as e:
        logging.error(f"Error reordering item {item_id}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/api/delete_item")
def api_delete_item(req: models.DeleteItemRequest, auth_deps: dict = Depends(get_current_auth_headers)) -> Dict[str, Any]:
    try:
        media = media_for_user(auth_deps, req.user_id)
        item_response = media.get(f"/Users/{req.user_id}/Items", params={"Ids": req.item_id}, timeout=10)
        item_response.raise_for_status()
        items = item_response.json().get("Items", [])
        if items and items[0].get("Type") in ("BoxSet", "Collection"):
            require_collection_permission(media)
        if core.delete_item_by_id(req.item_id, media):
            return {"status": "ok", "log": ["Item deleted successfully."]}
        else:
            raise HTTPException(status_code=400, detail="Failed to delete item. Check server logs for permission issues.")
    except HTTPException:
        raise
    except Exception as e:
        logging.error(f"Error processing delete request for item {req.item_id}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"An internal server error occurred: {str(e)}")

@router.post("/api/collections/{collection_id}/items/remove")
def api_remove_from_collection(
    collection_id: str,
    req: models.RemoveFromPlaylistRequest,
    auth_deps: dict = Depends(get_current_auth_headers)
) -> Dict[str, Any]:
    """
    Removes an item from a Collection (BoxSet).
    Uses the generic RemoveFromPlaylistRequest as the schema is identical.
    """
    try:
        media = media_for_user(auth_deps, req.user_id)
        require_collection_permission(media)

        if core.remove_item_from_collection(collection_id, req.item_id_to_remove, media):
            return {"status": "ok", "log": ["Item removed from collection."]}
        else:
            raise HTTPException(
                status_code=400,
                detail="Failed to remove item from collection. It may not be in this collection."
            )
    except HTTPException:
        raise
    except Exception as e:
        logging.error(f"Error removing item {req.item_id_to_remove} from collection {collection_id}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/api/playlists/{playlist_id}/items/remove")
def api_remove_from_playlist(playlist_id: str, req: models.RemoveFromPlaylistRequest, auth_deps: dict = Depends(get_current_auth_headers)) -> Dict[str, Any]:
    try:
        media = media_for_user(auth_deps, req.user_id)
        if core.remove_item_from_playlist(playlist_id, req.item_id_to_remove, media):
            return {"status": "ok", "log": ["Item removed from playlist."]}
        else:
            raise HTTPException(status_code=400, detail="Failed to remove item from playlist. It may have already been removed.")
    except HTTPException:
        raise
    except Exception as e:
        logging.error(f"Error removing item {req.item_id_to_remove} from playlist {playlist_id}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/api/convert_item")
def api_convert_item(req: models.ConvertItemRequest, auth_deps: dict = Depends(get_current_auth_headers)) -> Dict[str, Any]:
    media = media_for_user(auth_deps, req.user_id)
    log = []

    try:
        if req.delete_original:
            source_response = media.get(f"/Users/{req.user_id}/Items", params={"Ids": req.item_id}, timeout=10)
            source_response.raise_for_status()
            source_items = source_response.json().get("Items", [])
            if source_items and source_items[0].get("Type") in ("BoxSet", "Collection"):
                require_collection_permission(media)
        children = core.get_item_children(req.user_id, req.item_id, media)
        if not children:
            raise HTTPException(status_code=400, detail="Source item is empty. Nothing to convert.")

        item_ids = [child["Id"] for child in children]

        if req.target_type.lower() == "collection":
            require_collection_permission(media)
            new_id = core.create_collection_from_ids(req.user_id, req.new_name, item_ids, media, log)
        else:
            new_id = core.create_playlist(req.new_name, req.user_id, item_ids, media, log)

        if not new_id:
            raise HTTPException(status_code=500, detail="Failed to create the new converted item.")

        if req.delete_original:
            core.delete_item_by_id(req.item_id, media)
            log.append("Original item deleted.")

        return {"status": "ok", "log": log, "new_item_id": new_id}

    except HTTPException:
        raise
    except Exception as e:
        logging.error(f"Error converting item {req.item_id}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/api/shows/{series_id}/unplayed")
def api_mark_unplayed(
    series_id: str,
    req: models.ResetWatchRequest = Body(...),
    auth_deps: dict = Depends(get_current_auth_headers)
):
    media = media_for_user(auth_deps, req.user_id)
    try:
        from app import tv
        success = tv.mark_unplayed(series_id, req.user_id, media, req.season_number)

        if success:
            return {"status": "ok", "log": ["Watch history reset successfully."]}
        else:
            raise HTTPException(400, "Could not find the specified season to reset.")
    except HTTPException:
        raise
    except Exception as e:
        logging.error(f"Error resetting watch state: {e}", exc_info=True)
        raise HTTPException(500, str(e))

@router.post("/api/library/enrichment/start")
def api_start_enrichment(
    req: models.StartEnrichmentRequest = Body(default_factory=models.StartEnrichmentRequest),
    auth_deps: dict = Depends(get_current_auth_headers)
) -> Dict[str, Any]:
    """Starts a background metadata enrichment process for the current connection."""
    require_generative_ai(auth_deps)
    connection_id = auth_deps["connection_id"]
    media = auth_deps["media"]
    try:
        res = core.start_enrichment(
            connection_id=connection_id,
            media=media,
            batch_size=req.batch_size,
            max_items=req.max_items
        )
        return {"status": "ok", "state": res}
    except HTTPException:
        raise
    except ai_policy_errors as policy_error:
        # Checked outside the generic handler below: a policy refusal must reach the
        # browser as 403/409 with its reason, not as a generic 500.
        raise policy_http(policy_error) from policy_error
    except RuntimeError as re:
        raise HTTPException(status_code=409, detail=str(re))
    except ValueError as ve:
        raise HTTPException(status_code=400, detail=str(ve))
    except Exception as e:
        logging.error(f"Failed to start enrichment: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/api/library/enrichment/stop")
def api_stop_enrichment(auth_deps: dict = Depends(get_current_auth_headers)) -> Dict[str, Any]:
    """Stops the active enrichment worker for the current connection."""
    connection_id = auth_deps["connection_id"]
    return core.stop_enrichment(connection_id)

@router.get("/api/library/enrichment/status")
def api_enrichment_status(auth_deps: dict = Depends(get_current_auth_headers)) -> Dict[str, Any]:
    """Gets the current status and queue depth of enrichment for the current connection."""
    connection_id = auth_deps["connection_id"]
    media = auth_deps["media"]
    return core.get_enrichment_status(connection_id, media=media)

@router.post("/api/library/semantic_refresh")
def api_semantic_refresh(auth_deps: dict = Depends(get_current_auth_headers)) -> Dict[str, Any]:
    """Selectively re-indexes changed library items in ChromaDB while preserving AI enrichments."""
    user_id = auth_deps["login_uid"]
    media = auth_deps["media"]
    try:
        return core.refresh_semantic_index(user_id, media)
    except Exception as e:
        logging.error(f"Semantic refresh failed: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/api/bulk_delete_items")
def api_bulk_delete_items(
    req: models.BulkDeleteRequest,
    auth_deps: dict = Depends(get_current_auth_headers)
) -> Dict[str, Any]:
    """Bulk deletes items with per-item permission checks and reported outcomes."""
    media = media_for_user(auth_deps, req.user_id)
    deleted = []
    failed = []

    for item_id in req.item_ids:
        try:
            item_resp = media.get(f"/Users/{req.user_id}/Items", params={"Ids": item_id}, timeout=5)
            if item_resp.ok:
                items_data = item_resp.json().get("Items", [])
                if items_data and items_data[0].get("Type") in ("BoxSet", "Collection"):
                    if not media.can_manage_collections():
                        failed.append({"id": item_id, "name": items_data[0].get("Name", item_id), "reason": "Permission denied for collections"})
                        continue

            if core.delete_item_by_id(item_id, media):
                deleted.append(item_id)
            else:
                failed.append({"id": item_id, "reason": "Media server deletion failed"})
        except Exception as e:
            failed.append({"id": item_id, "reason": str(e)})

    return {
        "status": "ok",
        "deleted_count": len(deleted),
        "failed_count": len(failed),
        "deleted_ids": deleted,
        "failed_items": failed
    }

@router.post("/api/library/overlap_report")
def api_overlap_report(
    req: models.OverlapReportRequest,
    auth_deps: dict = Depends(get_current_auth_headers)
) -> Dict[str, Any]:
    """
    Finds items appearing across multiple playlists or collections.
    Bounded read to prevent media server thrashing.
    """
    media = media_for_user(auth_deps, req.user_id)
    target_ids = req.item_ids

    if not target_ids:
        manageable = core.get_manageable_items(req.user_id, media)
        target_ids = [m["Id"] for m in manageable[:30]]
    else:
        target_ids = target_ids[:50]

    parent_map = {}
    item_appearances: Dict[str, Dict[str, Any]] = {}

    for pid in target_ids:
        try:
            children = core.get_item_children(req.user_id, pid, media)
            p_resp = media.get(f"/Users/{req.user_id}/Items", params={"Ids": pid}, timeout=5)
            p_name = pid
            if p_resp.ok and p_resp.json().get("Items"):
                p_name = p_resp.json()["Items"][0].get("Name", pid)

            parent_map[pid] = p_name

            for child in children:
                cid = child.get("Id")
                if not cid:
                    continue
                if cid not in item_appearances:
                    item_appearances[cid] = {
                        "media_id": cid,
                        "name": child.get("Name", "Unknown"),
                        "type": child.get("Type", "Unknown"),
                        "in_items": []
                    }
                item_appearances[cid]["in_items"].append({"id": pid, "name": p_name})
        except Exception as e:
            logging.warning(f"Error fetching children for {pid} during overlap report: {e}")

    overlaps = [info for info in item_appearances.values() if len(info["in_items"]) > 1]
    overlaps.sort(key=lambda x: len(x["in_items"]), reverse=True)

    return {
        "status": "ok",
        "parents_checked": len(parent_map),
        "total_unique_media": len(item_appearances),
        "overlap_count": len(overlaps),
        "overlaps": overlaps
    }


