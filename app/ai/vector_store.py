import logging
from typing import List, Dict

import chromadb

import app.client as client
from app_state import CONFIG_DIR

# ==========================================
# 1. DATABASE INITIALIZATION
# ==========================================
CHROMA_PATH = CONFIG_DIR / "chroma_db"
chroma_client = chromadb.PersistentClient(path=str(CHROMA_PATH))

media_collection = chroma_client.get_or_create_collection(
    name="mixerbee_media"
)

# ==========================================
# 2. INDEXING & SEARCHING
# ==========================================
def index_library_for_vibes(user_id: str, hdr: dict):
    """Fetches metadata from Emby and embeds it completely locally."""
    logging.info("VIBE INDEXER: Starting local library vector indexing...")
    
    all_items = []
    start_index = 0
    limit = 500
    
    try:
        # --- PAGINATION LOOP ---
        while True:
            params = {
                "IncludeItemTypes": "Movie,Series",
                "Recursive": "true",
                "Fields": "Overview,Genres",
                "UserId": user_id,
                "StartIndex": start_index,
                "Limit": limit
            }
            
            r = client.SESSION.get(f"{client.EMBY_URL}/Users/{user_id}/Items", params=params, headers=hdr, timeout=30)
            r.raise_for_status()
            
            data = r.json()
            items = data.get("Items", [])
            
            if not items:
                break
                
            all_items.extend(items)
            
            if len(items) < limit:
                break
                
            start_index += limit
            logging.info(f"VIBE INDEXER: Fetched {len(all_items)} items from server so far...")

        if not all_items:
            logging.warning("VIBE INDEXER: No items found to index.")
            return

        documents = []
        metadatas = []
        ids = []
        
        for item in all_items:
            title = item.get("Name", "")
            overview = item.get("Overview", "")
            genres = ", ".join(item.get("Genres", []))
            
            if not overview:
                continue
                
            text_to_embed = f"Title: {title}. Genres: {genres}. Summary: {overview}"
            
            documents.append(text_to_embed)
            metadatas.append({"name": title, "type": item.get("Type")})
            ids.append(item["Id"])

        batch_size = 500
        total_items = len(ids)
        
        logging.info(f"VIBE INDEXER: Commencing vectorization of {total_items} total items...")
        
        for i in range(0, total_items, batch_size):
            media_collection.upsert(
                documents=documents[i:i+batch_size],
                metadatas=metadatas[i:i+batch_size],
                ids=ids[i:i+batch_size]
            )
            logging.info(f"VIBE INDEXER: Successfully indexed {min(i+batch_size, total_items)} / {total_items} items.")

        logging.info("VIBE INDEXER: Local vector indexing complete!")
        
    except Exception as e:
        logging.error(f"VIBE INDEXER: Failed to index library: {e}", exc_info=True)


def search_by_vibe(query: str) -> List[Dict[str, str]]:
    """
    TOOL: Searches the library locally by semantic meaning or 'vibe'.
    Returns a list of matching items with their names and IDs.
    """
    try:
        results = media_collection.query(
            query_texts=[query],
            n_results=15 
        )
        
        if not results['ids'] or not results['ids'][0]:
            return []
            
        matched_items = []
        for i in range(len(results['ids'][0])):
            matched_items.append({
                "Id": results['ids'][0][i],
                "Name": results['metadatas'][0][i]["name"],
                "Type": results['metadatas'][0][i]["type"]
            })
            
        return matched_items
    except Exception as e:
        logging.error(f"Vibe search failed: {e}")
        return []
