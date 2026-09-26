"""Saved media connections for account workspaces and connection-bound jobs.

HTTP callers must check account ownership before resolving a client. Background
jobs resolve their saved connection directly.
"""
import json
import threading
import uuid

import database
from app.media_client import Connection, MediaClient

_clients = {}
_clients_lock = threading.Lock()


def initialize_schema(conn):
    conn.execute('''CREATE TABLE IF NOT EXISTS media_connections (
        id TEXT PRIMARY KEY, base_url TEXT NOT NULL, server_type TEXT NOT NULL,
        username TEXT NOT NULL, password TEXT NOT NULL, user_id TEXT NOT NULL,
        server_id TEXT NOT NULL, ai_settings TEXT NOT NULL DEFAULT '{}'
    )''')
    columns = {r['name'] for r in conn.execute('PRAGMA table_info(media_connections)')}
    for name, definition in (
        ('owner_id', 'TEXT REFERENCES accounts(id)'), ('label', "TEXT NOT NULL DEFAULT ''"),
        ('webhook_secret', "TEXT NOT NULL DEFAULT ''"), ('api_key_hash', "TEXT NOT NULL DEFAULT ''"),
        ('api_key', "TEXT NOT NULL DEFAULT ''"),
        ('webhook_secret_updated_at', 'REAL'), ('webhook_setup_requested_at', 'REAL'),
        ('webhook_setup_acknowledged_at', 'REAL'), ('webhook_verified_at', 'REAL'),
        ('webhook_last_received_at', 'REAL')
    ):
        if name not in columns:
            conn.execute(f'ALTER TABLE media_connections ADD COLUMN {name} {definition}')
    if 'connection_id' not in {r['name'] for r in conn.execute('PRAGMA table_info(schedules)')}:
        conn.execute('ALTER TABLE schedules ADD COLUMN connection_id TEXT REFERENCES media_connections(id)')
    conn.execute('''CREATE TABLE IF NOT EXISTS connection_presets (
        id TEXT PRIMARY KEY, connection_id TEXT NOT NULL REFERENCES media_connections(id),
        name TEXT NOT NULL, data TEXT NOT NULL,
        UNIQUE(connection_id, name)
    )''')
    schedule_columns = {r['name'] for r in conn.execute('PRAGMA table_info(schedules)')}
    if 'preset_id' not in schedule_columns:
        conn.execute('ALTER TABLE schedules ADD COLUMN preset_id TEXT REFERENCES connection_presets(id)')
    backfill_schedule_preset_ids(conn)


def webhook_status(row):
    """Return the user-facing state for a connection's current webhook secret."""
    if not row or not row.get('webhook_secret'):
        return 'disabled'
    changed = row.get('webhook_secret_updated_at') or 0
    if (row.get('webhook_verified_at') or 0) >= changed and row.get('webhook_verified_at'):
        return 'connected'
    if (row.get('webhook_setup_acknowledged_at') or 0) >= changed:
        return 'waiting_for_event'
    if (row.get('webhook_setup_requested_at') or 0) >= changed:
        return 'setup_requested'
    return 'needs_setup'


def backfill_schedule_preset_ids(conn, connection_id=None):
    """Bind legacy name-based schedules to the matching preset in their connection."""
    params = () if connection_id is None else (connection_id,)
    where = ('WHERE s.preset_id IS NULL AND s.job_type IN (\'builder\', \'preset\')' if connection_id is None
             else 'WHERE s.preset_id IS NULL AND s.job_type IN (\'builder\', \'preset\') AND s.connection_id=?')
    rows = conn.execute(
        f'SELECT s.id, s.connection_id, s.config_data FROM schedules s {where}', params
    ).fetchall()
    for row in rows:
        if not row['connection_id'] or not row['config_data']:
            continue
        try:
            config_data = json.loads(row['config_data'])
        except (TypeError, json.JSONDecodeError):
            continue
        preset_name = config_data.get('preset_name') if isinstance(config_data, dict) else None
        if not preset_name:
            continue
        preset = conn.execute(
            'SELECT id FROM connection_presets WHERE connection_id=? AND name=?',
            (row['connection_id'], preset_name)
        ).fetchone()
        if preset:
            conn.execute('UPDATE schedules SET preset_id=? WHERE id=?', (preset['id'], row['id']))


def save_authenticated_connection(base_url, server_type, username, password, auth, ai_settings, *, owner_id=None, existing_id=None, label=""):
    """Only called after authentication. Existing connections survive active-user changes."""
    user_id = auth['User']['Id']
    server_id = auth.get('ServerId') or ''
    base_url = base_url.rstrip('/')
    # Server identity is preferable to a URL alias; type is part of the namespace.
    identity = f'{server_type}:{server_id or base_url}:{user_id}'
    if owner_id:
        identity = f'{owner_id}:{identity}'
    connection_id = uuid.uuid5(uuid.NAMESPACE_URL, identity).hex
    with database.get_db_connection() as conn:
        if owner_id is None and conn.execute('SELECT 1 FROM accounts LIMIT 1').fetchone():
            raise ValueError('Local accounts are enabled; configure connections while signed in.')
        if existing_id:
            existing = conn.execute('SELECT * FROM media_connections WHERE id=? AND owner_id=?', (existing_id, owner_id)).fetchone()
            if not existing:
                raise ValueError('Connection not found.')
            if existing['user_id'] != user_id or existing['server_type'] != server_type or (existing['server_id'] and existing['server_id'] != server_id):
                raise ValueError('This is a different server or media account. Add a new connection instead.')
            connection_id = existing_id
        elif owner_id:
            existing = conn.execute("SELECT id FROM media_connections WHERE owner_id=? AND server_type=? AND user_id=? AND ((server_id=? AND server_id!='') OR (server_id='' AND base_url=?))",
                                    (owner_id, server_type, user_id, server_id, base_url)).fetchone()
            if existing:
                connection_id = existing['id']
        conn.execute('''INSERT INTO media_connections
            (id, base_url, server_type, username, password, user_id, server_id, ai_settings)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET base_url=excluded.base_url,
            username=excluded.username, password=excluded.password, ai_settings=excluded.ai_settings''',
            (connection_id, base_url, server_type, username, password, user_id, server_id, json.dumps(ai_settings)))
        if owner_id:
            conn.execute('UPDATE media_connections SET owner_id=?, label=? WHERE id=?', (owner_id, label, connection_id))
        # Claim legacy presets once, never each time .env changes. Original tables
        # stay intact for rollback. Jobs with a different user remain unassigned.
        migrated = conn.execute("SELECT value FROM settings WHERE key='connection_migration_completed'").fetchone()
        migrate_legacy = owner_id is None
        if owner_id and not migrated:
            owner = conn.execute('SELECT is_admin FROM accounts WHERE id=?', (owner_id,)).fetchone()
            other_connections = conn.execute(
                'SELECT 1 FROM media_connections WHERE owner_id=? AND id<>? LIMIT 1',
                (owner_id, connection_id)
            ).fetchone()
            migrate_legacy = bool(owner and owner['is_admin'] and not other_connections)
        if not migrated and migrate_legacy:
            for row in conn.execute('SELECT name, data FROM presets').fetchall():
                conn.execute('INSERT OR IGNORE INTO connection_presets (id, connection_id, name, data) VALUES (?, ?, ?, ?)',
                             (uuid.uuid4().hex, connection_id, row['name'], row['data']))
            conn.execute('UPDATE schedules SET connection_id=? WHERE connection_id IS NULL AND user_id=?',
                         (connection_id, user_id))
            backfill_schedule_preset_ids(conn, connection_id)
            conn.execute("INSERT INTO settings (key,value) VALUES ('connection_migration_completed', ?)", (connection_id,))
        if owner_id is None:
            conn.execute("INSERT OR REPLACE INTO settings (key,value) VALUES ('active_connection_id', ?)", (connection_id,))
        conn.commit()
    connection = Connection(connection_id, base_url, server_type, username, password, user_id, server_id, dict(ai_settings))
    media = MediaClient(connection, token=auth['AccessToken'], user_profile=auth.get('User'))
    with _clients_lock:
        _clients[connection_id] = media
    return media


def active_connection_id():
    with database.get_db_connection() as conn:
        row = conn.execute("SELECT value FROM settings WHERE key='active_connection_id'").fetchone()
    return row['value'] if row else None


def get_media_client(connection_id):
    if not connection_id:
        raise ValueError('No saved media connection. Configure the server in Settings.')
    with database.get_db_connection() as conn:
        row = conn.execute('SELECT * FROM media_connections WHERE id=?', (connection_id,)).fetchone()
    if row is None:
        raise ValueError('Saved media connection no longer exists.')
    fields = ('id', 'base_url', 'server_type', 'username', 'password', 'user_id', 'server_id', 'ai_settings')
    data = {key: row[key] for key in fields}
    data['ai_settings'] = json.loads(data['ai_settings'])
    connection = Connection(**data)
    with _clients_lock:
        media = _clients.get(connection_id)
        if media is None or media.connection != connection:
            media = MediaClient(connection)
            _clients[connection_id] = media
    return media


def active_media_client():
    return get_media_client(active_connection_id())


def all_media_clients():
    with database.get_db_connection() as conn:
        ids = [row['id'] for row in conn.execute('SELECT id FROM media_connections')]
    return [get_media_client(cid) for cid in ids]


def forget_media_client(connection_id):
    """Drop a removed connection from the process-local client registry."""
    with _clients_lock:
        _clients.pop(connection_id, None)


def update_active_ai_setting(key, value):
    media = active_media_client()
    settings = dict(media.connection.ai_settings)
    settings[key] = value
    with database.get_db_connection() as conn:
        conn.execute('UPDATE media_connections SET ai_settings=? WHERE id=?',
                     (json.dumps(settings), media.connection.id))
        conn.commit()
