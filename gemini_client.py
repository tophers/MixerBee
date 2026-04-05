"""
gemini_client.py
"""

import os
import time
import random
import logging
from typing import List, Dict, Optional, Literal
from pydantic import BaseModel, Field
from google import genai
from google.genai import types

def _get_best_model() -> str:
    """
    Defaults to the current standard model to ensure zero latency on startup.
    Advanced users can override this by manually adding GEMINI_MODEL to their .env file.
    """
    return os.environ.get("GEMINI_MODEL", "gemini-2.5-flash")

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

class MusicOptions(BaseModel):
    mode: Literal["album", "artist_top", "artist_random", "genre"]
    artist_name: Optional[str] = Field(None, description="Name of the artist if mode is artist_top or artist_random")
    count: Optional[int] = 10
    filters: Optional[Filters] = None

class Block(BaseModel):
    type: Literal["tv", "movie", "music"]
    shows: Optional[List[Show]] = None
    mode: Optional[str] = "count"
    count: Optional[int] = 5
    end_season: Optional[int] = None
    end_episode: Optional[int] = None
    interleave: Optional[bool] = True
    filters: Optional[Filters] = None
    music: Optional[MusicOptions] = None

def generate_blocks_from_prompt(
    prompt: str, 
    api_key: str, 
    available_shows: List[str], 
    available_genres: List[str],
    available_music_genres: List[str],
    available_artists: List[str],
    max_retries: int = 3
) -> tuple[List[Dict], str]:
    
    if not api_key:
        raise ValueError("Gemini API key is not configured.")

    client = genai.Client(api_key=api_key)
    model_name = _get_best_model()

    # Safely sample context limits to prevent massive token bloat
    sampled_shows = random.sample(available_shows, min(250, len(available_shows))) if available_shows else []
    sampled_artists = random.sample(available_artists, min(200, len(available_artists))) if available_artists else []

    system_rules = """
    You are an expert at creating Emby/Jellyfin playlist blocks from user requests.
    Your response MUST strictly adhere to the requested JSON schema.

    1. TV SHOW SELECTION: Pick shows from the provided 'Available TV shows' list that best fit the request. NEVER leave the 'shows' array empty for a TV block.
    2. MOVIE SELECTION: Map requested movie genres to 'Available movie genres' in `filters.genres_any`. NEVER leave the `filters` object empty for a movie block.
    3. MUSIC SELECTION: For music requests, set the `music` object. Map requested music genres to 'Available music genres' inside `music.filters.genres_any` (setting mode to 'genre'). If requesting an artist, set `music.mode` to 'artist_top' or 'artist_random' and provide the EXACT `music.artist_name` from 'Available artists'.
    4. INTERLEAVING: If the user asks for a block of multiple TV shows, return ONLY ONE object in the array with 'interleave' set to true, listing all shows inside the 'shows' list.
    5. NO BLANKS: Every block MUST have at least one show, movie filter, or music configuration.
    6. RANDOMIZATION: Pick a random Season (1-4) and random Episode (1-10) for shows if not specified.
    """

    user_context = f"""
    Available TV shows: {", ".join(sampled_shows)}
    Available movie genres: {", ".join(available_genres)}
    Available music genres: {", ".join(available_music_genres)}
    Available artists: {", ".join(sampled_artists)}

    User Request: "{prompt}"
    """

    for attempt in range(max_retries):
        try:
            response = client.models.generate_content(
                model=model_name,
                contents=user_context,
                config=types.GenerateContentConfig(
                    system_instruction=system_rules,
                    response_mime_type="application/json",
                    response_schema=list[Block],
                    temperature=0.4
                )
            )

            if not response.parsed:
                raise ValueError("AI returned an empty response or failed to parse the schema.")

            valid_blocks = [
                b.model_dump(exclude_none=True) for b in response.parsed
                if (b.type == "tv" and b.shows) or 
                   (b.type == "movie" and b.filters) or 
                   (b.type == "music" and b.music)
            ]

            if not valid_blocks:
                raise ValueError("AI generated blocks, but none contained valid configuration data.")

            return valid_blocks, model_name

        except Exception as e:
            logging.warning(f"Gemini API attempt {attempt + 1} failed: {e}")
            if attempt == max_retries - 1:
                logging.error("Max retries reached for Gemini API.", exc_info=True)
                raise ConnectionError(f"Failed to process the request with the AI after {max_retries} attempts.")
            time.sleep(2 ** attempt) # Exponential backoff: 1s, 2s, 4s