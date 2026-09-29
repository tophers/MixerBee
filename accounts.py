"""Local accounts and revocable browser sessions, independent of media servers."""
import hashlib
import hmac
import os
import re
import secrets
import sqlite3
import threading
import time
import uuid
from collections import defaultdict, deque
from pathlib import Path

import database

SESSION_SECONDS = 7 * 24 * 3600
_rate_lock = threading.Lock()
_attempts = defaultdict(deque)


def initialize_schema(conn):
    conn.execute('''CREATE TABLE IF NOT EXISTS accounts (
        id TEXT PRIMARY KEY, username TEXT NOT NULL, username_key TEXT NOT NULL UNIQUE,
        password_hash TEXT NOT NULL, is_admin INTEGER NOT NULL DEFAULT 0,
        created_at REAL NOT NULL
    )''')
    conn.execute('''CREATE TABLE IF NOT EXISTS account_sessions (
        token_hash TEXT PRIMARY KEY, account_id TEXT NOT NULL REFERENCES accounts(id),
        csrf_token TEXT NOT NULL, connection_id TEXT,
        expires_at REAL NOT NULL
    )''')
    columns = {r['name'] for r in conn.execute('PRAGMA table_info(accounts)')}
    for name, definition in (('ai_disabled', 'INTEGER NOT NULL DEFAULT 0'),):
        if name not in columns:
            conn.execute(f'ALTER TABLE accounts ADD COLUMN {name} {definition}')


def setup_required():
    with database.get_db_connection() as conn:
        return conn.execute('SELECT 1 FROM accounts LIMIT 1').fetchone() is None


def setup_token_path():
    return database.DB_PATH.parent / 'setup-token'


def ensure_setup_token():
    pass


def check_rate_limit(key):
    now = time.monotonic()
    with _rate_lock:
        # Bound storage even when requests arrive under many client addresses.
        for old in list(_attempts):
            if not _attempts[old] or _attempts[old][-1] < now - 60:
                del _attempts[old]
        attempts = _attempts[key]
        while attempts and attempts[0] < now - 60:
            attempts.popleft()
        if len(attempts) >= 10:
            return False
        attempts.append(now)
        return True


def validate_credentials(username, password):
    username = username.strip()
    if not re.fullmatch(r'[A-Za-z0-9_.-]{1,64}', username):
        raise ValueError('Username must use 1–64 letters, numbers, dots, underscores, or hyphens.')
    if not 10 <= len(password) <= 256:
        raise ValueError('Password must contain 10–256 characters.')
    return username


def hash_password(password):
    salt = secrets.token_bytes(16)
    value = hashlib.scrypt(password.encode(), salt=salt, n=32768, r=8, p=1, maxmem=64 * 1024 * 1024)
    return f'scrypt${salt.hex()}${value.hex()}'


def verify_password(password, encoded):
    try:
        if len(password) > 256:
            return False
        algorithm, salt, expected = encoded.split('$')
        if algorithm != 'scrypt':
            return False
        actual = hashlib.scrypt(password.encode(), salt=bytes.fromhex(salt), n=32768, r=8, p=1, maxmem=64 * 1024 * 1024)
        return hmac.compare_digest(actual.hex(), expected)
    except (ValueError, TypeError):
        return False


def create_account(username, password, *, initial_only=False, bootstrap_token=None):
    username = validate_credentials(username, password)
    encoded = hash_password(password)
    aid = uuid.uuid4().hex
    with database.get_db_connection() as conn:
        conn.execute('BEGIN IMMEDIATE')
        first = conn.execute('SELECT 1 FROM accounts LIMIT 1').fetchone() is None
        if initial_only and not first:
            raise PermissionError('Initial setup is already complete.')
        try:
            # Named columns, not positional: this table gains columns over time and a
            # bare VALUES tuple breaks the next time one is added.
            conn.execute('INSERT INTO accounts (id, username, username_key, password_hash, is_admin, created_at)'
                         ' VALUES (?, ?, ?, ?, ?, ?)',
                         (aid, username, username.casefold(), encoded, int(first), time.time()))
        except sqlite3.IntegrityError as exc:
            raise ValueError('That username is already in use.') from exc
        if first:
            # Claim existing connection IDs without changing presets, schedules,
            # vector namespaces, or browser draft keys.
            conn.execute('UPDATE media_connections SET owner_id=? WHERE owner_id IS NULL', (aid,))
        conn.commit()
    return {'id': aid, 'username': username, 'is_admin': first, 'ai_disabled': False}


def authenticate(username, password):
    with database.get_db_connection() as conn:
        row = conn.execute('SELECT * FROM accounts WHERE username_key=?', (username.strip().casefold(),)).fetchone()
    if row is None:
        # Do comparable password work for nonexistent accounts.
        verify_password(password, 'scrypt$' + '00' * 16 + '$' + '00' * 64)
        return None
    if not verify_password(password, row['password_hash']):
        return None
    return {'id': row['id'], 'username': row['username'], 'is_admin': bool(row['is_admin']),
            'ai_disabled': bool(row['ai_disabled'])}


def token_hash(value):
    return hashlib.sha256(value.encode()).hexdigest()


def create_session(account_id):
    token, csrf = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
    with database.get_db_connection() as conn:
        row = conn.execute('SELECT id FROM media_connections WHERE owner_id=? ORDER BY rowid LIMIT 1', (account_id,)).fetchone()
        cid = row['id'] if row else None
        conn.execute('DELETE FROM account_sessions WHERE expires_at < ?', (time.time(),))
        conn.execute('INSERT INTO account_sessions VALUES (?, ?, ?, ?, ?)',
                     (token_hash(token), account_id, csrf, cid, time.time() + SESSION_SECONDS))
        conn.commit()
    return token, csrf


def read_session(token):
    if not token or len(token) > 256:
        return None
    with database.get_db_connection() as conn:
        row = conn.execute('''SELECT a.id, a.username, a.is_admin, a.ai_disabled, s.csrf_token,
            s.connection_id, s.token_hash FROM account_sessions s
            JOIN accounts a ON a.id=s.account_id WHERE s.token_hash=? AND s.expires_at>?''',
            (token_hash(token), time.time())).fetchone()
    return dict(row) if row else None


def revoke_session(token):
    with database.get_db_connection() as conn:
        conn.execute('DELETE FROM account_sessions WHERE token_hash=?', (token_hash(token),))
        conn.commit()


def change_password(account_id, password):
    validate_credentials('valid', password)
    encoded = hash_password(password)
    with database.get_db_connection() as conn:
        conn.execute('UPDATE accounts SET password_hash=? WHERE id=?', (encoded, account_id))
        conn.execute('DELETE FROM account_sessions WHERE account_id=?', (account_id,))
        conn.commit()


def ai_disabled(account_id):
    """The account-wide AI opt-out, read from the database rather than a cached session."""
    with database.get_db_connection() as conn:
        row = conn.execute('SELECT ai_disabled FROM accounts WHERE id=?', (account_id,)).fetchone()
    return bool(row['ai_disabled']) if row else False


def set_ai_disabled(account_id, disabled):
    """Persist the account-wide AI preference.

    Sessions stay valid: this is a preference, not a credential, and signing every
    browser out would lose unsaved Builder drafts for no security benefit.
    """
    with database.get_db_connection() as conn:
        cursor = conn.execute('UPDATE accounts SET ai_disabled=? WHERE id=?',
                              (1 if disabled else 0, account_id))
        conn.commit()
    if not cursor.rowcount:
        raise ValueError('Account not found.')
    return bool(disabled)


def cookie_name(request):
    # Browser cookies ignore TCP ports. Separate local dev/prod instances on one
    # hostname must not overwrite each other's cookies.
    origin = str(request.url.netloc) + request.scope.get('root_path', '')
    return 'mixerbee_session_' + hashlib.sha256(origin.encode()).hexdigest()[:12]
