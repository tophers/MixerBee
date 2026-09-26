"""Local login, household accounts, and owned connection selection."""
import time
from urllib.parse import quote, urlencode, urlsplit

from pathlib import Path
from fastapi import APIRouter, HTTPException, Request, Response
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

import accounts
import database
from connections import webhook_status

router = APIRouter()


class Credentials(BaseModel):
    username: str = Field(max_length=64)
    password: str = Field(max_length=256)
    setup_token: str | None = Field(default=None, max_length=256)


class PasswordChange(BaseModel):
    current_password: str = Field(max_length=256)
    new_password: str = Field(max_length=256)


def session_payload(session):
    if not session:
        return {'authenticated': False, 'setup_required': accounts.setup_required()}
    return {'authenticated': True, 'setup_required': False,
            'account': {k: session[k] for k in ('id', 'username', 'is_admin')},
            'csrf_token': session['csrf_token'], 'connection_id': session['connection_id']}


def sign_in(request, response, account):
    old = request.cookies.get(accounts.cookie_name(request))
    if old:
        accounts.revoke_session(old)
    token, _ = accounts.create_session(account['id'])
    response.set_cookie(accounts.cookie_name(request), token, max_age=accounts.SESSION_SECONDS,
                        httponly=True, samesite='strict', secure=request.url.scheme == 'https', path='/')
    return session_payload(accounts.read_session(token))


def rate_limit(request):
    if not accounts.check_rate_limit(request.client.host if request.client else 'unknown'):
        raise HTTPException(429, 'Too many attempts. Try again in a minute.')


@router.get('/api/auth/status')
def auth_status(request: Request):
    return session_payload(accounts.read_session(request.cookies.get(accounts.cookie_name(request))))


@router.post('/api/auth/setup')
def setup(req: Credentials, request: Request, response: Response):
    rate_limit(request)
    if not accounts.setup_required():
        raise HTTPException(403, 'Initial setup is already complete.')
    try:
        account = accounts.create_account(req.username, req.password, initial_only=True)
    except PermissionError as exc:
        raise HTTPException(403, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    return sign_in(request, response, account)


@router.post('/api/auth/login')
def login(req: Credentials, request: Request, response: Response):
    rate_limit(request)
    account = accounts.authenticate(req.username, req.password)
    if not account:
        raise HTTPException(401, 'Incorrect username or password.')
    return sign_in(request, response, account)


@router.post('/api/auth/logout')
def logout(request: Request, response: Response):
    accounts.revoke_session(request.cookies.get(accounts.cookie_name(request), ''))
    response.delete_cookie(accounts.cookie_name(request), path='/')
    return {'status': 'ok'}


@router.post('/api/auth/password')
def password(req: PasswordChange, request: Request, response: Response):
    rate_limit(request)
    session = request.state.account
    if not accounts.authenticate(session['username'], req.current_password):
        raise HTTPException(400, 'Current password is incorrect.')
    try:
        accounts.change_password(session['id'], req.new_password)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    response.delete_cookie(accounts.cookie_name(request), path='/')
    return {'status': 'ok'}


def require_admin(request):
    if not request.state.account['is_admin']:
        raise HTTPException(403, 'Only the installation owner can manage local accounts.')


def _webhook_public_base_url(request):
    with database.get_db_connection() as conn:
        row = conn.execute("SELECT value FROM settings WHERE key='webhook_public_base_url'").fetchone()
    return (row['value'] if row else str(request.base_url)).rstrip('/')


def _webhook_url(request, connection):
    base = _webhook_public_base_url(request)
    path = f"{base}/api/webhook/{quote(connection['id'], safe='')}"
    return f"{path}?{urlencode({'token': connection['webhook_secret']})}"


@router.get('/api/accounts')
def list_accounts(request: Request):
    require_admin(request)
    with database.get_db_connection() as conn:
        return [dict(row) for row in conn.execute('SELECT id, username, is_admin FROM accounts ORDER BY username_key')]


@router.post('/api/accounts')
def add_account(req: Credentials, request: Request):
    require_admin(request)
    try:
        return accounts.create_account(req.username, req.password)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


@router.get('/api/admin/webhook-requests')
def list_webhook_requests(request: Request):
    require_admin(request)
    with database.get_db_connection() as conn:
        rows = conn.execute('''SELECT c.id, c.label, c.base_url, c.server_type, c.username,
            c.webhook_secret, c.webhook_secret_updated_at, c.webhook_setup_requested_at,
            c.webhook_setup_acknowledged_at, c.webhook_verified_at,
            c.webhook_last_received_at, a.username AS mixerbee_username
            FROM media_connections c JOIN accounts a ON a.id=c.owner_id
            WHERE c.webhook_secret<>'' AND c.webhook_setup_requested_at IS NOT NULL
              AND (c.webhook_verified_at IS NULL OR c.webhook_verified_at < c.webhook_secret_updated_at)
            ORDER BY c.webhook_setup_requested_at DESC''').fetchall()
    requests = []
    for raw in rows:
        row = dict(raw)
        requests.append({
            'connection_id': row['id'], 'connection_label': row['label'],
            'server_url': row['base_url'], 'server_type': row['server_type'],
            'media_username': row['username'], 'mixerbee_username': row['mixerbee_username'],
            'requested_at': row['webhook_setup_requested_at'],
            'acknowledged_at': row['webhook_setup_acknowledged_at'],
            'status': webhook_status(row), 'webhook_url': _webhook_url(request, row),
        })
    return {'requests': requests, 'public_base_url': _webhook_public_base_url(request)}


@router.post('/api/admin/webhook-requests/{connection_id}/acknowledge')
def acknowledge_webhook_request(connection_id: str, request: Request):
    require_admin(request)
    with database.get_db_connection() as conn:
        row = conn.execute('''SELECT id FROM media_connections WHERE id=? AND webhook_secret<>''
            AND webhook_setup_requested_at IS NOT NULL''', (connection_id,)).fetchone()
        if not row:
            raise HTTPException(404, 'Webhook setup request not found.')
        conn.execute('UPDATE media_connections SET webhook_setup_acknowledged_at=? WHERE id=?',
                     (time.time(), connection_id))
        conn.commit()
    return {'status': 'ok', 'webhook_status': 'waiting_for_event',
            'log': ['Webhook marked as installed. MixerBee is waiting for its first valid event.']}


@router.post('/api/admin/settings/webhook-base-url')
def update_webhook_base_url(request: Request, payload: dict):
    require_admin(request)
    value = str(payload.get('url') or '').strip().rstrip('/')
    if value:
        parsed = urlsplit(value)
        if (parsed.scheme not in ('http', 'https') or not parsed.hostname or parsed.username
                or parsed.password or parsed.query or parsed.fragment):
            raise HTTPException(400, 'Use an http:// or https:// URL without credentials, query parameters, or a fragment.')
    with database.get_db_connection() as conn:
        if value:
            conn.execute("INSERT OR REPLACE INTO settings (key,value,updated_at) VALUES ('webhook_public_base_url', ?, CURRENT_TIMESTAMP)", (value,))
        else:
            conn.execute("DELETE FROM settings WHERE key='webhook_public_base_url'")
        conn.commit()
    return {'status': 'ok', 'webhook_public_base_url': value,
            'log': ['Media-server-reachable MixerBee URL saved.' if value else 'Custom webhook base URL cleared.']}


@router.get('/api/connections')
def list_connections(request: Request):
    with database.get_db_connection() as conn:
        return [dict(row) for row in conn.execute('''SELECT c.id, c.label, c.base_url, c.server_type, c.username,
            (SELECT COUNT(*) FROM connection_presets p WHERE p.connection_id=c.id) AS preset_count,
            (SELECT COUNT(*) FROM schedules s WHERE s.connection_id=c.id) AS schedule_count
            FROM media_connections c WHERE c.owner_id=? ORDER BY c.rowid''', (request.state.account['id'],))]


@router.post('/api/connections/{connection_id}/select')
def select_connection(connection_id: str, request: Request):
    from .dependencies import owned_connection
    owned_connection(request, connection_id)
    with database.get_db_connection() as conn:
        conn.execute('UPDATE account_sessions SET connection_id=? WHERE token_hash=?',
                     (connection_id, request.state.account['token_hash']))
        conn.commit()
    return {'status': 'ok', 'connection_id': connection_id}


@router.delete('/api/connections/{connection_id}')
def delete_connection(connection_id: str, request: Request, delete_data: bool = False):
    """Remove one owned connection and its MixerBee-local data.

    Media-server playlists and collections are deliberately untouched.
    """
    from .dependencies import owned_connection
    from app import cache
    from app.ai.vector_store import delete_connection_collection
    from connections import forget_media_client
    import scheduler

    owned_connection(request, connection_id)
    with database.get_db_connection() as conn:
        preset_count = conn.execute(
            'SELECT COUNT(*) FROM connection_presets WHERE connection_id=?', (connection_id,)
        ).fetchone()[0]
        schedule_ids = [row['id'] for row in conn.execute(
            'SELECT id FROM schedules WHERE connection_id=?', (connection_id,)
        )]
    if not delete_data:
        raise HTTPException(409, detail={
            'message': 'Confirm removal of this connection and its local MixerBee data.',
            'preset_count': preset_count,
            'schedule_count': len(schedule_ids),
        })

    for schedule_id in schedule_ids:
        scheduler.scheduler_manager.remove_schedule(schedule_id)

    with database.get_db_connection() as conn:
        conn.execute('BEGIN IMMEDIATE')
        row = conn.execute('SELECT owner_id FROM media_connections WHERE id=?', (connection_id,)).fetchone()
        if not row or row['owner_id'] != request.state.account['id']:
            raise HTTPException(404, 'Connection not found.')
        fallback = conn.execute(
            'SELECT id FROM media_connections WHERE owner_id=? AND id<>? ORDER BY rowid LIMIT 1',
            (request.state.account['id'], connection_id)
        ).fetchone()
        fallback_id = fallback['id'] if fallback else None
        conn.execute('DELETE FROM schedules WHERE connection_id=?', (connection_id,))
        conn.execute('DELETE FROM connection_presets WHERE connection_id=?', (connection_id,))
        conn.execute('UPDATE account_sessions SET connection_id=? WHERE account_id=? AND connection_id=?',
                     (fallback_id, request.state.account['id'], connection_id))
        conn.execute("DELETE FROM settings WHERE key='active_connection_id' AND value=?", (connection_id,))
        conn.execute('DELETE FROM media_connections WHERE id=?', (connection_id,))
        conn.commit()

    forget_media_client(connection_id)
    cache.forget_connection(connection_id)
    delete_connection_collection(connection_id)
    return {'status': 'ok', 'connection_id': fallback_id,
            'log': [f'Removed connection, {preset_count} preset(s), and {len(schedule_ids)} schedule(s). Media-server items were not changed.']}


@router.get('/api/backup/download')
def download_backup(request: Request):
    require_admin(request)
    import app.backup as backup
    archive_path = backup.create_backup_archive()
    filename = archive_path.name
    return FileResponse(
        path=str(archive_path),
        filename=filename,
        media_type='application/zip',
        headers={'X-MixerBee-Warning': 'Contains connection credentials and access keys.'}
    )


@router.post('/api/backup/inspect')
async def inspect_backup(request: Request):
    require_admin(request)
    import app.backup as backup
    import tempfile
    import shutil
    content = await request.body()
    if not content:
        raise HTTPException(400, "Empty backup archive body.")
    temp_dir = Path(tempfile.mkdtemp(prefix="inspect_upload_"))
    try:
        temp_file = temp_dir / "backup.zip"
        with open(temp_file, "wb") as f:
            f.write(content)
        return backup.inspect_backup_archive(temp_file)
    except Exception as e:
        raise HTTPException(400, detail=str(e))
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)


@router.post('/api/backup/restore')
async def restore_backup(request: Request):
    require_admin(request)
    import app.backup as backup
    import tempfile
    import shutil
    content = await request.body()
    if not content:
        raise HTTPException(400, "Empty backup archive body.")
    temp_dir = Path(tempfile.mkdtemp(prefix="restore_upload_"))
    try:
        temp_file = temp_dir / "backup.zip"
        with open(temp_file, "wb") as f:
            f.write(content)
        return backup.restore_backup_archive(temp_file)
    except Exception as e:
        raise HTTPException(400, detail=str(e))
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)


