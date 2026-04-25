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

import app_state
from .tools import AVAILABLE_TOOLS
from app.logger import get_logger, refresh_logger_level
from .vector_store import media_collection

logger = get_logger("MixerBee.AI")

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

    tv_shows: List[str] = Field(default=[], validation_alias=AliasChoices('tv_shows', 'shows', 'series_names', 'show_names'))
    tv_ids: List[str] = Field(default=[], validation_alias=AliasChoices('tv_ids', 'series_ids', 'show_ids'))
    tv_count: int = Field(default=3)
    tv_unwatched: bool = Field(default=False)

    movie_genres: List[str] = Field(default=[])
    movie_limit: int = Field(default=5)
    movie_year_from: int = Field(default=0)
    movie_year_to: int = Field(default=0)
    movie_people: List[str] = Field(default=[])
    movie_directors: List[str] = Field(default=[])
    movie_actors: List[str] = Field(default=[])
    movie_ids: List[str] = Field(default=[], validation_alias=AliasChoices('movie_ids', 'ids', 'item_ids'))
    movie_unwatched: bool = Field(default=False)

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

def _consolidate_blocks(blocks: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
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
                movie_vibe['filters']['ids'] = list(set(movie_vibe['filters'].get('ids', []) + b['filters'].get('ids', [])))
                for key in ["year_from", "year_to", "genres_any"]:
                    if b['filters'].get(key) and not movie_vibe['filters'].get(key):
                        movie_vibe['filters'][key] = b['filters'][key]
        elif v_type == 'tv':
            if not tv_vibe:
                tv_vibe = b
                tv_vibe['type'] = 'vibe'
                tv_vibe['vibe_type'] = 'tv'
            else:
                tv_vibe['shows'] = tv_vibe.get('shows', []) + b.get('shows', [])
        elif b_type == 'music':
            if not music_vibe: music_vibe = b
        else:
            others.append(b)
    result = []
    if movie_vibe: result.append(movie_vibe)
    if tv_vibe: result.append(tv_vibe)
    if music_vibe: result.append(music_vibe)
    result.extend(others)
    return result

def _map_tv_block(ai_block: AIBlock) -> Optional[Dict[str, Any]]:
    shows = []
    if ai_block.tv_ids:
        shows = [{"id": tid, "unwatched": ai_block.tv_unwatched} for tid in ai_block.tv_ids]
    elif ai_block.tv_shows:
        shows = [{"name": n, "season": 1, "episode": 1, "unwatched": ai_block.tv_unwatched} for n in ai_block.tv_shows]

    if not shows:
        if not ai_block.ai_title: return None
        shows = [{"name": "", "season": 1, "episode": 1, "unwatched": ai_block.tv_unwatched}]

    is_vibe = bool(ai_block.tv_ids)
    return {
        "type": "vibe" if is_vibe else "tv",
        "vibe_type": "tv" if is_vibe else None,
        "title": ai_block.ai_title,
        "is_ai_generated": True,
        "mode": "count",
        "count": ai_block.tv_count,
        "interleave": True,
        "shows": shows
    }

def _map_movie_block(ai_block: AIBlock) -> Optional[Dict[str, Any]]:
    filters: Dict[str, Any] = {
        "watched_status": "unplayed" if ai_block.movie_unwatched else "all",
        "sort_by": "Random",
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
    if "query" in (func.__doc__ or "").lower() or "search" in func.__name__:
        schema["function"]["parameters"]["properties"]["query"] = {"type": "string", "description": "The term to search for."}
        schema["function"]["parameters"]["required"].append("query")
    return schema

def _call_ollama(messages: List[Dict], tools: list = None, json_schema: Dict = None, enable_thinking: bool = False, phase_name: str = "General") -> Dict:
    url = f"{app_state.OLLAMA_URL}/api/chat"
    payload = {
        "model": app_state.OLLAMA_MODEL,
        "messages": messages,
        "stream": False,
        "options": {"temperature": 0.2 if not json_schema else 0.0, "seed": 42}
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

def _run_ollama_researcher(prompt: str) -> str:
    system = """You are the MixerBee Concierge. Your job is to query the local database to find media matching the user's request.

    RULES:
    1. USE TOOLS: You MUST use 'search_by_vibe' for moods/themes/eras, or 'verify_tv_show' for specific titles.
    2. VIBE MATCHING: Pay close attention to the requested era/year in the prompt (e.g. "90s", "2024").
    """

    messages = [{"role": "system", "content": system}, {"role": "user", "content": prompt}]
    tool_map = {t.__name__: t for t in AVAILABLE_TOOLS}
    
    all_tool_results = []
    
    response = _call_ollama(messages, tools=AVAILABLE_TOOLS, enable_thinking=False, phase_name="Research Phase")
    message = response.get("message", {})
    
    if "tool_calls" in message and message["tool_calls"]:
        for call in message["tool_calls"]:
            func_name = call["function"]["name"]
            args = call["function"].get("arguments", {})
            if func_name in tool_map:
                try:
                    logger.info(f"--- EXECUTING TOOL: {func_name} ---")
                    result = tool_map[func_name](**args)
                    
                    if isinstance(result, list):
                        for r in result:
                            if isinstance(r, dict):
                                all_tool_results.append(r)
                            elif isinstance(r, str):
                                all_tool_results.append({"Id": "", "Name": r, "Type": "Series", "Year": "Unknown"})
                except Exception as e:
                    logger.error(f"Tool failed: {e}")
                        
        if all_tool_results:
            summary = "EXACT MEDIA MATCHES FOUND IN DATABASE:\n"
            seen_ids = set()
            for r in all_tool_results:
                item_id = r.get("Id", "")
                name = r.get("Name", "Unknown")
                
                dedup_key = item_id if item_id else name
                if dedup_key not in seen_ids:
                    summary += f"- [ID: {item_id}] {name} ({r.get('Year', 'Unknown')}) - {r.get('Type', 'Unknown')}\n"
                    seen_ids.add(dedup_key)
            return summary
            
    return message.get("content", "No matching media found.")

def _generate_with_ollama(prompt: str) -> tuple[List[Dict[str, Any]], str]:
    logger.info(f"--- STARTING SMART BLOCK GENERATION: '{prompt}' ---")
    context = _run_ollama_researcher(prompt)
    logger.info(f"--- FINAL RESEARCH CONTEXT GIVEN TO ARCHITECT ---\n{context}")

    builder_system = """You are the MixerBee Master Architect.
    Convert the research findings into a strict JSON block list.

    MANDATORY RULES:
    1. USE EXACT IDs: Extract the EXACT internal server ID from the brackets (e.g., from [ID: 85601] extract "85601") for 'movie_ids' or 'tv_ids'. Output ONLY the raw numerical ID string.
    2. NO HALLUCINATIONS: If an item does not have an ID in the research, DO NOT include it. NEVER make up sequential IDs.
    3. BLOCK GROUPING: Group all movies into a SINGLE block (block_type: "movie"), and all TV shows into a SINGLE block (block_type: "tv"). Do not make a separate block for every single item.
    4. NO CHAT: Respond ONLY with the raw JSON object."""

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
                        "tv_shows": {"type": "array", "items": {"type": "string"}},
                        "tv_ids": {"type": "array", "items": {"type": "string"}},
                        "tv_count": {"type": "integer"},
                        "tv_unwatched": {"type": "boolean"},
                        "movie_genres": {"type": "array", "items": {"type": "string"}},
                        "movie_limit": {"type": "integer"},
                        "movie_year_from": {"type": "integer"},
                        "movie_year_to": {"type": "integer"},
                        "movie_ids": {"type": "array", "items": {"type": "string"}},
                        "movie_unwatched": {"type": "boolean"},
                        "music_mode": {"type": "string", "enum": ["album", "artist_top", "artist_random", "genre"]},
                        "music_artist_id": {"type": "string"},
                        "music_genres": {"type": "array", "items": {"type": "string"}},
                        "music_count": {"type": "integer"}
                    },
                    "required": ["block_type", "ai_title"]
                }
            }
        },
        "required": ["blocks"]
    }

    messages = [{"role": "system", "content": builder_system}, {"role": "user", "content": f"USER REQUEST: {prompt}\n\nRESEARCH FINDINGS:\n{context}"}]
    response = _call_ollama(messages, json_schema=schema, enable_thinking=False, phase_name="JSON Architect")
    raw_content = response["message"]["content"]
    logger.info(f"--- RAW JSON FROM ARCHITECT ---\n{raw_content}")

    try:
        data = json.loads(raw_content)
        block_list = data.get("blocks", [])
        parsed_blocks = [AIBlock(**b) for b in block_list]
        mapped_blocks = [fb for b in parsed_blocks if (fb := _map_to_frontend_block(b)) is not None]
        final_list = _consolidate_blocks(mapped_blocks)
        logger.info(f"--- SUCCESS: Generated {len(final_list)} blocks ---")
        return final_list, f"ollama:{app_state.OLLAMA_MODEL}"
    except Exception as e:
        logger.error(f"Ollama Build Error: {e}")
        raise ValueError(f"Failed to generate blocks: {e}")

def _generate_with_gemini(prompt: str) -> tuple[List[Dict[str, Any]], str]:
    if not app_state.GEMINI_API_KEY: raise ValueError("Gemini key missing.")
    client = genai.Client(api_key=app_state.GEMINI_API_KEY)
    model_name = os.environ.get("GEMINI_MODEL", "gemini-2.5-flash")
    logger.info(f"--- STARTING GEMINI GENERATION: '{prompt}' ---")
    chat = client.chats.create(model=model_name, config=types.GenerateContentConfig(system_instruction="Research assistant. Use real library IDs.", tools=AVAILABLE_TOOLS, temperature=0.0))
    research_response = chat.send_message(prompt)
    logger.info(f"--- GEMINI FINDINGS ---\n{research_response.text}")
    builder_response = client.models.generate_content(model=model_name, contents=f"User Request: {prompt}\n\nContext: {research_response.text}", config=types.GenerateContentConfig(response_mime_type="application/json", response_schema=list[AIBlock], temperature=0.0))
    if not builder_response or not builder_response.parsed: raise ValueError("Gemini failed.")
    valid_blocks = [fb for b in builder_response.parsed if (fb := _map_to_frontend_block(b)) is not None]
    return valid_blocks, model_name

def generate_smart_blocks(prompt: str) -> tuple[List[Dict[str, Any]], str]:
    refresh_logger_level()
    if app_state.AI_PROVIDER == "ollama": return _generate_with_ollama(prompt)
    return _generate_with_gemini(prompt)

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
                "properties": {
                    "tags": {"type": "array", "items": {"type": "string"}}
                },
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
                    if not app_state.GEMINI_API_KEY:
                        raise ValueError("Gemini API Key missing")
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
                    if not resp or not resp.parsed:
                        raise ValueError("Gemini returned empty or invalid response.")
                    vibe_tags_str = ", ".join(resp.parsed.tags)
                    
                if not vibe_tags_str:
                    raise ValueError("Empty tags returned")
                    
                meta['is_enriched'] = True
                meta['vibe_tags'] = vibe_tags_str
                
                text_to_embed = f"Title: {title}. Year: {meta.get('year')}. Type: {meta.get('type')}. Genres: {meta.get('genres')}. Style: {vibe_tags_str}. Summary: {overview}"
                
                media_collection.update(
                    ids=[item_id],
                    metadatas=[meta],
                    documents=[text_to_embed]
                )
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
