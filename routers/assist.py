"""
routers/assist.py – APIRouter for Playlist Assist (conversational movie curation).
"""

import logging
from typing import Any, Dict

from fastapi import APIRouter, Depends, HTTPException

import app as core
import models
from app import ai_policy
from app.ai.assist_orchestrator import (
    AssistError,
    AssistPinUnavailable,
    MAX_PLAYLIST_SIZE,
    assist_availability,
    run_assist_turn,
)
from app.ai.tools import resolve_movies
from app.media_client import media_scope
from .dependencies import get_current_auth_headers, media_for_user, require_generative_ai

router = APIRouter()

MAX_SAVE_ITEMS = 500


@router.get("/api/ai/assist/status")
def api_assist_status(auth_deps: dict = Depends(get_current_auth_headers)) -> Dict[str, Any]:
    """Tells the UI whether to hide Assist, show the setup gate, or show the pane."""
    return {"status": "ok"} | assist_availability(auth_deps["media"])


@router.post("/api/ai/assist/chat")
def api_assist_chat(
    req: models.AssistChatRequest,
    auth_deps: dict = Depends(get_current_auth_headers)
) -> Dict[str, Any]:
    media = auth_deps["media"]
    require_generative_ai(auth_deps)

    current_items = [item.model_dump() for item in req.current_items]

    try:
        result = run_assist_turn(
            prompt=req.prompt,
            current_items=current_items,
            chat_history=[m.model_dump() for m in req.chat_history],
            media=media,
        )
    except AssistPinUnavailable as e:
        # A pin that lost server access voids the whole turn rather than silently
        # producing a playlist the user did not ask for.
        raise HTTPException(400, str(e)) from e
    except AssistError as e:
        raise HTTPException(502, str(e)) from e
    except (ai_policy.AIDisabled, ai_policy.AINotConfigured) as e:
        # Raised by the recheck inside the turn when AI is switched off mid-request.
        # Caught above the generic handler so the reason survives.
        status = 403 if isinstance(e, ai_policy.AIDisabled) else 409
        reason = ai_policy.REASON_DISABLED if status == 403 else "ai_not_configured"
        raise HTTPException(status, {"detail": str(e), "reason": reason}) from e
    except Exception as e:
        logging.error("Playlist Assist turn failed", exc_info=True)
        raise HTTPException(500, f"Playlist Assist failed: {e}") from e

    # The revision id is echoed verbatim: it is the frontend's fast path for skipping
    # its merge step, never a reason for either side to discard a response.
    return {"status": "ok", "revision_id": req.revision_id} | result


@router.post("/api/ai/assist/save")
def api_assist_save(
    req: models.AssistSaveRequest,
    auth_deps: dict = Depends(get_current_auth_headers)
) -> Dict[str, Any]:
    """Create-only save: never adopts, replaces, or deletes an existing playlist."""
    user_id = req.user_id or auth_deps["login_uid"]
    media = media_for_user(auth_deps, user_id)

    name = (req.playlist_name or "").strip()
    if not name:
        raise HTTPException(400, "A playlist name is required.")

    item_ids, seen = [], set()
    for raw in req.item_ids[:MAX_SAVE_ITEMS]:
        item_id = str(raw or "").strip()
        if item_id and item_id not in seen:
            seen.add(item_id)
            item_ids.append(item_id)
    if not item_ids:
        raise HTTPException(400, "The playlist is empty. Add some movies first.")

    # Resolve before recording the run so history stores real titles and runtimes,
    # and so a stale canvas cannot post IDs the server no longer serves.
    # resolve_movies, not the model-facing get_movie_metadata: that one caps at
    # MAX_ASSIST_METADATA_IDS, which would silently truncate a long save.
    with media_scope(media):
        resolved = {item["Id"]: item for item in resolve_movies(item_ids)}
    ordered = [resolved[i] for i in item_ids if i in resolved]
    if not ordered:
        raise HTTPException(400, "None of these movies are available on the media server any more.")

    dropped = len(item_ids) - len(ordered)

    run_id = core.build_history.record_build_start(
        connection_id=auth_deps["connection_id"],
        operation="playlist",
        user_id=user_id,
        trigger_source="assist",
        series_key=name,
        definition_snapshot={
            "source": "playlist_assist",
            "title": name,
            "description": req.description,
            "item_ids": [item["Id"] for item in ordered],
        },
    )

    log = []
    if dropped:
        log.append(f"{dropped} item(s) were skipped because the server no longer serves them.")

    try:
        new_id = core.create_playlist_exclusive(
            name=name,
            user_id=user_id,
            ids=[item["Id"] for item in ordered],
            media=media,
            log=log,
        )
    except Exception as e:
        core.build_history.record_build_finish(
            run_id=run_id, output_id=None, outcome="error", summary=str(e), rows=[]
        )
        logging.error("Playlist Assist save failed", exc_info=True)
        raise HTTPException(500, f"Failed to save the playlist: {e}") from e

    if not new_id:
        core.build_history.record_build_finish(
            run_id=run_id, output_id=None, outcome="error",
            summary=f"Failed to create playlist '{name}'", rows=[]
        )
        raise HTTPException(500, " ".join(log) or "Failed to create the playlist.")

    # Cosmetic, and deliberately non-fatal: losing a description is not worth
    # deleting a playlist the user just spent a conversation curating.
    description_saved = True
    if req.description.strip():
        description_saved = core.set_playlist_overview(new_id, user_id, req.description.strip(), media, log)

    rows = [
        {
            "Id": item["Id"],
            "Name": item.get("Name"),
            "Type": "Movie",
            "RunTimeTicks": item.get("RunTimeTicks") or 0,
            "context": "Playlist Assist",
        }
        for item in ordered
    ]
    core.build_history.record_build_finish(
        run_id=run_id,
        output_id=new_id,
        # record_build_finish only stores item rows for a success outcome, and a
        # missing description does not make the build any less successful.
        outcome="ok",
        summary=f"Playlist Assist created '{name}' with {len(rows)} movies"
                + ("" if description_saved else " (description not applied)"),
        rows=rows,
    )

    if not log:
        log.append(f"Created playlist '{name}' with {len(rows)} movies.")

    return {
        # Always "ok": the playlist exists and is correct. A failed description is
        # reported as a warning, not a failed save.
        "status": "ok",
        "warning": "" if description_saved else "The playlist was created, but its description could not be saved.",
        "log": log,
        "new_item_id": new_id,
        "newItemUrl": core.construct_item_url(new_id, media),
        "run_id": run_id,
        "description_saved": description_saved,
        "item_count": len(rows),
        "max_playlist_size": MAX_PLAYLIST_SIZE,
    }
