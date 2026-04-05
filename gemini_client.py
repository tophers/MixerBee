"""
gemini_client.py
"""

import json
import random
import logging
from typing import List, Dict, Optional
from pydantic import BaseModel, Field

from google import genai
from google.genai import types

# Global cache so we only hit the models API once per session
_BEST_MODEL = None

def _get_best_model(client: genai.Client) -> str:
    """
    Dynamically discovers the best available Gemini Flash model.
    Falls back gracefully if the API call fails.
    """
    global _BEST_MODEL
    if _BEST_MODEL:
        return _BEST_MODEL

    # Priority list (newest/best for this task first)
    preferred_models = ["gemini-2.5-flash", "gemini-2.0-flash", "gemini-1.5-flash"]
    
    try:
        # Fetch available models from the user's API key
        available_models = [m.name for m in client.models.list()]
        for pm in preferred_models:
            if any(pm in m for m in available_models):
                _BEST_MODEL = pm
                logging.info(f"Selected Gemini model: {_BEST_MODEL}")
                return _BEST_MODEL
    except Exception as e:
        logging.warning(f"Could not fetch model list: {e}. Falling back to default.")

    _BEST_MODEL = "gemini-2.0-flash" 
    return _BEST_MODEL


# --- Pydantic Schemas for Structured JSON Output ---

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
    watched_status: Optional[str] = Field(default="unplayed", description="'all', 'unplayed', or 'played'")
    year_from: Optional[int] = None
    year_to: Optional[int] = None
    sort_by: Optional[str] = Field(default="Random")
    limit: Optional[int] = 5
    duration_minutes: Optional[int] = None

class Show(BaseModel):
    name: str = Field(description="Must exactly match a show from the available list.")
    season: int = 1
    episode: int = 1
    unwatched: bool = False

class Block(BaseModel):
    type: str = Field(description="'tv' or 'movie'")
    shows: Optional[List[Show]] = None
    mode: Optional[str] = Field(default="count", description="'count' or 'range'")
    count: Optional[int] = 5
    interleave: Optional[bool] = True
    filters: Optional[Filters] = None


# --- Core Generation Logic ---

def generate_blocks_from_prompt(prompt: str, api_key: str, available_shows: List[str], available_genres: List[str]) -> List[Dict]:
    """
    Takes a user's text prompt and uses the Gemini API to translate it
    into a structured list of playlist blocks.
    """
    if not api_key:
        raise ValueError("Gemini API key is not configured.")

    client = genai.Client(api_key=api_key)
    model_name = _get_best_model(client)

    # Randomize the TV shows injected into the prompt.
    # This prevents the AI from being heavily biased toward alphabetically early shows
    # while staying safely within the token/context limits of the model.
    sample_size = min(250, len(available_shows))
    sampled_shows = random.sample(available_shows, sample_size) if available_shows else []

    show_list = ", ".join(sampled_shows)
    genre_list = ", ".join(available_genres)

    full_prompt = f"""
    You are an expert at creating Emby/Jellyfin playlist blocks from user requests.
    Your response MUST strictly adhere to the requested JSON schema.

    ### CRITICAL RULES:
    1. EXACT COUNTS: Include exactly the number of different shows requested. Do not invent shows not on the list.
    2. INTERLEAVING: If the user asks for a block of multiple shows, return ONLY ONE object in the array with 'interleave' set to true, listing all shows inside the 'shows' list.
    3. NO BLANKS: Every block MUST have at least one show or filter.
    4. RANDOMIZATION: Pick a random Season (1-4) and random Episode (1-10) for shows if not specified.

    ### CONTEXT:
    - Available TV shows (randomized subset): {show_list}
    - Available movie genres: {genre_list}

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

        parsed_json = json.loads(response.text)

        valid_blocks = [
            block for block in parsed_json
            if (block.get("type") == "tv" and block.get("shows")) or
               (block.get("type") == "movie" and block.get("filters"))
        ]

        if not valid_blocks:
            raise ValueError("AI generated blocks, but none contained valid shows or filters.")

        return valid_blocks

    except json.JSONDecodeError as e:
        logging.error(f"JSON Parsing Error: {e}\nRaw Output: {response.text}")
        raise ConnectionError("The AI returned an invalid data format. Please try your request again.")

    except Exception as e:
        logging.error(f"Gemini API Error: {e}", exc_info=True)
        raise ConnectionError(f"Failed to process the request with the AI. Error: {str(e)}")