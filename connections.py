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
    preset_columns = {r['name'] for r in conn.execute('PRAGMA table_info(connection_presets)')}
    if 'tags_json' not in preset_columns:
        conn.execute("ALTER TABLE connection_presets ADD COLUMN tags_json TEXT NOT NULL DEFAULT '[]'")
    if 'is_favorite' not in preset_columns:
        conn.execute("ALTER TABLE connection_presets ADD COLUMN is_favorite INTEGER NOT NULL DEFAULT 0")

    conn.execute('''CREATE TABLE IF NOT EXISTS connection_recipes (
        id TEXT PRIMARY KEY,
        connection_id TEXT NOT NULL REFERENCES media_connections(id),
        name TEXT NOT NULL,
        description TEXT NOT NULL DEFAULT '',
        block_json TEXT NOT NULL,
        tags_json TEXT NOT NULL DEFAULT '[]',
        is_favorite INTEGER NOT NULL DEFAULT 0,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )''')
    conn.execute('CREATE INDEX IF NOT EXISTS idx_recipes_conn ON connection_recipes(connection_id)')

    schedule_columns = {r['name'] for r in conn.execute('PRAGMA table_info(schedules)')}
    if 'preset_id' not in schedule_columns:
        conn.execute('ALTER TABLE schedules ADD COLUMN preset_id TEXT REFERENCES connection_presets(id)')
    backfill_schedule_preset_ids(conn)
    from app.ai_policy import migrate_provider_optin
    migrate_provider_optin(conn)


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


def save_authenticated_connection(base_url, server_type, username, password, auth, ai_settings=None, *, owner_id=None, existing_id=None, label=""):
    """Only called after authentication. Existing connections survive active-user changes.

    ``ai_settings`` seeds a *new* connection only. An update never rewrites the stored
    AI settings: saving media credentials used to rebuild that JSON from whatever the
    connection form happened to hold, which erased a provider key the user configured
    from the AI Hub. Provider changes go through /api/settings/ai instead.
    """
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
            username=excluded.username, password=excluded.password''',
            (connection_id, base_url, server_type, username, password, user_id, server_id,
             json.dumps(dict(ai_settings or {}))))
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
    # Read back rather than trusting the argument: on an update the stored AI settings
    # were deliberately left alone, so they are the only correct value here.
    with database.get_db_connection() as conn:
        stored = conn.execute('SELECT ai_settings FROM media_connections WHERE id=?', (connection_id,)).fetchone()
    try:
        saved_ai = json.loads(stored['ai_settings'] or '{}') if stored else {}
    except (TypeError, ValueError):
        saved_ai = {}
    connection = Connection(connection_id, base_url, server_type, username, password, user_id, server_id, saved_ai)
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


def delete_connection_data(conn, connection_id):
    """Delete local SQL data inside the caller's transaction; never contact a server."""
    schedule_ids = [row['id'] for row in conn.execute(
        'SELECT id FROM schedules WHERE connection_id=?', (connection_id,))]
    conn.execute('DELETE FROM schedules WHERE connection_id=?', (connection_id,))
    conn.execute('DELETE FROM connection_presets WHERE connection_id=?', (connection_id,))
    conn.execute('DELETE FROM connection_recipes WHERE connection_id=?', (connection_id,))
    # build_run_items cascade from build_runs.
    conn.execute('DELETE FROM build_runs WHERE connection_id=?', (connection_id,))
    conn.execute('UPDATE account_sessions SET connection_id=NULL WHERE connection_id=?', (connection_id,))
    conn.execute("DELETE FROM settings WHERE key='active_connection_id' AND value=?", (connection_id,))
    conn.execute('DELETE FROM media_connections WHERE id=?', (connection_id,))
    return schedule_ids


def cleanup_deleted_connection(connection_id, schedule_ids):
    """Retire runtime jobs, credentials, caches and the AI index after SQL commits."""
    import scheduler
    from app import cache
    from app.ai.enrichment_manager import stop_enrichment
    from app.ai.vector_store import delete_connection_collection

    stop_enrichment(connection_id)
    for schedule_id in schedule_ids:
        scheduler.scheduler_manager.remove_schedule(schedule_id)
        scheduler._cancel_orphaned_jobs(schedule_id)
    forget_media_client(connection_id)
    cache.forget_connection(connection_id)
    delete_connection_collection(connection_id)


def update_active_ai_setting(key, value):
    media = active_media_client()
    settings = dict(media.connection.ai_settings)
    settings[key] = value
    with database.get_db_connection() as conn:
        conn.execute('UPDATE media_connections SET ai_settings=? WHERE id=?',
                     (json.dumps(settings), media.connection.id))
        conn.commit()


def reload_connections():
    """Clear cached connection media clients to pick up reloaded database state."""
    with _clients_lock:
        _clients.clear()
