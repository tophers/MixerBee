"""Account-wide AI policy, decided from persisted records only.

Two independent questions live here and must not be merged:

* **Generative AI** (prompt-to-blocks, Playlist Assist, enrichment tagging) needs the
  signed-in MixerBee account to allow it *and* the selected media connection to have a
  deliberately configured provider.
* **Semantic search** (ChromaDB embeddings, Echo blocks, vibe similarity) is a core
  library feature. It needs neither a provider nor the account switch, and nothing in
  this module may gate it.

Nothing here imports chromadb or a provider SDK: the policy has to be answerable for a
connection whose vector store has never been opened, and importing vector_store would
construct Chroma's persistent client as a side effect.
"""

import json

import accounts
import database

from .logger import get_logger

logger = get_logger("MixerBee.AIPolicy")

# Reasons returned to the browser alongside a capability payload, and carried on the
# HTTP errors below so a stale tab can tell an opt-out from missing setup.
REASON_DISABLED = 'disabled_by_user'
REASON_NO_CONNECTION = 'no_connection'
REASON_NOT_CONFIGURED = 'provider_not_configured'

VALID_PROVIDERS = ('gemini', 'ollama')


class AIDisabled(PermissionError):
    """The account turned AI features off. Distinct from "not set up yet"."""
    reason = REASON_DISABLED


class AINotConfigured(RuntimeError):
    """AI is allowed for this account but the connection has no provider configured."""
    reason = REASON_NOT_CONFIGURED


def provider_configured(ai_settings) -> bool:
    """True only when a provider was deliberately selected and its requirements are met.

    An absent or empty ``AI_PROVIDER`` is the opt-in signal: a connection saved with
    only media credentials has no provider and therefore no generative AI. A key for
    the provider that is *not* selected does not count -- that ambiguity is what let an
    ordinary connection look like an intentional AI setup.
    """
    ai = ai_settings or {}
    provider = str(ai.get('AI_PROVIDER') or '').strip().lower()
    if provider == 'gemini':
        return bool(str(ai.get('GEMINI_API_KEY') or '').strip())
    if provider == 'ollama':
        return bool(str(ai.get('OLLAMA_URL') or '').strip()
                    and str(ai.get('OLLAMA_MODEL') or '').strip())
    return False


def _load_ai_settings(row_or_settings):
    if row_or_settings is None:
        return {}
    if isinstance(row_or_settings, dict) and 'ai_settings' not in row_or_settings:
        return row_or_settings
    raw = row_or_settings['ai_settings'] if row_or_settings else '{}'
    if isinstance(raw, dict):
        return raw
    try:
        return json.loads(raw or '{}')
    except (TypeError, ValueError):
        return {}


def connection_record(connection_id):
    """The persisted connection row, or None. No media-server contact, no Chroma."""
    if not connection_id:
        return None
    with database.get_db_connection() as conn:
        row = conn.execute('SELECT id, owner_id, ai_settings FROM media_connections WHERE id=?',
                           (connection_id,)).fetchone()
    return dict(row) if row else None


def account_allows_ai(account_id) -> bool:
    """False when this account has opted out. An unknown account allows nothing."""
    if not account_id:
        return False
    return not accounts.ai_disabled(account_id)


def capability(account_id=None, connection_row=None) -> dict:
    """The one capability payload every caller -- HTTP, job, or template -- reads.

    ``connection_row`` may be a ``media_connections`` row (or dict), or None when no
    connection is selected. ``account_id`` may be None to resolve the owner from the
    row, which is what background jobs and external API keys do.
    """
    if account_id is None and connection_row is not None:
        account_id = connection_row.get('owner_id') if isinstance(connection_row, dict) else None
    disabled = bool(account_id) and accounts.ai_disabled(account_id)
    configured = provider_configured(_load_ai_settings(connection_row))

    if disabled:
        reason = REASON_DISABLED
    elif connection_row is None:
        reason = REASON_NO_CONNECTION
    elif not configured:
        reason = REASON_NOT_CONFIGURED
    else:
        reason = ''

    return {
        'ai_disabled': disabled,
        'ai_provider_configured': configured,
        'generative_ai_available': not disabled and configured,
        'ai_unavailable_reason': reason,
        # Semantic search and index maintenance follow the connection, never the switch.
        'semantic_search_allowed': connection_row is not None,
    }


def capability_for_connection(connection_id, account_id=None) -> dict:
    """Capability for a connection id, resolving its owner when no account is given."""
    row = connection_record(connection_id)
    if account_id is None and row:
        account_id = row.get('owner_id')
    return capability(account_id, row)


def generative_available(connection_id, account_id=None) -> bool:
    return capability_for_connection(connection_id, account_id)['generative_ai_available']


def require_generative(connection_id, account_id=None):
    """Service-level gate. Raises AIDisabled or AINotConfigured; returns the capability.

    Worker loops call this again before every provider round so a disable that lands
    mid-run stops the next call instead of waiting for the job to end.
    """
    caps = capability_for_connection(connection_id, account_id)
    if caps['ai_disabled']:
        raise AIDisabled('AI features are turned off for this MixerBee account.')
    if not caps['ai_provider_configured']:
        raise AINotConfigured('No AI provider is configured for this media connection.')
    return caps


def require_generative_http(connection_id, account_id=None):
    """HTTP gate: 403 for a deliberate opt-out, 409 for missing setup.

    Both carry a machine-readable reason so the browser can refresh its capability
    state and hide the control that produced the call, rather than only toasting.
    """
    from fastapi import HTTPException
    try:
        return require_generative(connection_id, account_id)
    except AIDisabled as exc:
        raise HTTPException(403, {'detail': str(exc), 'reason': REASON_DISABLED}) from exc
    except AINotConfigured as exc:
        raise HTTPException(409, {'detail': str(exc), 'reason': REASON_NOT_CONFIGURED}) from exc


def require_account_allows_ai_http(account_id):
    """For deliberate setup steps (provider discovery, saving provider settings).

    Allowed while AI is permitted but not yet configured -- that is exactly the state
    the AI Hub exists to get the user out of -- and refused once the account opts out.
    """
    from fastapi import HTTPException
    if not account_allows_ai(account_id):
        raise HTTPException(403, {'detail': 'AI features are turned off for this MixerBee account.',
                                  'reason': REASON_DISABLED})


def owned_connection_ids(account_id):
    with database.get_db_connection() as conn:
        return [r['id'] for r in conn.execute('SELECT id FROM media_connections WHERE owner_id=?',
                                              (account_id,))]


def retained_ai_schedule_count(account_id) -> int:
    """Enrichment schedules this account still owns while AI is unavailable.

    They are kept with their enabled flags intact and simply skipped, so re-enabling
    resumes them at their next normal occurrence with no missed runs replayed.
    """
    if not account_id:
        return 0
    with database.get_db_connection() as conn:
        row = conn.execute('''SELECT COUNT(*) AS n FROM schedules s
            JOIN media_connections c ON c.id = s.connection_id
            WHERE c.owner_id=? AND s.job_type='enrichment' ''', (account_id,)).fetchone()
    return int(row['n']) if row else 0


# --- One-time opt-in migration -------------------------------------------------

# The values the UI and models.py used to pre-fill, which is why a saved connection
# carrying only these proves nothing about intent.
_DEFAULT_OLLAMA_URLS = {'', 'http://localhost:11434', 'http://127.0.0.1:11434'}
_DEFAULT_OLLAMA_MODELS = {'', 'qwen2.5:7b', 'llama3.1'}


def _legacy_setup_was_deliberate(conn, connection_id, ai) -> bool:
    """Whether a pre-opt-in connection shows evidence of a chosen AI provider.

    A Gemini key is unambiguous. For Ollama the old forms pre-filled a localhost URL
    and a default model on every connection save, so those values alone are not
    consent -- but anything the user had to do by hand is: a non-default URL, model or
    timeout, a starred model, or an enrichment schedule they created.
    """
    if str(ai.get('GEMINI_API_KEY') or '').strip():
        return True
    if str(ai.get('AI_PROVIDER') or '').strip().lower() != 'ollama':
        return False
    if str(ai.get('OLLAMA_URL') or '').strip().rstrip('/') not in _DEFAULT_OLLAMA_URLS:
        return True
    if str(ai.get('OLLAMA_MODEL') or '').strip() not in _DEFAULT_OLLAMA_MODELS:
        return True
    if ai.get('STARRED_MODELS'):
        return True
    try:
        if int(ai.get('OLLAMA_TIMEOUT') or 120) != 120:
            return True
    except (TypeError, ValueError):
        pass
    return conn.execute("SELECT 1 FROM schedules WHERE connection_id=? AND job_type='enrichment' LIMIT 1",
                        (connection_id,)).fetchone() is not None


def migrate_provider_optin(conn):
    """Clear the provider selection on connections that only ever held defaults.

    Runs once, recorded in ``settings``. Credentials, URLs, models and starred lists
    are preserved untouched -- only the selection is cleared, so re-enabling is one
    click in the AI Hub rather than re-entering anything.
    """
    if conn.execute("SELECT 1 FROM settings WHERE key='ai_provider_optin_migrated'").fetchone():
        return
    for row in conn.execute('SELECT id, ai_settings FROM media_connections').fetchall():
        try:
            ai = json.loads(row['ai_settings'] or '{}')
        except (TypeError, ValueError):
            continue
        if not isinstance(ai, dict) or not str(ai.get('AI_PROVIDER') or '').strip():
            continue
        if _legacy_setup_was_deliberate(conn, row['id'], ai):
            continue
        ai['AI_PROVIDER'] = ''
        conn.execute('UPDATE media_connections SET ai_settings=? WHERE id=?',
                     (json.dumps(ai), row['id']))
        logger.info('AI provider selection cleared for connection %s: only default values were '
                     'stored, so it needs one explicit save in the AI Hub.', row['id'])
    conn.execute("INSERT OR REPLACE INTO settings (key, value) VALUES ('ai_provider_optin_migrated', '1')")
