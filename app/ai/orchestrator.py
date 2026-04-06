import os
import logging
from typing import List, Dict, Optional, Literal
from pydantic import BaseModel, Field, field_validator
from google import genai
from google.genai import types

from .tools import AVAILABLE_TOOLS

# ==========================================
# 1. FLAT AI SCHEMA (Data Transfer Object)
# ==========================================
class AIBlock(BaseModel):
    block_type: Literal["tv", "movie", "music"] = Field(
        description="Must be 'tv', 'movie', or 'music'"
    )

    @field_validator('block_type', mode='before')
    @classmethod
    def lowercase_block_type(cls, v):
        if isinstance(v, str):
            return v.lower()
        return v
    
    ai_title: str = Field(
        default="Curated Mix",
        description="A short, catchy title for this block. E.g., 'Spooky Vibes' or '80s Action'"
    )
    
    tv_shows: List[str] = Field(
        default=[], 
        description="List of exact TV show names. Empty array if not a tv block."
    )
    tv_count: int = Field(
        default=3, 
        description="Number of episodes. Default to 3 if unspecified."
    )
    
    movie_genres: List[str] = Field(
        default=[], 
        description="List of exact movie genres. Empty array if not a movie block."
    )
    movie_limit: int = Field(
        default=5, 
        description="Number of movies. Default to 5 if unspecified."
    )
    movie_year_from: int = Field(
        default=0, 
        description="Start year for movie release (e.g., 1980). 0 if unspecified."
    )
    movie_year_to: int = Field(
        default=0, 
        description="End year for movie release (e.g., 1989). 0 if unspecified."
    )
    movie_people: List[str] = Field(
        default=[], 
        description="List of actor or director names requested. Empty array if unspecified."
    )
    
    movie_ids: List[str] = Field(
        default=[], 
        description="List of specific internal item IDs returned by the vibe search tool. Empty array if unspecified."
    )

    music_mode: Literal["album", "artist_top", "artist_random", "genre"] = Field(
        default="genre", 
        description="Must be 'album', 'artist_top', 'artist_random', or 'genre'. Default to 'genre'."
    )

    @field_validator('music_mode', mode='before')
    @classmethod
    def lowercase_music_mode(cls, v):
        if isinstance(v, str):
            return v.lower()
        return v

    music_artist_id: str = Field(
        default="", 
        description="The internal ID from the verify_artist tool. Empty string if not an artist request."
    )
    music_genres: List[str] = Field(
        default=[], 
        description="List of exact music genres. Empty array if not a genre request."
    )
    music_count: int = Field(
        default=15, 
        description="Number of tracks to fetch. Default to 15 if unspecified."
    )

def _map_to_frontend_block(ai_block: AIBlock) -> Optional[Dict]:
    """Translates the flat AI schema into the complex nested schema the frontend needs."""
    b_type = ai_block.block_type.lower()
    
    if "tv" in b_type:
        shows = [{"name": name, "season": 1, "episode": 1, "unwatched": True} for name in ai_block.tv_shows]
        if not shows: 
            return None
        return {
            "type": "tv",
            "title": ai_block.ai_title,
            "is_ai_generated": True, # TV blocks with specific shows act as curated lists
            "mode": "count",
            "count": max(1, ai_block.tv_count),
            "interleave": True,
            "shows": shows
        }
        
    elif "movie" in b_type:
        if not ai_block.movie_genres and not ai_block.movie_people and not ai_block.movie_ids and ai_block.movie_year_from == 0: 
            return None
            
        filters = {
            "watched_status": "unplayed",
            "sort_by": "Random",
            "limit": max(1, ai_block.movie_limit)
        }
        
        is_ai_curated = False
        
        if ai_block.movie_genres:
            filters["genres_any"] = ai_block.movie_genres
        if ai_block.movie_year_from > 0:
            filters["year_from"] = ai_block.movie_year_from
        if ai_block.movie_year_to > 0:
            filters["year_to"] = ai_block.movie_year_to
        if ai_block.movie_people:
            filters["people"] = [{"Name": name} for name in ai_block.movie_people]
            
        if ai_block.movie_ids:
            filters["ids"] = ai_block.movie_ids
            is_ai_curated = True # Flag this to hide the manual UI dropdowns!
            
        return {
            "type": "movie",
            "title": ai_block.ai_title,
            "is_ai_generated": is_ai_curated, 
            "filters": filters
        }
        
    elif "music" in b_type:
        return {
            "type": "music",
            "title": ai_block.ai_title,
            "is_ai_generated": bool(ai_block.music_artist_id), # Curated if targeting a specific artist
            "music": {
                "mode": ai_block.music_mode,
                "artistId": ai_block.music_artist_id,
                "count": max(1, ai_block.music_count),
                "filters": {
                    "genres": ai_block.music_genres,
                    "sort_by": "Random",
                    "limit": max(1, ai_block.music_count)
                }
            }
        }
    return None

# ==========================================
# 2. ORCHESTRATOR LOGIC
# ==========================================
def _get_best_model() -> str:
    return os.environ.get("GEMINI_MODEL", "gemini-2.5-flash")

def generate_smart_blocks(prompt: str) -> tuple[List[Dict], str]:
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        raise ValueError("Gemini API key is not configured.")

    client = genai.Client(api_key=api_key)
    model_name = _get_best_model()

    # --- AGENT 1: THE RESEARCHER ---
    researcher_system = """
    You are a library research assistant. Analyze the user's prompt.
    Use your tools to find the EXACT names of any TV shows, music artists, or genres mentioned.
    
    CRITICAL INSTRUCTION: If the user asks for a "vibe", "mood", "feeling", or ANY abstract concept (like "spooky", "mysterious", "cozy", "action-packed"), you ABSOLUTELY MUST call the `search_by_vibe` tool with that concept. Do not try to guess genres. Use the tool to get the specific internal IDs.
    
    Summarize your findings clearly. E.g., 'The user wants the following movie IDs for a spooky vibe: ["123", "456", "789"].'
    """
    
    logging.info(f"AI Phase 1: Researching items for prompt: '{prompt}'")
    chat = client.chats.create(
        model=model_name,
        config=types.GenerateContentConfig(
            system_instruction=researcher_system,
            tools=AVAILABLE_TOOLS,
            temperature=0.2
        )
    )
    
    research_response = chat.send_message(prompt)
    verified_context = research_response.text
    logging.info(f"AI Phase 1 Context Gathered: {verified_context}")

    # --- AGENT 2: THE BUILDER ---
    builder_system = """
    You are a JSON formatter for media playlists. You will receive a user's original request AND a verified context summary from a researcher.
    Your job is to translate this into the required JSON schema.
    
    CRITICAL RULES:
    1. Use ONLY the exact names/IDs provided in the verified context summary.
    2. You must output a flat schema. For fields that DO NOT apply, output an empty string "", 0, or an empty array [].
    3. Create one block object per distinct type of media requested.
    4. If the researcher provides specific Movie IDs, you MUST output them in the `movie_ids` array. Do not leave it empty if IDs are provided in the context.
    5. Always generate a fun, concise `ai_title` for the block based on the prompt.
    """
    
    builder_prompt = f"User Request: {prompt}\n\nVerified Context: {verified_context}"
    
    logging.info("AI Phase 2: Building strict JSON schema.")
    builder_response = client.models.generate_content(
        model=model_name,
        contents=builder_prompt,
        config=types.GenerateContentConfig(
            system_instruction=builder_system,
            response_mime_type="application/json",
            response_schema=list[AIBlock],
            temperature=0.1
        )
    )

    if not builder_response.parsed:
        raise ValueError("AI failed to generate a valid schema.")

    valid_blocks = []
    for ai_block in builder_response.parsed:
        frontend_block = _map_to_frontend_block(ai_block)
        if frontend_block:
            valid_blocks.append(frontend_block)

    if not valid_blocks:
        raise ValueError("AI generated blocks, but none contained valid data.")

    return valid_blocks, model_name
