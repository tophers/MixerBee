"""
app/ai/vector_store.py - Vector DB init and config.
"""

import json
from typing import List, Dict
import chromadb

import app.client as client
from app_state import CONFIG_DIR
from app.logger import get_logger, refresh_logger_level

logger = get_logger("MixerBee.Vector")

CHROMA_PATH = CONFIG_DIR / "chroma_db"
chroma_client = chromadb.PersistentClient(path=str(CHROMA_PATH))

media_collection = chroma_client.get_or_create_collection(
    name="mixerbee_media"
)

def migrate_enrichment_fields():
    logger.info("VIBE INDEXER: Running schema migration check...")
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
            logger.info(f"VIBE INDEXER: Migrating {len(updates['ids'])} items to new schema.")
            for j in range(0, len(updates['ids']), 500):
                media_collection.update(
                    ids=updates['ids'][j:j+500],
                    metadatas=updates['metadatas'][j:j+500]
                )
            logger.info("VIBE INDEXER: Migration complete.")
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
    """Fetches metadata from Emby and embeds only new/missing items locally."""
    refresh_logger_level()
    migrate_enrichment_fields()
    logger.info("--- VIBE INDEXER: CHECKING FOR LIBRARY UPDATES ---")

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
            logger.info(f"VIBE INDEXER: Removing {len(ids_to_remove)} deleted items from Vector DB.")
            for i in range(0, len(ids_to_remove), 500):
                media_collection.delete(ids=ids_to_remove[i:i+500])

        if not ids_to_add:
            logger.info("VIBE INDEXER: Vector DB is up to date. No new items to index.")
            return

        logger.info(f"VIBE INDEXER: Found {len(ids_to_add)} new items. Fetching metadata...")
        
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
                title = item.get("Name", "")
                overview = item.get("Overview", "").strip()
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

                if not overview: 
                    overview = "No summary available."

                text_to_embed = f"Title: {title}. Year: {year_str}. Type: {item.get('Type')}. Genres: {genres}. Style: . Summary: {overview}"

                documents.append(text_to_embed)
                metadatas.append({
                    "name": title,
                    "type": item.get("Type"),
                    "year": year_str,
                    "genres": genres,
                    "overview": overview,
                    "is_enriched": False,
                    "vibe_tags": ""
                })
                upsert_ids.append(item["Id"])

            if upsert_ids:
                media_collection.upsert(
                    documents=documents,
                    metadatas=metadatas,
                    ids=upsert_ids
                )
            logger.info(f"VIBE INDEXER: Processed {min(i+batch_size, len(ids_to_add))} / {len(ids_to_add)} new items.")

        logger.info("--- VIBE INDEXER: VECTOR UPDATE COMPLETE ---")

    except Exception as e:
        logger.error(f"VIBE INDEXER: Failed during library sync: {e}", exc_info=True)


def search_by_vibe(query: str = None, **kwargs) -> List[Dict[str, str]]:
    refresh_logger_level()
    if not query:
        query = kwargs.get("vibe") or kwargs.get("concept") or kwargs.get("description")
    if not query: return []

    logger.info(f"--- VIBE SEARCH REQUEST: '{query}' ---")

    try:
        results = media_collection.query(query_texts=[query], n_results=25)

        if not results['ids'] or not results['ids'][0]:
            return []

        matched_items = []
        for i in range(len(results['ids'][0])):
            matched_items.append({
                "Id": results['ids'][0][i],
                "Name": results['metadatas'][0][i]["name"],
                "Type": results['metadatas'][0][i]["type"],
                "Year": results['metadatas'][0][i].get("year", "Unknown")
            })

        logger.info(f"VIBE SEARCH: Found {len(matched_items)} potential matches.")
        for i, item in enumerate(matched_items[:5]):
            logger.info(f"    Hit {i+1}: {item['Name']} ({item['Year']}) [ID: {item['Id']}]")

        return matched_items
    except Exception as e:
        logger.error(f"Vibe search failed: {e}")
        return []
