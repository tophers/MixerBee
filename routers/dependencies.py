"""
routers/dependencies.py – APIRouter
"""

import logging
from fastapi import HTTPException, Request

def _ensure_fresh_auth(connection_id) -> dict:
    """Authenticate one explicit connection; never fall back to shared app state."""
    from connections import get_media_client
    if not connection_id:
        raise HTTPException(409, "Add a media connection in Settings.")
    try:
        media = get_media_client(connection_id)
        media.ensure_authenticated()
        return {"media": media, "login_uid": media.user_id, "connection_id": connection_id}
    except Exception as exc:
        logging.warning("Saved media connection unavailable: %s", type(exc).__name__)
        raise HTTPException(503, "Media connection unavailable. Check this account's server and credentials.") from exc


def media_for_user(auth_deps, user_id):
    media = auth_deps["media"]
    if media.user_id != user_id:
        raise HTTPException(403, "Requested user does not match the active media connection.")
    return media


def require_collection_permission(media):
    if not media.can_manage_collections():
        raise HTTPException(403, "This media-server account cannot manage collections. Use a playlist instead.")
    return media


def owned_connection(request: Request, connection_id=None, required=True):
    session = request.state.account
    cid = connection_id or request.headers.get('x-mixerbee-connection') or session['connection_id']
    if not cid:
        if required:
            raise HTTPException(409, "Add a media connection in Settings.")
        return None
    import database
    with database.get_db_connection() as conn:
        row = conn.execute('SELECT * FROM media_connections WHERE id=? AND owner_id=?', (cid, session['id'])).fetchone()
    if not row:
        raise HTTPException(404, "Connection not found.")
    return dict(row)


def get_current_auth_headers(request: Request) -> dict:
    cid = getattr(request.state, 'external_connection_id', None)
    if cid is None:
        cid = owned_connection(request)['id']
    return _ensure_fresh_auth(cid)


def require_generative_ai(auth_deps: dict) -> dict:
    """Shared HTTP guard for provider generation and enrichment.

    Raises 403 with reason ``disabled_by_user`` for a deliberate opt-out and 409 with
    ``ai_not_configured`` for missing setup, so a stale tab can tell the two apart and
    refresh its capability state instead of only showing an error.

    Never applied to semantic refresh, vector reset/reindex, similarity search, or Echo
    resolution: those are core library features with no provider requirement.
    """
    from app import ai_policy
    from fastapi import HTTPException
    try:
        return ai_policy.require_generative(auth_deps["connection_id"])
    except ai_policy.AIDisabled as exc:
        raise HTTPException(403, {"detail": str(exc), "reason": ai_policy.REASON_DISABLED}) from exc
    except ai_policy.AINotConfigured as exc:
        raise HTTPException(409, {"detail": str(exc), "reason": "ai_not_configured"}) from exc


def get_auth_data(connection_id: str) -> dict:
    """Jobs must resolve their own persisted connection, never the UI's active one."""
    if not connection_id:
        raise ValueError("Background jobs require a saved connection ID.")
    return _ensure_fresh_auth(connection_id)
