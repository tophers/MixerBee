"""
gemini_client.py – Manages Gemini API connectivity and prompt translation.
"""

import json
from typing import List, Dict
from google import genai
from google.genai import types

JSON_SCHEMA = """
[
  {
    "type": "tv", 
    "shows": [
      {
        "name": "Name of the TV Show (Must exactly match one from the available list)",
        "season": 1, 
        "episode": 1, 
        "unwatched": false
      }
    ],
    "mode": "count", 
    "count": 5, 
    "interleave": true 
  },
  {
    "type": "movie",
    "filters": {
      "genres_any": ["Action"],
      "genres_all": [],
      "genres_exclude": ["Comedy"],
      "people": [{"Name": "Tom Hanks"}],
      "exclude_people": [],
      "studios": ["A24"],
      "exclude_studios": [],
      "watched_status": "unplayed",
      "year_from": 1980,
      "year_to": 1989,
      "sort_by": "Random",
      "limit": 5,
      "duration_minutes": null
    }
  }
]
"""

def generate_blocks_from_prompt(prompt: str, api_key: str, available_shows: List[str], available_genres: List[str]) -> List[Dict]:
    """
    Takes a user's text prompt and uses the Gemini API to translate it
    into a structured list of playlist blocks.
    """
    if not api_key:
        raise ValueError("Gemini API key is not configured.")

    client = genai.Client(api_key=api_key)

    show_list = ", ".join(available_shows[:200])
    genre_list = ", ".join(available_genres)

    full_prompt = f"""
    You are an expert at creating Emby playlist blocks from user requests.
    Your response MUST be a valid JSON array of objects that strictly adheres to the provided schema.

    ### CRITICAL RULES:
    1. EXACT COUNTS: You must include exactly the number of different shows requested. Do not invent shows not on the list.
    2. INTERLEAVING: If the user asks for "A block" of multiple shows, return ONLY ONE JSON object in the array. List all requested shows inside the "shows" list of that single object, and set "interleave": true.
    3. NO BLANKS: Do NOT return empty or blank TV blocks to pad the array. Every object MUST have at least one show or filter.
    4. RANDOMIZATION: If the user asks for "random episodes," do not default to Season 1, Episode 1. Instead, pick a random Season (between 1 and 4) and a random Episode (between 1 and 10).
    
    ### CONTEXT:
    - Available TV shows include: {show_list}
    - Available movie genres are: {genre_list}

    ### SCHEMA TEMPLATE:
    {JSON_SCHEMA}

    Now, generate the JSON output based strictly on the user request below.

    User Request: "{prompt}"
    """

    try:
        response = client.models.generate_content(
            model='gemini-2.5-flash-lite',
            contents=full_prompt,
            config=types.GenerateContentConfig(
                response_mime_type="application/json",
                temperature=0.2  # Low temperature forces strict adherence to rules
            )
        )

        parsed_json = json.loads(response.text)

        if isinstance(parsed_json, list):
            valid_blocks = [
                block for block in parsed_json 
                if (block.get("type") == "tv" and block.get("shows")) or 
                   (block.get("type") == "movie" and block.get("filters"))
            ]
            
            if not valid_blocks:
                raise ValueError("AI generated blocks, but none contained valid shows or filters.")
                
            return valid_blocks
        else:
            raise ValueError("AI did not return a valid JSON array.")

    except json.JSONDecodeError as e:
        print(f"JSON Parsing Error: {e}")
        raise ConnectionError("The AI returned an invalid data format. Please try your request again.")
        
    except Exception as e:
        print(f"Gemini API Error: {e}")
        raise ConnectionError(f"Failed to process the request with the AI. Error: {e}")