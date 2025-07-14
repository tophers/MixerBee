import google.generativeai as genai
import json
from typing import List, Dict

# Updated schema with examples for both TV block modes.
JSON_SCHEMA = """
[
  {
    "type": "tv",
    "shows": [
      {
        "name": "Name of the TV Show",
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
    "type": "tv",
    "shows": [
      {
        "name": "Another Show",
        "season": 2,
        "episode": 1
      }
    ],
    "mode": "range",
    "end_season": 3,
    "end_episode": 12
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

    genai.configure(api_key=api_key)
    model = genai.GenerativeModel('gemini-1.5-flash-latest')

    show_list = ", ".join(available_shows[:200]) # Limit to avoid excessive length
    genre_list = ", ".join(available_genres)

    full_prompt = f"""
    You are an expert at creating Emby playlist blocks from user requests.
    Your response MUST be a valid JSON array of objects that strictly adheres to the following schema.
    Do not include any other text, explanations, or markdown formatting in your response.

    JSON Schema:
    {JSON_SCHEMA}

    Instructions:
    - For TV shows, if the user specifies a range (e.g., "season 1 to 3", "through episode 5"), use "mode": "range" and provide "end_season" and "end_episode".
    - Otherwise, for a specific number of episodes, use "mode": "count".
    - For Movie genres, use 'genres_any' for genres to include, 'genres_all' to require all specified genres, and 'genres_exclude' to ban genres.
    - For People, put their name in the 'people' or 'exclude_people' array as an object: {{"Name": "Person Name"}}.
    - For Studios, put the name in the 'studios' or 'exclude_studios' array as a string.

    Here is some context about the user's library:
    - Available TV shows include (but are not limited to): {show_list}
    - Available movie genres are: {genre_list}

    Now, based on the following user request, generate the JSON output.

    User Request: "{prompt}"
    """

    try:
        response = model.generate_content(full_prompt)
        cleaned_response = response.text.strip().replace("```json", "").replace("```", "")
        parsed_json = json.loads(cleaned_response)

        if isinstance(parsed_json, list):
            return parsed_json
        else:
            raise ValueError("AI did not return a valid list of blocks.")

    except Exception as e:
        print(f"Error calling Gemini API or parsing response: {e}")
        raise ConnectionError(f"Failed to get a valid response from the AI: {e}")