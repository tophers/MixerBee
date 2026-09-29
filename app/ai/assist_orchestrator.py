"""
app/ai/assist_orchestrator.py - Conversational Playlist Assist turn runner.

Playlist Assist is a chat loop over a flat list of movies (the "canvas"), not over
the Builder's block definitions. One turn takes the current canvas plus a prompt and
returns a revised canvas, a chat reply, and suggested title/description.

Phase 1 is strictly movies: resolving a Series into episodes or an Album into tracks
is deliberately out of scope, so every tool and every prompt here is movie-only.
"""

import json
import os
import re
import time
from typing import Any, Dict, List, Optional

import requests

from app.logger import get_logger, refresh_logger_level
from app.media_client import current_media, media_operation, media_scope
from .tools import (
    ASSIST_TOOLS,
    ASSIST_VIBE_TOOL,
    MAX_ASSIST_TITLES,
    MAX_ASSIST_VIBE_COUNT,
    MAX_ASSIST_METADATA_IDS,
    bind_tools,
    get_movie_metadata,
    in_year_window,
    resolve_movies,
)
from .vector_store import media_collection

logger = get_logger("MixerBee.AI.Assist")

try:
    from google import genai
    from google.genai import types
except ImportError:
    genai = None


# --- Hard limits (§2 Safety & Guardrails) ---------------------------------
# Every one of these bounds a cost the LLM would otherwise choose for itself.
MAX_TOOL_INVOCATIONS = 5          # cumulative across the whole turn
MAX_PLAYLIST_SIZE = 50            # non-pinned items only; pins always win
MAX_HISTORY_MESSAGES = 12         # trailing chat turns replayed to the model
MAX_HISTORY_CHARS = 6000          # total characters of replayed history
MAX_PROMPT_CHARS = 2000
MAX_OUTPUT_TOKENS = 2048
TURN_DEADLINE_SECONDS = 120       # hard wall-clock ceiling for one turn

MAX_TITLE_CHARS = 120
MAX_DESCRIPTION_CHARS = 500
MAX_CHAT_RESPONSE_CHARS = 1200


class AssistError(RuntimeError):
    """Raised for conditions the router turns into a 4xx/5xx with a real message."""


class AssistPinUnavailable(AssistError):
    """A pinned item is no longer served by the media server, so the turn is void."""


def vibe_search_available(media) -> bool:
    """True when this connection actually has a populated vector index.

    Deliberately not connection_needs_index(): that tracks process-local state and
    reports True for every connection right after a restart, which would disable
    vibe search on every boot even with a fully populated index on disk.
    """
    try:
        with media_scope(media):
            return media_collection.count() > 0
    except Exception as e:
        logger.warning("Could not determine vibe index state: %s", e)
        return False


def assist_availability(media) -> Dict[str, Any]:
    """What the UI needs to decide between the pane, the setup gate, and hiding Assist.

    Availability comes from the shared account/connection policy rather than a third
    private reading of ai_settings. Assist stays unavailable without a provider even
    though one of its tools is semantic search: the conversation itself needs a model.
    """
    from app.ai_policy import capability_for_connection
    caps = capability_for_connection(media.connection.id)
    available = caps["generative_ai_available"]
    payload = {
        "ai_configured": available,
        "provider": str((media.connection.ai_settings or {}).get("AI_PROVIDER") or ""),
        "max_playlist_size": MAX_PLAYLIST_SIZE,
    } | caps
    # Only touch the vector store when the pane will actually be shown: a status call
    # must be answerable without opening Chroma for a disabled or unconfigured account.
    payload["vibe_available"] = available and vibe_search_available(media)
    return payload


class TurnLedger:
    """Records every library ID the tools actually returned during one turn.

    The curator is only allowed to emit IDs that are already on the canvas or that
    a tool surfaced here. Without this the model can pass through incidental search
    noise -- asking for "Tank Girl" also matches "Stolen Girl" -- or simply invent a
    plausible-looking ID, and the item lands in the playlist because it happens to
    resolve on the server.
    """

    def __init__(self):
        self.seen_ids = set()

    def wrap(self, tools: List) -> List:
        from functools import wraps

        def instrument(tool):
            @wraps(tool)
            def call(*args, **kwargs):
                result = tool(*args, **kwargs)
                if isinstance(result, list):
                    for row in result:
                        if isinstance(row, dict) and row.get("Id"):
                            self.seen_ids.add(str(row["Id"]))
                return result
            return call

        return [instrument(t) for t in tools]


def _tools_for_turn(media) -> List:
    """Drop vibe search entirely when there is no index to search."""
    if vibe_search_available(media):
        return list(ASSIST_TOOLS)
    logger.info("Vibe index empty for this connection; omitting semantic_movie_vibe_search.")
    return [t for t in ASSIST_TOOLS if t is not ASSIST_VIBE_TOOL]


# --- Ollama tool schemas ---------------------------------------------------
# Gemini infers these from the callables; Ollama will not, so they are written out
# explicitly. Keep this map in lockstep with the signatures in tools.py.
_ASSIST_OLLAMA_SCHEMAS: Dict[str, Dict[str, Any]] = {
    "batch_find_movies": {
        "type": "object",
        "properties": {
            "titles": {
                "type": "array",
                "items": {"type": "string"},
                "description": f"Movie titles to look up (at most {MAX_ASSIST_TITLES}).",
            }
        },
        "required": ["titles"],
    },
    "semantic_movie_vibe_search": {
        "type": "object",
        "properties": {
            "prompt": {"type": "string", "description": "The vibe, mood or theme to search for."},
            "count": {
                "type": "integer",
                "description": f"How many movies to return (1-{MAX_ASSIST_VIBE_COUNT}).",
            },
            "year_from": {
                "type": "integer",
                "description": "Earliest release year to allow, e.g. 1990 for the 90s. 0 for no limit.",
            },
            "year_to": {
                "type": "integer",
                "description": "Latest release year to allow, e.g. 1999 for the 90s. 0 for no limit.",
            },
        },
        "required": ["prompt"],
    },
    "get_movie_metadata": {
        "type": "object",
        "properties": {
            "ids": {
                "type": "array",
                "items": {"type": "string"},
                "description": f"Library IDs to describe (at most {MAX_ASSIST_METADATA_IDS}).",
            }
        },
        "required": ["ids"],
    },
}


def _get_assist_ollama_tool_schema(func) -> Dict[str, Any]:
    """Explicit JSON schema for one assist tool, as Ollama's /api/chat expects.

    Gemini derives the same shape from the callable's annotations. Nothing keeps the
    two in step on its own, so the hand-written schema is checked against the real
    signature here and a mismatch fails loudly instead of quietly denying the Ollama
    path an argument Gemini can use.
    """
    params = _ASSIST_OLLAMA_SCHEMAS.get(func.__name__)
    if params is None:
        raise AssistError(
            f"Assist tool '{func.__name__}' has no Ollama schema. "
            "Add one to _ASSIST_OLLAMA_SCHEMAS alongside the callable."
        )

    import inspect
    signature = set(inspect.signature(func).parameters)
    declared = set(params.get("properties", {}))
    if signature != declared:
        raise AssistError(
            f"Ollama schema for '{func.__name__}' is out of sync with its signature: "
            f"missing {sorted(signature - declared)}, extra {sorted(declared - signature)}."
        )

    return {
        "type": "function",
        "function": {
            "name": func.__name__,
            "description": (func.__doc__ or "No description.").strip(),
            "parameters": params,
        },
    }


ASSIST_RESPONSE_SCHEMA = {
    "type": "object",
    "properties": {
        "chat_response": {"type": "string"},
        "suggested_title": {"type": "string"},
        "suggested_description": {"type": "string"},
        "movie_ids": {"type": "array", "items": {"type": "string"}},
        # Declared by the model, enforced by the backend. Asking a small local model
        # to apply a release-year predicate across a dozen items by hand is
        # unreliable; asking it to name the window and doing the arithmetic here is
        # not. 0 means "no constraint".
        "year_from": {"type": "integer"},
        "year_to": {"type": "integer"},
    },
    "required": ["chat_response", "suggested_title", "suggested_description", "movie_ids"],
}


# --- Prompt construction ---------------------------------------------------

def _render_canvas(items: List[Dict[str, Any]]) -> str:
    if not items:
        return "(The playlist is currently empty.)"
    lines = []
    for idx, it in enumerate(items, start=1):
        pin = " [PINNED — must stay]" if it.get("locked") else ""
        year = it.get("Year") or "Unknown"
        genres = it.get("Genres") or ""
        line = f'{idx}. ID: "{it.get("Id", "")}" | "{it.get("Name", "Unknown")} ({year})"'
        if genres:
            line += f" | Genres: {genres}"
        lines.append(line + pin)
    return "\n".join(lines)


def _system_prompt(vibe_available: bool) -> str:
    vibe_line = (
        "- semantic_movie_vibe_search: find movies by mood/theme when the user is vague.\n"
        "  Pass year_from/year_to whenever the user named a period, so the search only\n"
        "  returns films from it."
        if vibe_available else
        "- (Vibe search is unavailable for this library. Work from titles you name yourself\n"
        "  and verify them with batch_find_movies.)"
    )
    return f"""You are the MixerBee Playlist Assistant. You help the user shape ONE playlist
of MOVIES through conversation.

### HARD CONSTRAINTS ###
1. MOVIES ONLY. You cannot add TV episodes, albums or songs. If the user asks for
   them, say so plainly in your chat response and do the movie part of the request.
2. Every movie you include MUST be identified by a library ID you obtained from a
   tool call in this conversation, or an ID already present in the CURRENT PLAYLIST.
   Never invent an ID and never put a title in the ID list.
3. PINNED items must appear in your output. The user has locked them.
4. THIS IS A REVISION. Re-emit the CURRENT PLAYLIST unchanged except where the
   user's request applies. Removing something the user did not ask about is a bug.
5. Aim for at most {MAX_PLAYLIST_SIZE} movies unless pinned items push it higher.

### TOOLS ###
- batch_find_movies: resolve named titles to library IDs. Batch them into one call.
{vibe_line}
- get_movie_metadata: check year/genre/runtime facts for IDs you already have.
You may make at most {MAX_TOOL_INVOCATIONS} tool calls in total, so batch your work.

### RELEASE YEARS ###
If the user's request involves a release period ("90s", "made before 2000", "not
from the 80s or 90s"), set year_from and year_to to that window -- 1990/1999 for
"the 90s", 1980/1999 for "the 80s or 90s". MixerBee enforces the window exactly and
drops anything outside it, so you do not have to filter by year yourself. Leave both
at 0 when the user said nothing about release dates.

### OUTPUT ###
Respond with JSON only:
- chat_response: a short, friendly sentence or two describing what you changed.
- suggested_title: a playlist name.
- suggested_description: one or two sentences of blurb.
- movie_ids: the complete, ordered list of library IDs for the revised playlist.
- year_from / year_to: the release window, or 0 and 0 for no constraint."""


def _user_message(prompt: str, items: List[Dict[str, Any]], findings: str) -> str:
    return (
        f"### CURRENT PLAYLIST ###\n{_render_canvas(items)}\n\n"
        f"### RESEARCH FINDINGS ###\n{findings or '(no searches were run)'}\n\n"
        f"### USER REQUEST ###\n{prompt}"
    )


def _trim_history(chat_history: Optional[List[Dict[str, Any]]]) -> List[Dict[str, str]]:
    """Keep the tail of the conversation within both a message and a character budget."""
    trimmed: List[Dict[str, str]] = []
    budget = MAX_HISTORY_CHARS
    for entry in reversed((chat_history or [])[-MAX_HISTORY_MESSAGES:]):
        role = "assistant" if str(entry.get("role")) == "assistant" else "user"
        content = str(entry.get("content") or "").strip()
        if not content:
            continue
        if len(content) > budget:
            break
        budget -= len(content)
        trimmed.append({"role": role, "content": content})
    trimmed.reverse()
    return trimmed


# --- Ollama path -----------------------------------------------------------

def _ollama_settings() -> Dict[str, Any]:
    ai = current_media().connection.ai_settings or {}
    return {
        "url": ai.get("OLLAMA_URL", "http://localhost:11434"),
        "model": ai.get("OLLAMA_MODEL", "qwen2.5:7b"),
        "timeout": ai.get("OLLAMA_TIMEOUT", 120),
    }


def _call_ollama(messages, tools=None, json_schema=None, phase="Assist", remaining=None):
    cfg = _ollama_settings()
    payload = {
        "model": cfg["model"],
        "messages": messages,
        "stream": False,
        "options": {"temperature": 0.0 if json_schema else 0.2,
                    "num_predict": MAX_OUTPUT_TOKENS},
    }
    if tools:
        payload["tools"] = [_get_assist_ollama_tool_schema(t) for t in tools]
    if json_schema:
        payload["format"] = json_schema

    timeout = cfg["timeout"]
    if remaining is not None:
        timeout = max(5, min(timeout, int(remaining)))

    logger.info("--- OLLAMA ASSIST REQUEST (%s) ---", phase)
    resp = requests.post(f"{cfg['url']}/api/chat", json=payload, timeout=timeout)
    resp.raise_for_status()
    return resp.json()


def _run_assist_with_ollama(prompt, items, history, tools, deadline) -> Dict[str, Any]:
    tool_map = {t.__name__: t for t in tools}
    system = _system_prompt(ASSIST_VIBE_TOOL in tools)

    research_messages = [{"role": "system", "content": system}]
    research_messages.extend(history)
    research_messages.append({
        "role": "user",
        "content": (f"### CURRENT PLAYLIST ###\n{_render_canvas(items)}\n\n"
                    f"### USER REQUEST ###\n{prompt}\n\n"
                    "Call whichever tools you need to gather candidate movies. "
                    "Do not answer yet."),
    })

    findings_parts: List[str] = []
    invocations = 0
    try:
        response = _call_ollama(research_messages, tools=tools, phase="Research",
                                remaining=deadline - time.monotonic())
        message = response.get("message", {}) or {}
        for call in (message.get("tool_calls") or []):
            if invocations >= MAX_TOOL_INVOCATIONS or time.monotonic() >= deadline:
                logger.warning("Assist tool budget or deadline reached; stopping research.")
                break
            name = (call.get("function") or {}).get("name")
            args = (call.get("function") or {}).get("arguments") or {}
            if name not in tool_map:
                continue
            invocations += 1
            try:
                result = tool_map[name](**args)
            except Exception as e:
                logger.error("Assist tool '%s' failed: %s", name, e)
                continue
            findings_parts.append(_format_findings(name, args, result))
        if (message.get("content") or "").strip():
            findings_parts.append("Assistant notes: " + message["content"].strip())
    except Exception as e:
        logger.error("Assist research phase failed: %s", e, exc_info=True)

    curator_messages = [{"role": "system", "content": system}]
    curator_messages.extend(history)
    curator_messages.append({
        "role": "user",
        "content": _user_message(prompt, items, "\n\n".join(findings_parts)),
    })

    response = _call_ollama(curator_messages, json_schema=ASSIST_RESPONSE_SCHEMA,
                            phase="Curator", remaining=deadline - time.monotonic())
    raw = ((response.get("message") or {}).get("content") or "").strip()
    return _parse_assist_json(raw)


# --- Gemini path -----------------------------------------------------------

def _gemini_client():
    key = (current_media().connection.ai_settings or {}).get("GEMINI_API_KEY", "")
    if not key:
        raise AssistError("Gemini API key is not configured for this connection.")
    if genai is None:
        raise AssistError("The google-genai package is not installed.")
    return genai.Client(api_key=key), os.environ.get("GEMINI_MODEL", "gemini-2.5-flash")


def _gemini_http_options(deadline):
    """Bound each Gemini call by whatever is left of the turn deadline.

    google-genai takes this in milliseconds. Without it the deadline would only be
    checked between phases and a single hung call could outlive it.
    """
    remaining = max(5.0, deadline - time.monotonic())
    return types.HttpOptions(timeout=int(remaining * 1000))


def _run_assist_with_gemini(prompt, items, history, tools, deadline) -> Dict[str, Any]:
    client, model_name = _gemini_client()
    system = _system_prompt(ASSIST_VIBE_TOOL in tools)

    chat = client.chats.create(
        model=model_name,
        config=types.GenerateContentConfig(
            system_instruction=system,
            tools=bind_tools(tools),
            temperature=0.2,
            max_output_tokens=MAX_OUTPUT_TOKENS,
            automatic_function_calling=types.AutomaticFunctionCallingConfig(
                maximum_remote_calls=MAX_TOOL_INVOCATIONS
            ),
            http_options=_gemini_http_options(deadline),
        ),
    )
    history_text = "\n".join(f"{h['role']}: {h['content']}" for h in history)

    research_text = ""
    try:
        research = chat.send_message(
            f"### EARLIER CONVERSATION ###\n{history_text or '(none)'}\n\n"
            f"### CURRENT PLAYLIST ###\n{_render_canvas(items)}\n\n"
            f"### USER REQUEST ###\n{prompt}\n\n"
            "Use your tools to gather the candidate movies you need."
        )
        research_text = research.text or ""
    except Exception as e:
        logger.error("Assist Gemini research phase failed: %s", e, exc_info=True)

    if time.monotonic() >= deadline:
        raise AssistError("The assistant took too long to respond. Try a simpler request.")

    curator = client.models.generate_content(
        model=model_name,
        contents=(f"### EARLIER CONVERSATION ###\n{history_text or '(none)'}\n\n"
                  + _user_message(prompt, items, research_text)),
        config=types.GenerateContentConfig(
            system_instruction=system,
            response_mime_type="application/json",
            response_schema=ASSIST_RESPONSE_SCHEMA,
            temperature=0.0,
            max_output_tokens=MAX_OUTPUT_TOKENS,
            http_options=_gemini_http_options(deadline),
        ),
    )
    return _parse_assist_json(curator.text or "")


# --- Shared plumbing -------------------------------------------------------

def _format_findings(tool_name: str, args: Dict[str, Any], result: Any) -> str:
    label = args.get("prompt") or args.get("titles") or args.get("ids") or tool_name
    lines = [f"FINDINGS FROM {tool_name} ({label}):"]
    if isinstance(result, list):
        for r in result:
            if not isinstance(r, dict):
                continue
            lines.append(
                f'- ID: "{r.get("Id", "")}" | "{r.get("Name", "Unknown")} '
                f'({r.get("Year", "Unknown")})" | Genres: {r.get("Genres", "")}'
            )
    if len(lines) == 1:
        lines.append("- (no matches)")
    return "\n".join(lines)


def _parse_assist_json(raw: str) -> Dict[str, Any]:
    text = (raw or "").strip()
    if not text:
        raise AssistError("The assistant returned an empty response.")
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", text, re.DOTALL)
        if not match:
            raise AssistError("The assistant returned a response MixerBee could not read.")
        try:
            data = json.loads(match.group(0))
        except json.JSONDecodeError as e:
            raise AssistError("The assistant returned malformed JSON.") from e
    if not isinstance(data, dict):
        raise AssistError("The assistant returned a response MixerBee could not read.")
    return data


def _clean_ids(raw: Any) -> List[str]:
    """Accept the id list in whatever shape the model emitted, keeping order."""
    if isinstance(raw, str):
        raw = [p.strip() for p in raw.split(",")]
    if not isinstance(raw, list):
        return []
    out, seen = [], set()
    for entry in raw:
        if isinstance(entry, dict):
            entry = entry.get("Id") or entry.get("id") or ""
        candidate = str(entry or "").strip()
        match = re.search(r"\b([a-fA-F0-9]{32}|\d{3,15})\b", candidate)
        if not match:
            continue
        item_id = match.group(1)
        if item_id not in seen:
            seen.add(item_id)
            out.append(item_id)
    return out


def _year_window(data: Dict[str, Any]):
    """The release window the model declared, sanitised. (0, 0) means no constraint."""
    from .tools import _coerce_year
    lo, hi = _coerce_year(data.get("year_from")), _coerce_year(data.get("year_to"))
    if lo and hi and lo > hi:
        lo, hi = hi, lo
    return lo, hi


def enforce_pins(proposed_ids: List[str], current_items: List[Dict[str, Any]]) -> List[str]:
    """Deterministic pin enforcement (§2.1).

    Pinned membership is guaranteed regardless of what the model returned, and pins
    beat the size cap: the cap only ever trims unpinned items.
    """
    pinned = [(idx, str(it.get("Id") or "")) for idx, it in enumerate(current_items)
              if it.get("locked") and it.get("Id")]
    pinned_ids = {pid for _, pid in pinned}

    kept: List[str] = []
    unpinned_count = 0
    for item_id in proposed_ids:
        if item_id in pinned_ids:
            kept.append(item_id)
        elif unpinned_count < MAX_PLAYLIST_SIZE:
            kept.append(item_id)
            unpinned_count += 1

    for original_index, pid in pinned:
        if pid in kept:
            continue
        if original_index <= len(kept):
            kept.insert(original_index, pid)
        else:
            kept.append(pid)
    return kept


@media_operation
def run_assist_turn(
    prompt: str,
    current_items: List[Dict[str, Any]],
    chat_history: Optional[List[Dict[str, Any]]] = None,
    *,
    media=None,
) -> Dict[str, Any]:
    """Run one Playlist Assist turn and return the revised canvas.

    Returns {ai_chat_response, suggested_title, suggested_description, new_items}.
    Raises AssistPinUnavailable when a pinned item no longer resolves on the server;
    the caller turns that into a 400 and the mutation is discarded wholesale.
    """
    refresh_logger_level()
    deadline = time.monotonic() + TURN_DEADLINE_SECONDS

    prompt = (prompt or "").strip()[:MAX_PROMPT_CHARS]
    if not prompt:
        raise AssistError("A prompt is required.")

    current_items = current_items or []
    history = _trim_history(chat_history)
    ledger = TurnLedger()
    tools = ledger.wrap(_tools_for_turn(media))

    # Resolve the canvas from the server before prompting. The browser only sends
    # {Id, locked, Name}, so building the manifest from the request would show the
    # model "(Unknown)" for every release year and then ask it to filter by year.
    # These values are also the ones the year window is later enforced against, so
    # they must come from the library, not from whatever the page happened to hold.
    canvas_ids = {str(it.get("Id")) for it in current_items if it.get("Id")}
    canvas_details = {item["Id"]: item for item in resolve_movies(sorted(canvas_ids))}
    hydrated = []
    for it in current_items:
        item_id = str(it.get("Id") or "")
        detail = canvas_details.get(item_id) or {}
        hydrated.append({
            "Id": item_id,
            "locked": bool(it.get("locked")),
            "Name": detail.get("Name") or it.get("Name") or "Unknown",
            "Year": detail.get("Year", ""),
            "Genres": detail.get("Genres", ""),
        })

    # Last check before the model is contacted, after the canvas round-trip to the
    # media server: a disable that lands during that resolve stops this turn.
    from app.ai_policy import require_generative
    require_generative(media.connection.id)

    provider = (media.connection.ai_settings or {}).get("AI_PROVIDER", "gemini")
    if provider == "ollama":
        data = _run_assist_with_ollama(prompt, hydrated, history, tools, deadline)
    else:
        data = _run_assist_with_gemini(prompt, hydrated, history, tools, deadline)

    proposed = _clean_ids(data.get("movie_ids"))

    # An ID is only admissible if it was already on the canvas or a tool returned it
    # this turn. Resolving on the server is not enough on its own: incidental search
    # noise and invented IDs both resolve perfectly well.
    allowed = canvas_ids | ledger.seen_ids
    rejected = [i for i in proposed if i not in allowed]
    if rejected:
        logger.warning("Dropping %d unsourced ID(s) the model proposed: %s",
                       len(rejected), ", ".join(rejected[:10]))
    proposed = [i for i in proposed if i in allowed]

    year_from, year_to = _year_window(data)

    # Canvas items are already resolved; only genuinely new IDs need a lookup.
    details = dict(canvas_details)
    fresh = [i for i in proposed if i not in details]
    if fresh:
        details.update({item["Id"]: item for item in resolve_movies(fresh)})

    if year_from or year_to:
        kept = [i for i in proposed
                if in_year_window((details.get(i) or {}).get("Year"), year_from, year_to)]
        if len(kept) != len(proposed):
            logger.info("Release window %s-%s dropped %d of %d proposed movies.",
                        year_from or "any", year_to or "any", len(proposed) - len(kept), len(proposed))
        proposed = kept

    final_ids = enforce_pins(proposed, current_items)

    # Pins are exempt from the year window (membership is guaranteed) but they still
    # have to exist, so the resolved set is the authority for availability.
    resolved = {i: details[i] for i in final_ids if i in details}

    missing_pins = [str(it.get("Id")) for it in current_items
                    if it.get("locked") and str(it.get("Id") or "") not in resolved]
    if missing_pins:
        names = ", ".join(
            str(it.get("Name") or it.get("Id"))
            for it in current_items
            if it.get("locked") and str(it.get("Id") or "") in set(missing_pins)
        )
        raise AssistPinUnavailable(
            f"Pinned item(s) are no longer available on the media server: {names}. "
            "No changes were applied."
        )

    locked_ids = {str(it.get("Id")) for it in current_items if it.get("locked")}
    new_items = []
    for item_id in final_ids:
        item = resolved.get(item_id)
        if not item:
            continue
        new_items.append(dict(item, locked=item_id in locked_ids))

    return {
        "ai_chat_response": str(data.get("chat_response") or "")[:MAX_CHAT_RESPONSE_CHARS]
                            or "Updated the playlist.",
        "year_from": year_from,
        "year_to": year_to,
        "suggested_title": str(data.get("suggested_title") or "")[:MAX_TITLE_CHARS],
        "suggested_description": str(data.get("suggested_description") or "")[:MAX_DESCRIPTION_CHARS],
        "new_items": new_items,
    }
