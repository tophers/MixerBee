"""
gemini_client.py
"""

import random
import logging
from typing import List, Dict, Optional, Literal
from pydantic import BaseModel, Field
from google import genai
from google.genai import types

_BEST_MODEL = None

def _get_best_model(client: genai.Client) -> str:
    global _BEST_MODEL
    if _BEST_MODEL:
        return _BEST_MODEL

    preferred_models = ["gemini-2.5-flash", "gemini-2.0-flash", "gemini-1.5-flash"]
    
    try:
        available_models = [m.name for m in client.models.list()]
        for pm in preferred_models:
            if any(pm in m for m in available_models):
                _BEST_MODEL = pm
                return _BEST_MODEL
    except Exception as e:
        logging.warning(f"Could not fetch model list: {e}. Falling back to default.")

    _BEST_MODEL = "gemini-2.0-flash"
    return _BEST_MODEL

class Person(BaseModel):
    Name: str

class Filters(BaseModel):
    genres_any: Optional[List[str]] = Field(default_factory=list)
    genres_all: Optional[List[str]] = Field(default_factory=list)
    genres_exclude: Optional[List[str]] = Field(default_factory=list)
    people: Optional[List[Person]] = Field(default_factory=list)
    exclude_people: Optional[List[Person]] = Field(default_factory=list)
    studios: Optional[List[str]] = Field(default_factory=list)
    exclude_studios: Optional[List[str]] = Field(default_factory=list)
    watched_status: Optional[str] = "unplayed"
    year_from: Optional[int] = None
    year_to: Optional[int] = None
    sort_by: Optional[str] = "Random"
    limit: Optional[int] = 5
    duration_minutes: Optional[int] = None

class Show(BaseModel):
    name: str
    season: int = 1
    episode: int = 1
    unwatched: bool = False

class Block(BaseModel):
    type: Literal["tv", "movie", "music"]
    shows: Optional[List[Show]] = None
    mode: Optional[str] = "count"
    count: Optional[int] = 5
    end_season: Optional[int] = None
    end_episode: Optional[int] = None
    interleave: Optional[bool] = True
    filters: Optional[Filters] = None

def generate_blocks_from_prompt(prompt: str, api_key: str, available_shows: List[str], available_genres: List[str]) -> tuple[List[Dict], str]:
    if not api_key:
        raise ValueError("Gemini API key is not configured.")

    client = genai.Client(api_key=api_key)
    model_name = _get_best_model(client)

    sample_size = min(250, len(available_shows))
    sampled_shows = random.sample(available_shows, sample_size) if available_shows else []

    show_list = ", ".join(sampled_shows)
    genre_list = ", ".join(available_genres)

    full_prompt = f"""
    You are an expert at creating Emby/Jellyfin playlist blocks from user requests.
    Your response MUST strictly adhere to the requested JSON schema.

    1. TV SHOW SELECTION: Pick shows from the 'Available TV shows' list that best fit the request. If you cannot find perfect matches, pick the closest alternatives from the list. NEVER leave the 'shows' array empty for a TV block.
    2. MOVIE SELECTION: For movie requests, map the requested genre to the closest match in the 'Available movie genres' list and put it in `filters.genres_any`. If a specific number of movies is requested, set `filters.limit` to that number. NEVER leave the `filters` object empty for a movie block.
    3. INTERLEAVING: If the user asks for a block of multiple shows, return ONLY ONE object in the array with 'interleave' set to true, listing all shows inside the 'shows' list.
    4. NO BLANKS: Every block MUST have at least one show or filter.
    5. RANDOMIZATION: Pick a random Season (1-4) and random Episode (1-10) for shows if not specified.

    Available TV shows: {show_list}
    Available movie genres: {genre_list}

    User Request: "{prompt}"
    """

    try:
        response = client.models.generate_content(
            model=model_name,
            contents=full_prompt,
            config=types.GenerateContentConfig(
                response_mime_type="application/json",
                response_schema=list[Block],
                temperature=0.4
            )
        )

        if not response.parsed:
            raise ValueError("AI returned an empty response or failed to parse the schema.")

        valid_blocks = []
        
        for block_obj in response.parsed:
            block = block_obj.model_dump(exclude_none=True)
            
            if (block.get("type") == "tv" and block.get("shows")) or \
               (block.get("type") == "movie" and block.get("filters")) or \
               (block.get("type") == "music"):
                valid_blocks.append(block)

        if not valid_blocks:
            raise ValueError("AI generated blocks, but none contained valid shows or filters.")

        return valid_blocks, model_name

    except ValueError as ve:
        logging.error(f"Validation Error: {ve}")
        raise
        
    except Exception as e:
        logging.error(f"Gemini API Communication Error: {e}", exc_info=True)
        raise ConnectionError(f"Failed to process the request with the AI. Error: {str(e)}")