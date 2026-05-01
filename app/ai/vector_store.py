"""
app/ai/vector_store.py - Vector DB init and config.
"""

import json
import time
import threading
from typing import List, Dict, Optional
import chromadb

import app.client as client
from app_state import CONFIG_DIR
from app.logger import get_logger, refresh_logger_level

logger = get_logger("MixerBee.Vector")

CHROMA_PATH = CONFIG_DIR / "chroma_db"
chroma_client = chromadb.PersistentClient(path=str(CHROMA_PATH))

_active_collection: Optional[chromadb.Collection] = None

def get_media_collection() -> chromadb.Collection:
    """
    Always returns the currently active 'mixerbee_media' collection handle.
    """
    global _active_collection
    if _active_collection is None:
        _active_collection = chroma_client.get_or_create_collection(
            name="mixerbee_media",
            metadata={"hnsw:space": "cosine"}
        )
    return _active_collection

class CollectionProxy:
    """
    A transparent proxy for the ChromaDB collection.
    """
    def __getattr__(self, name):
        return getattr(get_media_collection(), name)

    def __repr__(self):
        return repr(get_media_collection())

media_collection = CollectionProxy()

def get_vector_space() -> str:
    """Returns the distance metric currently used by the collection."""
    try:
        col = get_media_collection()
        meta = col.metadata or {}
        return meta.get("hnsw:space", "l2")
    except:
        return "cosine"

def reset_media_collection(preserve_enrichments: bool = True):
    """
    Manually resets the ChromaDB collection.
    """
    import app_state
    global _active_collection
    enriched_backups = {}

    try:
        col = get_media_collection()
        if preserve_enrichments:
            logger.info("RESET: Backing up AI enrichments before wipe...")
            existing = col.get(where={"is_enriched": True}, include=["metadatas"])
            if existing and existing.get('ids'):
                for i, item_id in enumerate(existing['ids']):
                    meta = existing['metadatas'][i]
                    if meta and meta.get('vibe_tags'):
                        enriched_backups[item_id] = meta['vibe_tags']
                logger.info(f"RESET: Backed up {len(enriched_backups)} enriched items.")

        logger.info("RESET: Deleting 'mixerbee_media' collection...")
        chroma_client.delete_collection(name="mixerbee_media")
    except Exception as e:
        logger.warning(f"RESET: Collection may not exist or error during wipe: {e}")

    logger.info("RESET: Recreating collection with Cosine similarity...")
    
    _active_collection = None
    get_media_collection() 

    if preserve_enrichments and enriched_backups:
        app_state.ENRICHMENT_BACKUP = enriched_backups
        logger.info("RESET: Backups queued for restoration on next library sync.")

def ensure_cosine_similarity():
    """
    Checks if the collection is using L2 (Euclidean) and migrates to Cosine if so.
    Preserves 'vibe_tags' for any enriched items during the transition.
    """
    import app_state
    current_space = get_vector_space()
    if current_space == "cosine":
        return

    logger.warning(f"DETECTION: Vector DB is using '{current_space}'. Migrating to 'cosine' to improve AI semantics...")

    reset_media_collection(preserve_enrichments=True)

TYPE_COUNT_CACHE = {}
LAST_CACHE_TIME = 0
CACHE_LOCK = threading.Lock()

def get_dynamic_limit(media_type: str) -> int:
    """Calculates a proportional limit based on the actual size of the user's library."""
    global TYPE_COUNT_CACHE, LAST_CACHE_TIME

    with CACHE_LOCK:
        if time.time() - LAST_CACHE_TIME > 300:
            TYPE_COUNT_CACHE.clear()
            LAST_CACHE_TIME = time.time()

        if media_type not in TYPE_COUNT_CACHE:
            try:
                res = media_collection.get(where={"type": media_type}, include=[])
                TYPE_COUNT_CACHE[media_type] = len(res.get('ids', []))
            except Exception as e:
                logger.error(f"Failed to count {media_type}s: {e}")
                TYPE_COUNT_CACHE[media_type] = 0

        total_items = TYPE_COUNT_CACHE[media_type]

    if total_items == 0:
        return 12

    calculated = int(total_items * 0.05)
    final_limit = max(12, min(30, calculated))

    logger.info(f"Dynamic Limit Calc: {total_items} total {media_type}s -> 5% = {calculated} -> Clamped to {final_limit}")
    return final_limit

def migrate_enrichment_fields():
    logger.info("Running schema migration check...")
    import app_state
    try:
        total = media_collection.count()
        if total == 0: return

        existing = media_collection.get(limit=total, include=["metadatas"])
        if not existing or not existing.get('ids'): return

        updates = {'ids': [], 'metadatas': []}

        for i, meta in enumerate(existing['metadatas']):
            if meta is None: meta = {}
            if 'is_enriched' not in meta:
                meta['is_enriched'] = False
                meta['vibe_tags'] = ""
                if 'genres' not in meta: meta['genres'] = ""
                if 'overview' not in meta: meta['overview'] = ""
                updates['ids'].append(existing['ids'][i])
                updates['metadatas'].append(meta)

        if updates['ids']:
            logger.info(f"Migrating {len(updates['ids'])} items with missing schema fields.")
            for j in range(0, len(updates['ids']), 500):
                media_collection.update(
                    ids=updates['ids'][j:j+500],
                    metadatas=updates['metadatas'][j:j+500]
                )

    except Exception as e:
        logger.error(f"Migration failed: {e}", exc_info=True)

def calculate_library_iq() -> dict:
    try:
        total = media_collection.count()
        if total == 0: return {"total": 0, "enriched": 0}

        all_data = media_collection.get(limit=total, include=["metadatas"])

        enriched_count = 0
        if all_data and all_data.get('metadatas'):
            for meta in all_data['metadatas']:
                if meta and str(meta.get('is_enriched', 'False')).lower() == "true":
                    enriched_count += 1

        return {"total": total, "enriched": enriched_count}
    except Exception as e:
        logger.error(f"Stats calculation failed: {e}")
        return {"total": 0, "enriched": 0}

def index_library_for_vibes(user_id: str, hdr: dict):
    """Fetches metadata from Emby and embeds locally. Restores AI tags from backup if available."""
    import app_state
    refresh_logger_level()
    migrate_enrichment_fields()
    logger.info("Vector DB Checking for Library Updates")

    backup_tags = getattr(app_state, 'ENRICHMENT_BACKUP', {})

    try:
        existing_data = media_collection.get(include=[])
        existing_ids = set(existing_data['ids']) if existing_data and existing_data['ids'] else set()

        emby_ids = set()
        start_index = 0
        limit = 15000

        while True:
            params = {
                "IncludeItemTypes": "Movie,Series",
                "Recursive": "true",
                "UserId": user_id,
                "StartIndex": start_index,
                "Limit": limit,
                "Fields": ""
            }
            r = client.SESSION.get(f"{client.EMBY_URL}/Users/{user_id}/Items", params=params, headers=hdr, timeout=30)
            r.raise_for_status()
            items = r.json().get("Items", [])
            if not items: break

            emby_ids.update([item["Id"] for item in items])
            if len(items) < limit: break
            start_index += limit

        ids_to_remove = list(existing_ids - emby_ids)
        ids_to_add = list(emby_ids - existing_ids)

        if ids_to_remove:
            logger.info(f"Removing {len(ids_to_remove)} deleted items from Vector DB.")
            for i in range(0, len(ids_to_remove), 500):
                media_collection.delete(ids=ids_to_remove[i:i+500])

        if not ids_to_add:
            logger.info("Vector DB is up to date. No new items to index.")
            return

        logger.info(f"Found {len(ids_to_add)} items to index. Checking for AI tag restoration...")

        batch_size = 100
        for i in range(0, len(ids_to_add), batch_size):
            batch_ids = ids_to_add[i:i+batch_size]
            params = {
                "Ids": ",".join(batch_ids),
                "UserId": user_id,
                "Fields": "Overview,Genres,ProductionYear,PremiereDate,DateCreated"
            }
            r = client.SESSION.get(f"{client.EMBY_URL}/Users/{user_id}/Items", params=params, headers=hdr, timeout=30)
            r.raise_for_status()

            new_items = r.json().get("Items", [])
            if not new_items: continue

            documents = []
            metadatas = []
            upsert_ids = []

            for item in new_items:
                item_id = item["Id"]
                title = item.get("Name", "")
                overview = item.get("Overview", "").strip() or "No summary available."
                genres = ", ".join(item.get("Genres", []))

                year = item.get("ProductionYear")
                if not year and item.get("PremiereDate"):
                    try:
                        year = item.get("PremiereDate")[:4]
                    except: pass
                if not year and item.get("DateCreated"):
                    try:
                        year = item.get("DateCreated")[:4]
                    except: pass

                year_str = str(year) if year else "Unknown Year"

                is_enriched = False
                vibe_tags = ""
                if item_id in backup_tags:
                    vibe_tags = backup_tags[item_id]
                    is_enriched = True
                    logger.info(f"MIGRATION: Restoring AI tags for '{title}'")

                text_to_embed = f"Title: {title}. Year: {year_str}. Format: {item.get('Type')}. Genres: {genres}. Style: {vibe_tags}. Summary: {overview}"

                documents.append(text_to_embed)
                metadatas.append({
                    "name": title,
                    "type": item.get("Type"),
                    "year": year_str,
                    "genres": genres,
                    "overview": overview,
                    "is_enriched": is_enriched,
                    "vibe_tags": vibe_tags
                })
                upsert_ids.append(item_id)


            if upsert_ids:
                media_collection.upsert(
                    documents=documents,
                    metadatas=metadatas,
                    ids=upsert_ids
                )
            logger.info(f"Processed {min(i+batch_size, len(ids_to_add))} / {len(ids_to_add)} items.")

        if hasattr(app_state, 'ENRICHMENT_BACKUP') and app_state.ENRICHMENT_BACKUP:
            app_state.ENRICHMENT_BACKUP = {}
            logger.info("MIGRATION: Enrichment restoration buffer cleared.")

        logger.info("Vector Update Complete")

    except Exception as e:
        logger.error(f"Failed during library sync: {e}", exc_info=True)

def search_by_vibe(query: str = None, media_type: str = None, limit: int = None, threshold: float = None, **kwargs) -> List[Dict[str, str]]:
    """
    Searches the library for media matching a specific vibe, mood, theme, or description.
    Includes a 'Radius Lock' to filter out mathematically irrelevant results.

    Args:
        query: The conceptual vibe or theme to search for (e.g., "gritty cyberpunk", "90s sitcom").
        media_type: Optional. Filter strictly by format: use 'Movie' or 'Series'.
        limit: Optional override for search depth.
        threshold: Optional override for relevancy strictness (0.0 to 1.0).
    """
    refresh_logger_level()
    if not query:
        query = kwargs.get("vibe") or kwargs.get("concept") or kwargs.get("description")
    if not query: return []

    from .orchestrator import ai_tweaks_context
    active_tweaks = ai_tweaks_context.get()

    if threshold is None and active_tweaks:
        threshold = active_tweaks.threshold
    if limit is None and active_tweaks:
        limit = active_tweaks.limit

    current_threshold = threshold if threshold is not None else 0.72

    try:
        where_clause = {}
        mt_normalized = ""
        if media_type:
            mt_normalized = media_type.strip().capitalize()
            if mt_normalized in ["Tv", "Show"]:
                mt_normalized = "Series"
            where_clause["type"] = mt_normalized

        if limit is not None:
            final_limit = int(limit)
        else:
            if mt_normalized:
                final_limit = get_dynamic_limit(mt_normalized)
            else:
                final_limit = 15

    except Exception as e:
        logger.warning(f"Failed to parse limit/type, defaulting to 15: {e}")
        final_limit = 15

    logger.info(f"Vibe Search Request: '{query}' | Threshold: {current_threshold} | Limit: {final_limit}")

    try:
        results = media_collection.query(
            query_texts=[query],
            n_results=final_limit,
            where=where_clause if where_clause else None,
            include=["metadatas", "distances"]
        )

        if not results['ids'] or not results['ids'][0]:
            return []

        matched_items = []
        for i in range(len(results['ids'][0])):
            name = results['metadatas'][0][i]["name"]
            year = results['metadatas'][0][i].get("year", "Unknown")
            item_id = results['ids'][0][i]
            distance = results['distances'][0][i] if results['distances'] else 0.0

            if distance > current_threshold:
                logger.info(f"   [SKIPPED] {name} ({year}) | Cosine Distance: {distance:.4f} (Outside Radius)")
                continue

            matched_items.append({
                "Id": item_id,
                "Name": name,
                "Type": results['metadatas'][0][i]["type"],
                "Year": year,
                "Genres": results['metadatas'][0][i].get("genres", ""),
                "Distance": distance
            })

            logger.info(f"   [KEEP] {name} ({year}) [ID: {item_id}] | Cosine Distance: {distance:.4f}")

        return matched_items
    except Exception as e:
        logger.error(f"Vibe search failed: {e}")
        return []
