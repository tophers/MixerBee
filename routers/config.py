"""Settings belong to the signed-in account's selected media connection."""
import json
import secrets
import threading
import time
import uuid

import requests
from fastapi import APIRouter, HTTPException, Depends, Body, Request

import accounts
import app as core
import database
import models
from connections import get_media_client, save_authenticated_connection, webhook_status
from app.media_client import Connection, MediaClient
from app.cache import refresh_cache
from app import ai_policy
from app.ai.vector_store import (ensure_library_indexed, get_vector_space,
                                 reset_media_collection)
from .dependencies import get_current_auth_headers, owned_connection

from app.logger import get_logger

logger = get_logger("MixerBee.Settings")

router = APIRouter()


def get_local_ip():
    import socket
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.settimeout(0.5)
        s.connect(('10.254.254.254', 1))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return '127.0.0.1'


def settings_payload(row):
    ai = json.loads(row['ai_settings']) if row else {}
    api_key = (row['api_key'] if (row and 'api_key' in row.keys()) else '') or ''
    api_key_hash = (row['api_key_hash'] if (row and 'api_key_hash' in row.keys()) else '') or ''
    with database.get_db_connection() as conn:
        public_base = conn.execute("SELECT value FROM settings WHERE key='webhook_public_base_url'").fetchone()
    payload = {
        'connection_id': row['id'] if row else None, 'label': row['label'] if row else '',
        'server_type': row['server_type'] if row else 'emby',
        'emby_url': row['base_url'] if row else '', 'emby_user': row['username'] if row else '',
        'emby_pass': row['password'] if row else '',
        # No provider defaults: an empty AI_PROVIDER is what marks a connection as
        # having no deliberate AI setup, and pre-filling one here would undo that.
        # The UI shows localhost/model examples as placeholders instead.
        'ai_provider': str(ai.get('AI_PROVIDER') or ''), 'gemini_key': ai.get('GEMINI_API_KEY', ''),
        'ollama_url': ai.get('OLLAMA_URL', ''),
        'ollama_model': ai.get('OLLAMA_MODEL', ''),
        'ollama_timeout': ai.get('OLLAMA_TIMEOUT', 120), 'starred_models': ai.get('STARRED_MODELS', []),
        'external_api_key': api_key, 'external_api_key_set': bool(api_key or api_key_hash),
        'webhook_secret': row['webhook_secret'] if row else '',
        'webhook_public_base_url': public_base['value'] if public_base else '',
        'version': core.CLIENT_VERSION,
        'server_ip': get_local_ip(),
        'vector_space': get_vector_space(media=get_media_client(row['id'])) if row else 'cosine'
    }
    payload['webhook_status'] = webhook_status(payload | ({
        key: row[key] for key in ('webhook_secret_updated_at', 'webhook_setup_requested_at',
                                  'webhook_setup_acknowledged_at', 'webhook_verified_at')
    } if row else {}))
    return payload


@router.get('/api/config_status')
def api_config_status(request: Request):
    row = owned_connection(request, required=False)
    settings = settings_payload(row)
    caps = ai_policy.capability(request.state.account['id'], row)
    return {k: settings[k] for k in ('server_type', 'version', 'ai_provider', 'ollama_model', 'starred_models', 'vector_space')} | caps | {
        'is_configured': bool(row),
        # Enrichment schedules are hidden while AI is unavailable, not deleted. The
        # count tells Account settings how many are waiting for a re-enable.
        'retained_ai_schedules': ai_policy.retained_ai_schedule_count(request.state.account['id'])
                                 if not caps['generative_ai_available'] else 0,
        # Transitional alias for the old ambiguous flag: it now means exactly
        # "generative AI is available", which is what every caller wanted.
        'is_ai_configured': caps['generative_ai_available']}


@router.get('/api/settings')
def api_get_settings(request: Request):
    row = owned_connection(request, required=False)
    return settings_payload(row) | ai_policy.capability(request.state.account['id'], row)


@router.post('/api/settings/external_api_key/regenerate')
def api_regenerate_external_api_key(request: Request, payload: dict = Body(default={})):
    row = owned_connection(request, payload.get('connection_id'))
    custom = str(payload.get('key') or '').strip()
    if custom and not 16 <= len(custom) <= 256:
        raise HTTPException(400, 'External API key must contain 16–256 characters.')
    key = custom or secrets.token_urlsafe(24)
    with database.get_db_connection() as conn:
        other = conn.execute('SELECT id FROM media_connections WHERE api_key_hash=?', (accounts.token_hash(key),)).fetchone()
        if other and other['id'] != row['id']:
            raise HTTPException(400, 'That integration key is already in use. Choose a different key.')
        conn.execute('UPDATE media_connections SET api_key=?, api_key_hash=? WHERE id=?',
                     (key, accounts.token_hash(key), row['id']))
        conn.commit()
    return {'status': 'ok', 'external_api_key': key, 'log': ['External API key updated.']}


@router.post('/api/settings/external_api_key/clear')
def api_clear_external_api_key(request: Request, payload: dict = Body(default={})):
    row = owned_connection(request, payload.get('connection_id'))
    with database.get_db_connection() as conn:
        conn.execute("UPDATE media_connections SET api_key='', api_key_hash='' WHERE id=?", (row['id'],))
        conn.commit()
    return {'status': 'ok', 'external_api_key': '', 'log': ['External API access disabled for this connection.']}


@router.post('/api/settings/webhook_secret/regenerate')
def api_regenerate_webhook_secret(request: Request, payload: dict = Body(default={})):
    row = owned_connection(request, payload.get('connection_id'))
    custom = str(payload.get('key') or '').strip()
    if custom and not 16 <= len(custom) <= 256:
        raise HTTPException(400, 'Webhook secret must contain 16–256 characters.')
    secret = custom or secrets.token_urlsafe(24)
    now = time.time()
    requested_at = None if request.state.account['is_admin'] else now
    with database.get_db_connection() as conn:
        conn.execute('''UPDATE media_connections SET webhook_secret=?, webhook_secret_updated_at=?,
            webhook_setup_requested_at=?, webhook_setup_acknowledged_at=NULL,
            webhook_verified_at=NULL, webhook_last_received_at=NULL WHERE id=?''',
            (secret, now, requested_at, row['id']))
        conn.commit()
    message = ('Webhook secret updated. The MixerBee owner has been asked to configure the media server.'
               if requested_at else 'Webhook secret updated. Configure its URL on the media server.')
    return {'status': 'ok', 'webhook_secret': secret,
            'webhook_status': 'setup_requested' if requested_at else 'needs_setup', 'log': [message]}


@router.post('/api/settings/webhook/setup-request')
def api_request_webhook_setup(request: Request, payload: dict = Body(default={})):
    row = owned_connection(request, payload.get('connection_id'))
    if not row['webhook_secret']:
        raise HTTPException(409, 'Generate a webhook secret before requesting setup.')
    with database.get_db_connection() as conn:
        conn.execute('''UPDATE media_connections SET webhook_setup_requested_at=?,
            webhook_setup_acknowledged_at=NULL WHERE id=?''', (time.time(), row['id']))
        conn.commit()
    return {'status': 'ok', 'webhook_status': 'setup_requested',
            'log': ['The MixerBee owner has been notified about this webhook setup.']}


@router.post('/api/settings/webhook_secret/clear')
def api_clear_webhook_secret(request: Request, payload: dict = Body(default={})):
    row = owned_connection(request, payload.get('connection_id'))
    with database.get_db_connection() as conn:
        conn.execute('''UPDATE media_connections SET webhook_secret='', webhook_secret_updated_at=NULL,
            webhook_setup_requested_at=NULL, webhook_setup_acknowledged_at=NULL,
            webhook_verified_at=NULL, webhook_last_received_at=NULL WHERE id=?''', (row['id'],))
        conn.commit()
    return {'status': 'ok', 'webhook_secret': '', 'log': ['Webhooks disabled for this connection.']}


@router.get('/api/ollama/status')
def api_ollama_status(request: Request, url: str | None = None):
    # Discovery is part of deliberate setup, so it is allowed before a provider is
    # chosen -- but never once the account has opted out of AI.
    ai_policy.require_account_allows_ai_http(request.state.account['id'])
    settings = settings_payload(owned_connection(request, required=False))
    base_url = (url or settings['ollama_url'] or 'http://localhost:11434').rstrip('/')
    validate_url(base_url)
    try:
        tags = requests.get(f'{base_url}/api/tags', timeout=5)
        running = requests.get(f'{base_url}/api/ps', timeout=5)
        return {'installed': tags.json().get('models', []) if tags.ok else [],
                'running': running.json().get('models', []) if running.ok else []}
    except requests.RequestException:
        return {'installed': [], 'running': [], 'error': 'Could not reach Ollama.'}


@router.post('/api/settings/model')
def api_update_active_model(req: models.ModelUpdateRequest, request: Request):
    row = owned_connection(request)
    ai_policy.require_generative_http(row['id'], request.state.account['id'])
    ai = json.loads(row['ai_settings'])
    ai['OLLAMA_MODEL'] = req.ollama_model
    with database.get_db_connection() as conn:
        conn.execute('UPDATE media_connections SET ai_settings=? WHERE id=?', (json.dumps(ai), row['id']))
        conn.commit()
    from connections import forget_media_client
    forget_media_client(row['id'])
    return {'status': 'ok', 'model': req.ollama_model}


@router.post('/api/settings/ai')
def api_update_ai_settings(req: models.AiSettingsUpdateRequest, request: Request):
    """Deliberate AI setup for one connection. This is the only writer of ai_settings."""
    row = owned_connection(request)
    # Allowed while unconfigured -- this endpoint is how setup completes -- but never
    # once the account has opted out.
    ai_policy.require_account_allows_ai_http(request.state.account['id'])
    # '' clears the selection, which is how a user turns AI off for one connection
    # without deleting the credentials they may want back later.
    if req.ai_provider is not None and req.ai_provider not in ('', 'gemini', 'ollama'):
        raise HTTPException(400, 'Choose Gemini or Ollama.')
    if req.ollama_url:
        validate_url(req.ollama_url)
    if req.ollama_timeout is not None and not 10 <= req.ollama_timeout <= 600:
        raise HTTPException(400, 'Ollama timeout must be between 10 and 600 seconds.')

    # Merge onto the stored settings rather than rebuilding them: a field the caller
    # omitted keeps its saved value instead of being blanked.
    ai = json.loads(row['ai_settings']) if row['ai_settings'] else {}
    if req.ai_provider is not None:
        ai['AI_PROVIDER'] = req.ai_provider
    if req.gemini_key is not None:
        ai['GEMINI_API_KEY'] = req.gemini_key.strip()
    if req.ollama_url is not None:
        ai['OLLAMA_URL'] = req.ollama_url.rstrip('/')
    if req.ollama_model is not None:
        ai['OLLAMA_MODEL'] = req.ollama_model.strip()
    if req.ollama_timeout is not None:
        ai['OLLAMA_TIMEOUT'] = req.ollama_timeout
    if req.starred_models is not None:
        ai['STARRED_MODELS'] = req.starred_models

    # Only the selected provider's requirements are validated. Saving a Gemini key
    # must not demand an Ollama URL, and vice versa.
    provider = str(ai.get('AI_PROVIDER') or '')
    if provider == 'gemini' and not str(ai.get('GEMINI_API_KEY') or '').strip():
        raise HTTPException(400, 'Add a Gemini API key to use Gemini.')
    if provider == 'ollama' and not (str(ai.get('OLLAMA_URL') or '').strip() and str(ai.get('OLLAMA_MODEL') or '').strip()):
        raise HTTPException(400, 'Add an Ollama server URL and model name to use Ollama.')

    with database.get_db_connection() as conn:
        conn.execute('UPDATE media_connections SET ai_settings=? WHERE id=?', (json.dumps(ai), row['id']))
        conn.commit()
    # Drop the cached client so the next request picks up the new settings. No indexing
    # is kicked off here any more: the semantic index is a core library concern, not an
    # AI-provider one, and connection saves, startup warming, and the periodic catch-up
    # already build it whether or not a provider is configured.
    from connections import forget_media_client
    forget_media_client(row['id'])
    caps = ai_policy.capability(request.state.account['id'], row | {'ai_settings': json.dumps(ai)})
    return {'status': 'ok', 'log': ['AI settings updated.']} | caps


def validate_url(url):
    from urllib.parse import urlsplit
    parsed = urlsplit(url)
    if parsed.scheme not in ('http', 'https') or not parsed.hostname or parsed.username or parsed.password:
        raise HTTPException(400, 'Use an http:// or https:// server URL without embedded credentials.')


def authenticate_candidate(req):
    validate_url(req.emby_url.strip())
    if req.server_type not in ('emby', 'jellyfin'):
        raise HTTPException(400, 'Choose Emby or Jellyfin.')
    candidate = MediaClient(Connection(uuid.uuid4().hex, req.emby_url.strip().rstrip('/'),
                                       req.server_type, req.emby_user.strip(), req.emby_pass))
    try:
        return candidate.authenticate()
    finally:
        candidate.session.close()


@router.post('/api/settings/test')
def api_test_settings(req: models.SettingsRequest):
    try:
        authenticate_candidate(req)
        return {'status': 'ok', 'log': ['Connection successful! Credentials and URL verified.']}
    except Exception:
        return {'status': 'error', 'log': ['Connection failed. Check the URL, username, password, and server availability.']}


def warm_connection(media):
    refresh_cache(media)
    # Unconditional: the semantic index backs Echo blocks and similarity search, which
    # are core library features and do not require an AI provider. Settings can be
    # saved repeatedly; ensure_library_indexed collapses overlapping runs instead of
    # stacking indexer threads on one collection.
    ensure_library_indexed(media.user_id, media, force=True)


@router.post('/api/settings')
def api_save_settings(req: models.SettingsRequest, request: Request):
    if req.connection_id:
        owned_connection(request, req.connection_id)
    # No AI validation here on purpose: saving media credentials must never require a
    # Gemini key, an Ollama URL, a model, or a live provider test. AI setup is a
    # separate, deliberate step through /api/settings/ai.
    key = (req.external_api_key or '').strip()
    if key and not 16 <= len(key) <= 256:
        raise HTTPException(400, 'External API key must contain 16–256 characters.')
    # Each integration token identifies exactly one connection.
    if key:
        with database.get_db_connection() as conn:
            other = conn.execute('SELECT id FROM media_connections WHERE api_key_hash=?', (accounts.token_hash(key),)).fetchone()
        if other and other['id'] != req.connection_id:
            raise HTTPException(400, 'That integration key is already in use. Choose a different key.')
    try:
        auth = authenticate_candidate(req)
    except Exception as exc:
        raise HTTPException(400, 'Could not authenticate. Check the server URL and media credentials.') from exc
    # A new connection starts with no provider selected. save_authenticated_connection
    # leaves an existing connection's AI settings untouched, so a general save can no
    # longer blank a configured provider with this form's values.
    ai = {'AI_PROVIDER': '', 'GEMINI_API_KEY': '', 'OLLAMA_URL': '', 'OLLAMA_MODEL': '',
          'OLLAMA_TIMEOUT': 120, 'STARRED_MODELS': []}
    try:
        media = save_authenticated_connection(req.emby_url.strip(), req.server_type, req.emby_user.strip(), req.emby_pass,
            auth, ai, owner_id=request.state.account['id'], existing_id=req.connection_id, label=req.label.strip())
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    with database.get_db_connection() as conn:
        if key or req.clear_external_api_key:
            conn.execute('UPDATE media_connections SET api_key=?, api_key_hash=? WHERE id=?',
                         (key if key else '', accounts.token_hash(key) if key else '', media.connection.id))
        conn.execute('UPDATE account_sessions SET connection_id=? WHERE token_hash=?',
                     (media.connection.id, request.state.account['token_hash']))
        conn.commit()
    threading.Thread(target=warm_connection, args=(media,), daemon=True).start()
    caps = ai_policy.capability_for_connection(media.connection.id, request.state.account['id'])
    return {'status': 'ok', 'connection_id': media.connection.id,
            'log': ['Connection saved. Library refresh started.']} | caps


@router.post("/api/settings/reset_vector_db")
def api_reset_vector_db(req: models.ResetVectorDbRequest, auth_deps: dict = Depends(get_current_auth_headers)):
    """Triggers a manual reset of the vector database."""
    try:
        reset_media_collection(preserve_enrichments=req.preserve_enrichments, media=auth_deps["media"])
        
        threading.Thread(
            target=ensure_library_indexed,
            args=(auth_deps["login_uid"], auth_deps["media"]),
            kwargs={"force": True},
            daemon=True
        ).start()

        msg = "AI Database has been reset. Library re-indexing started in background."
        if req.preserve_enrichments:
            msg += " Previous AI tags will be restored automatically."
            
        return {"status": "ok", "log": [msg]}
    except Exception as e:
        logger.error(f"Manual DB Reset failed: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))
