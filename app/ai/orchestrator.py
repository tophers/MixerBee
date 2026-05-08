"""
app/ai/orchestrator.py - AI multi-agent RAG orchestrator supporting Gemini and Ollama.
"""

import os
import json
import re
import requests
import time
from typing import List, Dict, Optional, Literal, Any
from pydantic import BaseModel, Field, field_validator, AliasChoices
from contextvars import ContextVar

import app_state
from .tools import AVAILABLE_TOOLS
from app.logger import get_logger, refresh_logger_level
from .vector_store import media_collection
from models import AiTweaks

logger = get_logger("MixerBee.AI")

ai_tweaks_context: ContextVar[Optional[AiTweaks]] = ContextVar("ai_tweaks", default=None)

try:
    from google import genai
    from google.genai import types
except ImportError:
    genai = None

class AIBlock(BaseModel):
    block_type: str = Field(
        validation_alias=AliasChoices('block_type', 'type', 'media_type', 'category'),
        description="The type of media: 'tv', 'movie', or 'music'"
    )

    ai_title: str = Field(
        default="Curated Mix",
        validation_alias=AliasChoices('ai_title', 'title', 'name'),
        description="A creative title for this specific block."
    )

    reasoning: str = Field(
        default="",
        description="Briefly explain which items you are including and which bad matches you explicitly threw away."
    )

    tv_shows: List[str] = Field(default=[], validation_alias=AliasChoices('tv_shows', 'shows', 'series_names', 'show_names'))
    tv_ids: List[str] = Field(default=[], validation_alias=AliasChoices('tv_ids', 'series_ids', 'show_ids'))
    tv_count: int = Field(default=3)

    movie_genres: List[str] = Field(default=[])
    movie_limit: int = Field(default=5)
    movie_year_from: int = Field(default=0)
    movie_year_to: int = Field(default=0)
    movie_people: List[str] = Field(default=[])
    movie_directors: List[str] = Field(default=[])
    movie_actors: List[str] = Field(default=[])
    movie_ids: List[str] = Field(default=[], validation_alias=AliasChoices('movie_ids', 'ids', 'item_ids'))

    music_mode: Literal["album", "artist_top", "artist_random", "genre"] = Field(default="genre")
    music_artist_id: str = Field(default="")
    music_genres: List[str] = Field(default=[])
    music_count: int = Field(default=15)

    @field_validator('block_type', mode='before')
    @classmethod
    def normalize_block_type(cls, v):
        if not isinstance(v, str): return "movie"
        v = v.lower()
        if any(x in v for x in ["tv", "show", "series", "episode"]): return "tv"
        if any(x in v for x in ["movie", "film"]): return "movie"
        if any(x in v for x in ["music", "audio", "song", "track"]): return "music"
        return v

    @field_validator('movie_ids', 'tv_ids', mode='before')
    @classmethod
    def coerce_ids_to_strings(cls, v):
        def clean(val):
            if val is None: return ""
            s = str(val).strip()
            match = re.search(r'\b([a-fA-F0-9]{32}|\d{3,15})\b', s)
            if match:
                return match.group(1)
            return ""

        if isinstance(v, list):
            return [c for item in v if (c := clean(item))]
        if v and isinstance(v, str):
            parts = [p.strip() for p in v.split(",")]
            return [c for p in parts if (c := clean(p))]
        return []

class EnrichmentResult(BaseModel):
    tags: List[str]

def _consolidate_blocks(blocks: List[Dict[str, Any]], target_size: int = 10) -> List[Dict[str, Any]]:
    if not blocks: return []
    movie_vibe = None
    tv_vibe = None
    music_vibe = None
    others = []
    for b in blocks:
        b_type = b.get('type')
        v_type = b.get('vibe_type') or b_type
        if v_type == 'movie':
            if not movie_vibe:
                movie_vibe = b
                movie_vibe['type'] = 'vibe'
                movie_vibe['vibe_type'] = 'movie'
            else:
                existing_ids = movie_vibe['filters'].get('ids', [])
                new_ids = b['filters'].get('ids', [])
                movie_vibe['filters']['ids'] = list(dict.fromkeys(existing_ids + new_ids))
                if movie_vibe.get('title') == "Curated Mix":
                    movie_vibe['title'] = b.get('title', "Curated Mix")
        elif v_type == 'tv':
            if not tv_vibe:
                tv_vibe = b
            else:
                tv_vibe['shows'] = tv_vibe.get('shows', []) + b.get('shows', [])
        elif b_type == 'music':
            if not music_vibe: music_vibe = b
        else:
            others.append(b)

    if movie_vibe and 'ids' in movie_vibe.get('filters', {}):
        movie_vibe['filters']['ids'] = movie_vibe['filters']['ids'][:target_size]

    if tv_vibe and 'shows' in tv_vibe:
        tv_vibe['shows'] = tv_vibe['shows'][:target_size]

    result = []
    if movie_vibe: result.append(movie_vibe)
    if tv_vibe: result.append(tv_vibe)
    if music_vibe: result.append(music_vibe)
    result.extend(others)
    return result

def _map_tv_block(ai_block: AIBlock) -> Optional[Dict[str, Any]]:
    active_tweaks = ai_tweaks_context.get()
    is_unwatched = active_tweaks.only_unwatched if active_tweaks else False

    shows = []
    if ai_block.tv_ids:
        shows = [{"id": tid, "unwatched": is_unwatched} for tid in ai_block.tv_ids if tid]
    elif ai_block.tv_shows:
        shows = [{"name": n, "season": 1, "episode": 1, "unwatched": is_unwatched} for n in ai_block.tv_shows if n and str(n).strip()]

    if not shows:
        return None

    return {
        "type": "tv", 
        "title": ai_block.ai_title,
        "is_ai_generated": True,
        "mode": "count",
        "count": ai_block.tv_count if ai_block.tv_count > 0 else 3,
        "interleave": True,
        "shows": shows
    }

def _map_movie_block(ai_block: AIBlock) -> Optional[Dict[str, Any]]:
    active_tweaks = ai_tweaks_context.get()
    is_unwatched = active_tweaks.only_unwatched if active_tweaks else False

    filters: Dict[str, Any] = {
        "watched_status": "unplayed" if is_unwatched else "all",
        "sort_by": "PremiereDate",
    }

    if ai_block.movie_ids:
        filters["ids"] = ai_block.movie_ids
        filters["limit"] = len(ai_block.movie_ids)
    else:
        filters["limit"] = ai_block.movie_limit

    if ai_block.movie_genres: filters["genres_any"] = ai_block.movie_genres
    if ai_block.movie_year_from > 0: filters["year_from"] = ai_block.movie_year_from
    if ai_block.movie_year_to > 0: filters["year_to"] = ai_block.movie_year_to

    people = [{"Name": n, "Role": "Person"} for n in ai_block.movie_people]
    people.extend([{"Name": n, "Role": "Director"} for n in ai_block.movie_directors])
    people.extend([{"Name": n, "Role": "Actor"} for n in ai_block.movie_actors])
    if people: filters["people"] = people

    if not any([ai_block.movie_ids, ai_block.movie_genres, people, ai_block.movie_year_from > 0, ai_block.ai_title]):
        return None

    is_vibe = bool(ai_block.movie_ids)
    return {
        "type": "vibe" if is_vibe else "movie",
        "vibe_type": "movie" if is_vibe else None,
        "title": ai_block.ai_title,
        "is_ai_generated": True,
        "filters": filters
    }

def _map_music_block(ai_block: AIBlock) -> Dict[str, Any]:
    return {
        "type": "music", "title": ai_block.ai_title, "is_ai_generated": True,
        "music": {
            "mode": ai_block.music_mode, "artistId": ai_block.music_artist_id, "count": ai_block.music_count,
            "filters": {"genres": ai_block.music_genres, "sort_by": "Random", "limit": ai_block.music_count}
        }
    }

def _map_to_frontend_block(ai_block: AIBlock) -> Optional[Dict[str, Any]]:
    bt = ai_block.block_type.lower()
    if any(x in bt for x in ["tv", "series", "show"]): return _map_tv_block(ai_block)
    if any(x in bt for x in ["movie", "film"]): return _map_movie_block(ai_block)
    if any(x in bt for x in ["music", "audio"]): return _map_music_block(ai_block)
    return None

def _get_ollama_tool_schema(func) -> Dict:
    schema = {
        "type": "function",
        "function": {
            "name": func.__name__,
            "description": func.__doc__.strip() if func.__doc__ else "No description.",
            "parameters": {"type": "object", "properties": {}, "required": []}
        }
    }

    if func.__name__ == "search_by_vibe":
        schema["function"]["parameters"]["properties"] = {
            "query": {"type": "string", "description": "The term, vibe, or concept to search for."},
            "media_type": {"type": "string", "description": "Optional format constraint. Must be 'Movie' or 'Series'."}
        }
        schema["function"]["parameters"]["required"].append("query")
    elif "query" in (func.__doc__ or "").lower() or "search" in func.__name__:
        schema["function"]["parameters"]["properties"]["query"] = {"type": "string", "description": "The term to search for."}
        schema["function"]["parameters"]["required"].append("query")

    return schema

def _call_ollama(messages: List[Dict], tools: list = None, json_schema: Dict = None, enable_thinking: bool = False, phase_name: str = "General", temperature: float = 0.2) -> Dict:
    url = f"{app_state.OLLAMA_URL}/api/chat"
    payload = {
        "model": app_state.OLLAMA_MODEL,
        "messages": messages,
        "stream": False,
        "options": {"temperature": temperature if not json_schema else 0.0, "seed": 42}
    }
    if enable_thinking: payload["options"]["num_predict"] = 2048
    if tools: payload["tools"] = [_get_ollama_tool_schema(t) for t in tools]
    if json_schema: payload["format"] = json_schema

    logger.info(f"--- OLLAMA REQUEST ({phase_name}) ---")

    timeout_val = getattr(app_state, 'OLLAMA_TIMEOUT', 120)

    resp = requests.post(url, json=payload, timeout=timeout_val)
    resp.raise_for_status()
    result = resp.json()

    msg = result.get("message", {})
    if enable_thinking and "content" in msg:
        thoughts = re.findall(r'<think>(.*?)</think>', msg["content"], re.DOTALL)
        if thoughts:
            logger.info(f"--- LLM THINKING ({phase_name}) ---")
            logger.info(thoughts[0].strip())
    if "tool_calls" in msg:
        logger.info(f"--- MODEL TOOL CALLS ({phase_name}) ---")
        logger.info(json.dumps(msg["tool_calls"], indent=2))
    return result

def _run_ollama_researcher(prompt: str, tweaks: AiTweaks) -> tuple[List[Dict[str, Any]], Dict[str, str]]:
    """
    Runs the Researcher phase and returns grouped results plus a strict ID-Type map.
    """
    system = """You are the MixerBee Concierge. Your job is to query the local database to find media matching the user's request.

    RULES:
    1. SPLIT YOUR QUERIES: If the user asks for multiple distinct concepts (e.g. "cyberpunk movies" AND "90s sitcoms"), you MUST make MULTIPLE SEPARATE tool calls. Do not combine them into one search.
    2. USE EXACT FILTERS: When calling search_by_vibe, use the 'media_type' argument to specify 'Movie' or 'Series' if the user asks for a specific format.
    3. KEEP IT SIMPLE: For the query string, only pass the core vibe/theme (e.g. "gritty cyberpunk" or "90s sitcom").
    """

    messages = [{"role": "system", "content": system}, {"role": "user", "content": prompt}]
    tool_map = {t.__name__: t for t in AVAILABLE_TOOLS}

    response = _call_ollama(messages, tools=AVAILABLE_TOOLS, enable_thinking=False, phase_name="Research Phase", temperature=tweaks.temperature)
    message = response.get("message", {})
    content = message.get("content", "")

    finding_groups = []
    id_type_map = {}

    if "tool_calls" in message and message["tool_calls"]:
        for call in message["tool_calls"]:
            func_name = call["function"]["name"]
            args = call["function"].get("arguments", {})
            if func_name in tool_map:
                try:
                    args.pop("limit", None)
                    args.pop("count", None)

                    logger.info(f"--- EXECUTING TOOL: {func_name} WITH ARGS: {args} ---")
                    result = tool_map[func_name](**args)

                    search_context = args.get("query", func_name)

                    summary = f"RESEARCH FINDINGS FOR '{search_context}':\n"
                    all_tool_results = []
                    if isinstance(result, list):
                        for r in result:
                            if isinstance(r, dict):
                                item_id = r.get("Id", "")
                                item_type = r.get("Type", "Movie")
                                if item_id:
                                    id_type_map[item_id] = item_type
                                    all_tool_results.append(r)
                            elif isinstance(r, str):
                                all_tool_results.append({"Id": "", "Name": r, "Type": "Series", "Year": "Unknown", "Genres": ""})

                    if all_tool_results:
                        seen_ids = set()
                        for r in all_tool_results:
                            item_id = r.get("Id", "")
                            name = r.get("Name", "Unknown")
                            dedup_key = item_id if item_id else name
                            if dedup_key not in seen_ids:
                                genres = r.get("Genres", "Unknown")
                                summary += f"- ID: \"{item_id}\" | Title: \"{name} ({r.get('Year', 'Unknown')})\" | Type: {r.get('Type', 'Unknown')} | Genres: {genres}\n"
                                seen_ids.add(dedup_key)

                        finding_groups.append({"query": search_context, "context": summary})
                except Exception as e:
                    logger.error(f"Tool failed: {e}")

    if content.strip() and (not finding_groups or len(content) > 100):
        logger.info("Researcher provided meaningful text content. Adding to Architect context.")
        finding_groups.append({"query": "Researcher Analysis", "context": content})

    return finding_groups, id_type_map

def _generate_with_ollama(prompt: str, tweaks: AiTweaks) -> tuple[List[Dict[str, Any]], str, List[str]]:
    logger.info(f"--- STARTING DIVIDE-AND-CONQUER GENERATION: '{prompt}' ---")

    finding_groups, id_type_map = _run_ollama_researcher(prompt, tweaks)
    
    logs = [f"Researcher initialized for: '{prompt}'"]

    if not finding_groups:
        msg = "Researcher found no items in your library matching that prompt within the current Relevancy Threshold."
        logger.warning(f"Researcher empty: {msg}")
        return [], f"ollama:{app_state.OLLAMA_MODEL}", [msg]

    strictness_rule = ""
    if tweaks.strictness == "genre_verified":
        strictness_rule = "4. GENRE FILTERING (CRITICAL): Check the 'Genres' field. If an item doesn't match the specific vibe of the group, discard it."
    else:
        strictness_rule = "4. VIBE FIRST CURATION: Trust the 'Found via' labels in the findings. If it was found for this group, keep it."

    builder_system = f"""You are the MixerBee Master Architect.
    Transform the specific research findings provided into a structured JSON block list.

    ### BLOCK LOGIC (IMPORTANT) ###
    - For TV, you will provide a list of Series IDs in 'tv_ids'.
    - You can set 'tv_count' to the number of sequential episodes you want to play per show (e.g. 2 or 3).
    - For Movies, provide Movie IDs in 'movie_ids'.
    - NEVER use titles in ID arrays. Use ONLY the raw numeric strings from the "ID:" field.

    ### RULES ###
    1. BLOCK GROUPING: Group all movies into ONE block. Group all TV shows into ONE block.
    2. QUANTITY: If the user requests a specific number of shows/movies, pick exactly that many from the findings.
    {strictness_rule}
    5. REASONING: Briefly explain your choices.

    Respond ONLY with raw JSON."""

    schema = {
        "type": "object",
        "properties": {
            "blocks": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "block_type": {"type": "string", "enum": ["tv", "movie", "music"]},
                        "ai_title": {"type": "string"},
                        "reasoning": {"type": "string"},
                        "tv_ids": {"type": "array", "items": {"type": "string"}},
                        "tv_shows": {"type": "array", "items": {"type": "string"}},
                        "tv_count": {"type": "integer"},
                        "movie_ids": {"type": "array", "items": {"type": "string"}},
                        "music_mode": {"type": "string", "enum": ["album", "artist_top", "artist_random", "genre"]},
                        "music_genres": {"type": "array", "items": {"type": "string"}},
                        "music_count": {"type": "integer"}
                    },
                    "required": ["block_type", "ai_title", "reasoning"]
                }
            }
        },
        "required": ["blocks"]
    }

    all_generated_blocks = []

    for group in finding_groups:
        query_text = group['query']
        group_context = group['context']

        logger.info(f"--- ARCHITECT PROCESSING GROUP: '{query_text}' ---")

        messages = [
            {"role": "system", "content": builder_system},
            {"role": "user", "content": f"USER PROMPT: {prompt}\n\nCURRENT FINDINGS GROUP: {query_text}\n\n{group_context}"}
        ]

        try:
            response = _call_ollama(messages, json_schema=schema, enable_thinking=False, phase_name=f"Architect ({query_text})", temperature=0.0)
            raw_content = response["message"]["content"]
            data = json.loads(raw_content)

            if not data.get("blocks"):
                logger.warning(f"Architect returned valid JSON but 0 blocks. Raw content: {raw_content}")

            for b_data in data.get("blocks", []):
                valid_movies, valid_tv = [], []
                raw_ids = b_data.get("movie_ids", []) + b_data.get("tv_ids", [])

                for rid in raw_ids:
                    actual_type = id_type_map.get(rid)
                    if actual_type == "Series" or (actual_type is None and b_data.get("block_type") == "tv"):
                        valid_tv.append(rid)
                    else:
                        valid_movies.append(rid)

                if valid_movies or b_data.get("movie_genres"):
                    m_block = b_data.copy()
                    m_block.update({
                        "block_type": "movie",
                        "movie_ids": valid_movies,
                        "tv_ids": [],
                        "tv_shows": []
                    })
                    if (fb := _map_to_frontend_block(AIBlock(**m_block))):
                        all_generated_blocks.append(fb)

                if valid_tv or b_data.get("tv_shows"):
                    t_block = b_data.copy()
                    t_block.update({
                        "block_type": "tv",
                        "tv_ids": valid_tv,
                        "movie_ids": [],
                        "movie_genres": [],
                        "tv_count": b_data.get("tv_count", 3)
                    })
                    if (fb := _map_to_frontend_block(AIBlock(**t_block))):
                        all_generated_blocks.append(fb)

        except Exception as e:
            logger.error(f"Failed to process group '{query_text}': {e}")

    final_list = _consolidate_blocks(all_generated_blocks, target_size=tweaks.target_size)

    if not final_list:
        logs.append("No matches were validated for the final block list.")
    else:
        logs.append(f"Successfully generated {len(final_list)} consolidated blocks.")

    logger.info(f"--- SUCCESS: Generated {len(final_list)} consolidated blocks ---")
    return final_list, f"ollama:{app_state.OLLAMA_MODEL}", logs

def _generate_with_gemini(prompt: str, tweaks: AiTweaks) -> tuple[List[Dict[str, Any]], str, List[str]]:
    if not app_state.GEMINI_API_KEY: raise ValueError("Gemini key missing.")
    client = genai.Client(api_key=app_state.GEMINI_API_KEY)
    model_name = os.environ.get("GEMINI_MODEL", "gemini-2.5-flash")
    logger.info(f"--- STARTING GEMINI GENERATION: '{prompt}' ---")
    
    logs = [f"Gemini processing request: '{prompt}'"]

    strictness_rule = ""
    if tweaks.strictness == "genre_verified":
        strictness_rule = "4. GENRE FILTERING: Use the provided 'Genres' to filter out bad matches. Keep all the good matches!"
    else:
        strictness_rule = "4. VIBE FIRST: Trust the 'Found via' labels. If an item is labeled as found via the requested vibe, keep it regardless of standard genre tags."

    system_instruction = f"""You are a Research assistant and Master Architect.

    ### TV BLOCK LOGIC ###
    - Provide Series IDs in 'tv_ids'.
    - Set 'tv_count' to the number of sequential episodes to watch per show (e.g. 2 or 3).

    ### RULES ###
    1. SPLIT QUERIES: Make multiple separate tool calls for disparate things.
    2. BLOCK GROUPING: Group all movies into ONE block. Group all TV shows into ONE block.
    3. QUANTITY: If the user requests a specific number of shows/movies, pick exactly that many from the findings.
    4. TYPE MATCHING: "Type: Series" -> "tv" block (tv_ids). "Type: Movie" -> "movie" block (movie_ids).
    {strictness_rule}
    6. POPULATE IDs: You MUST output the raw numeric IDs in the 'movie_ids' or 'tv_ids' arrays. DO NOT put titles in the ID arrays!
    """

    chat = client.chats.create(
        model=model_name,
        config=types.GenerateContentConfig(
            system_instruction=system_instruction,
            tools=AVAILABLE_TOOLS,
            temperature=tweaks.temperature
        )
    )
    research_response = chat.send_message(prompt)
    logger.info(f"--- GEMINI FINDINGS ---\n{research_response.text}")
    
    # Simple heuristic to see if research found nothing
    if not any(char.isdigit() for char in research_response.text):
        msg = "Researcher found no matching IDs in your library. Try Relaxing Relevancy."
        return [], model_name, [msg]

    builder_response = client.models.generate_content(
        model=model_name,
        contents=f"User Request: {prompt}\n\nContext: {research_response.text}",
        config=types.GenerateContentConfig(
            response_mime_type="application/json",
            response_schema=list[AIBlock],
            temperature=0.0
        )
    )
    if not builder_response or not builder_response.parsed: 
        return [], model_name, ["Architect failed to parse results."]

    valid_blocks = [fb for b in builder_response.parsed if (fb := _map_to_frontend_block(b)) is not None]
    final_list = _consolidate_blocks(valid_blocks, target_size=tweaks.target_size)
    
    if not final_list:
        logs.append("No library items were close enough to the request to be included.")
    else:
        logs.append(f"Successfully generated {len(final_list)} blocks.")

    return final_list, model_name, logs

def generate_smart_blocks(prompt: str, tweaks: Optional[AiTweaks] = None) -> tuple[List[Dict[str, Any]], str, List[str]]:
    refresh_logger_level()
    actual_tweaks = tweaks or AiTweaks()
    token = ai_tweaks_context.set(actual_tweaks)

    try:
        if app_state.AI_PROVIDER == "ollama":
            return _generate_with_ollama(prompt, actual_tweaks)
        return _generate_with_gemini(prompt, actual_tweaks)
    finally:
        ai_tweaks_context.reset(token)

def process_enrichment_queue(batch_size: int, timeout: int) -> Dict[str, Any]:
    """Pulls a batch of un-enriched media, calls the LLM for vibe tags, and updates the Vector DB."""
    refresh_logger_level()
    logger.info(f"--- STARTING METADATA ENRICHMENT (Batch: {batch_size}) ---")

    try:
        unprocessed = media_collection.get(
            where={"is_enriched": False},
            limit=batch_size
        )

        if not unprocessed or not unprocessed['ids']:
            logger.info("Enrichment queue is empty. Library is 100% enriched.")
            return {"status": "ok", "processed": 0, "success": 0, "log": ["Queue is empty. Library fully enriched."]}

        ids = unprocessed['ids']
        metadatas = unprocessed['metadatas']
        success_count = 0

        for i, item_id in enumerate(ids):
            meta = metadatas[i]
            title = meta.get('name', 'Unknown')
            overview = meta.get('overview', 'No summary available.')
            logger.info(f"Enriching [{i+1}/{len(ids)}]: {title}")
            prompt = f"Analyze Title: '{title}' Summary: '{overview}'. Return 5-12 highly specific vibe tags in English ONLY for visual style, emotional tone, and pacing. Avoid generic filler (e.g., 'action', 'intense', 'fast-paced') unless absolute defining traits. Focus on unique descriptors (e.g., 'noir', 'brutalist', 'melancholic'). If summary is brief, provide fewer tags. Output strictly as JSON: {{\"tags\": [\"tag1\", \"tag2\"]}}."

            schema = {
                "type": "object",
                "properties": {"tags": {"type": "array", "items": {"type": "string"}}},
                "required": ["tags"]
            }

            try:
                vibe_tags_str = ""
                if app_state.AI_PROVIDER == "ollama":
                    messages = [
                        {"role": "system", "content": "You are a media tagging AI. Output only raw JSON."},
                        {"role": "user", "content": prompt}
                    ]
                    url = f"{app_state.OLLAMA_URL}/api/chat"
                    payload = {
                        "model": app_state.OLLAMA_MODEL,
                        "messages": messages,
                        "stream": False,
                        "format": schema,
                        "options": {"temperature": 0.0}
                    }
                    resp = requests.post(url, json=payload, timeout=timeout)
                    resp.raise_for_status()
                    result = resp.json()
                    content = result["message"]["content"]
                    parsed = json.loads(content)
                    vibe_tags_str = ", ".join(parsed.get("tags", []))
                else:
                    if not app_state.GEMINI_API_KEY: raise ValueError("Gemini API Key missing")
                    model_name = os.environ.get("GEMINI_MODEL", "gemini-2.5-flash")
                    client = genai.Client(api_key=app_state.GEMINI_API_KEY)
                    resp = client.models.generate_content(
                        model=model_name,
                        contents=prompt,
                        config=types.GenerateContentConfig(
                            response_mime_type="application/json",
                            response_schema=EnrichmentResult,
                            temperature=0.0
                        )
                    )
                    if not resp or not resp.parsed: raise ValueError("Gemini returned invalid response.")
                    vibe_tags_str = ", ".join(resp.parsed.tags)

                if vibe_tags_str:
                    meta['is_enriched'] = True
                    meta['vibe_tags'] = vibe_tags_str
                    text_to_embed = f"Title: {title}. Year: {meta.get('year')}. Type: {meta.get('type')}. Genres: {meta.get('genres')}. Style: {vibe_tags_str}. Summary: {overview}"
                    media_collection.update(ids=[item_id], metadatas=[meta], documents=[text_to_embed])
                    success_count += 1
                    logger.info(f"  -> Tags: {vibe_tags_str}")
            except Exception as e:
                logger.error(f"  -> Failed to enrich {title}: {e}")

        log_msg = f"Enrichment batch complete. Successfully processed {success_count}/{len(ids)} items."
        logger.info(log_msg)
        return {"status": "ok", "processed": len(ids), "success": success_count, "log": [log_msg]}
    except Exception as e:
        logger.error(f"Enrichment queue failed: {e}", exc_info=True)
        return {"status": "error", "log": [str(e)]}
