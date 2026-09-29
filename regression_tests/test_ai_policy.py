"""Offline checks for the account-wide AI switch and deliberate provider setup.

Covers what the switch has to guarantee: it is per account and per installation, it
cannot be bypassed by a direct HTTP call or an external API key, and it never touches
semantic indexing, similarity search, or Echo blocks.
"""
# Import the existing harness first: it isolates runtime paths before app imports.
import test_connections as connection_tests
import json
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

import accounts
import connections
import database
import scheduler
import web
from app import ai_policy
from app.ai import enrichment_manager
from app.media_client import MediaClient

CONFIGURED_OLLAMA = {'AI_PROVIDER': 'ollama', 'OLLAMA_URL': 'http://ollama.local:11434',
                     'OLLAMA_MODEL': 'qwen2.5:7b'}


class AiPolicyTests(unittest.TestCase):
    setUp = connection_tests.ConnectionTests.setUp
    save = connection_tests.ConnectionTests.save

    # --- helpers ----------------------------------------------------------

    def owner(self):
        accounts._attempts.clear()
        client = TestClient(web.app)
        result = client.post('/api/auth/setup', headers={'X-MixerBee-Request': '1'},
                             json={'username': 'owner', 'password': 'owner-password'})
        self.assertEqual(result.status_code, 200, result.text)
        self.pin(client, result.json())
        return client

    def member(self, owner, username='bob'):
        r = owner.post('/api/accounts', json={'username': username, 'password': f'{username}-password'})
        self.assertEqual(r.status_code, 200, r.text)
        client = TestClient(web.app)
        r = client.post('/api/auth/login', headers={'X-MixerBee-Request': '1'},
                        json={'username': username, 'password': f'{username}-password'})
        self.assertEqual(r.status_code, 200, r.text)
        self.pin(client, r.json())
        return client

    def pin(self, client, session):
        client.headers.update({'X-MixerBee-CSRF': session['csrf_token'],
                               'X-MixerBee-Account': session['account']['id'],
                               'X-MixerBee-Connection': session['connection_id'] or '',
                               'X-MixerBee-Request': '1'})

    def add_connection(self, client, user='alice', server='server-a', url='http://a'):
        auth = {'User': {'Id': user, 'Policy': {'IsAdministrator': True}}, 'ServerId': server,
                'AccessToken': 'test-token'}
        with patch.object(MediaClient, 'authenticate', return_value=auth), \
             patch('routers.config.threading.Thread'):
            r = client.post('/api/settings', json={'server_type': 'emby', 'emby_url': url,
                                                   'emby_user': user, 'emby_pass': 'test-password'})
        self.assertEqual(r.status_code, 200, r.text)
        cid = r.json()['connection_id']
        client.headers['X-MixerBee-Connection'] = cid
        return cid

    def configure_ai(self, client, expect=200):
        r = client.post('/api/settings/ai', json={'ai_provider': 'ollama',
                                                  'ollama_url': 'http://ollama.local:11434',
                                                  'ollama_model': 'qwen2.5:7b'})
        self.assertEqual(r.status_code, expect, r.text)
        return r

    def assertConfiguredOllama(self, connection_id):
        stored = self.stored_ai(connection_id)
        for key, value in CONFIGURED_OLLAMA.items():
            self.assertEqual(stored.get(key), value, key)

    def authenticated(self):
        """Let endpoints resolve a MediaClient without touching a real server."""
        return patch.object(MediaClient, 'ensure_authenticated', return_value=None)

    def stored_ai(self, connection_id):
        with database.get_db_connection() as conn:
            row = conn.execute('SELECT ai_settings FROM media_connections WHERE id=?',
                               (connection_id,)).fetchone()
        return json.loads(row['ai_settings'])

    # --- deliberate setup -------------------------------------------------

    def test_media_only_connection_has_no_generative_ai(self):
        """A connection saved with only media credentials must expose nothing AI."""
        owner = self.owner()
        cid = self.add_connection(owner)
        stored = self.stored_ai(cid)
        self.assertEqual(stored['AI_PROVIDER'], '')
        self.assertEqual(stored['OLLAMA_URL'], '')
        self.assertEqual(stored['OLLAMA_MODEL'], '')
        self.assertFalse(ai_policy.generative_available(cid))

        status = owner.get('/api/config_status').json()
        self.assertFalse(status['generative_ai_available'])
        self.assertFalse(status['is_ai_configured'])
        self.assertEqual(status['ai_unavailable_reason'], 'provider_not_configured')
        # Semantic search is core and stays allowed without any provider.
        self.assertTrue(status['semantic_search_allowed'])

    def test_provider_needs_its_own_requirements_only(self):
        """Selecting one provider must never demand the other one's settings."""
        self.assertFalse(ai_policy.provider_configured({}))
        self.assertFalse(ai_policy.provider_configured({'AI_PROVIDER': ''}))
        # Ollama selected with only a default-looking URL is not a configured setup.
        self.assertFalse(ai_policy.provider_configured({'AI_PROVIDER': 'ollama',
                                                        'OLLAMA_URL': 'http://localhost:11434'}))
        self.assertTrue(ai_policy.provider_configured(CONFIGURED_OLLAMA))
        self.assertTrue(ai_policy.provider_configured({'AI_PROVIDER': 'gemini', 'GEMINI_API_KEY': 'k'}))
        # A Gemini key while Ollama is selected is not consent to use Gemini.
        self.assertFalse(ai_policy.provider_configured({'AI_PROVIDER': 'ollama', 'GEMINI_API_KEY': 'k'}))

    def test_connection_save_preserves_configured_provider(self):
        owner = self.owner()
        cid = self.add_connection(owner)
        self.configure_ai(owner)
        self.assertTrue(ai_policy.generative_available(cid))

        # Re-save media credentials, posting stale AI fields the way an old client would.
        auth = {'User': {'Id': 'alice', 'Policy': {'IsAdministrator': True}}, 'ServerId': 'server-a',
                'AccessToken': 'test-token'}
        with patch.object(MediaClient, 'authenticate', return_value=auth), \
             patch('routers.config.threading.Thread'):
            r = owner.post('/api/settings', json={
                'connection_id': cid, 'server_type': 'emby', 'emby_url': 'http://a',
                'emby_user': 'alice', 'emby_pass': 'test-password',
                'ai_provider': 'gemini', 'gemini_key': '', 'ollama_url': '', 'ollama_model': ''})
        self.assertEqual(r.status_code, 200, r.text)
        self.assertConfiguredOllama(cid)
        self.assertTrue(ai_policy.generative_available(cid))

    # --- the account switch ----------------------------------------------

    def test_switch_is_account_wide_and_covers_future_connections(self):
        owner = self.owner()
        first = self.add_connection(owner)
        self.configure_ai(owner)

        r = owner.post('/api/account/preferences', json={'ai_disabled': True})
        self.assertEqual(r.status_code, 200, r.text)
        self.assertTrue(r.json()['ai_disabled'])
        self.assertEqual(r.json()['ai_unavailable_reason'], 'disabled_by_user')
        self.assertFalse(ai_policy.generative_available(first))

        # A second connection added afterwards is covered without being touched.
        second = self.add_connection(owner, user='alice2', server='server-b', url='http://b')
        self.assertFalse(ai_policy.generative_available(second))
        # And provider setup is refused rather than silently succeeding.
        self.configure_ai(owner, expect=403)

        # Credentials on the first connection survived the disable.
        self.assertConfiguredOllama(first)

    def test_other_accounts_are_unaffected(self):
        owner = self.owner()
        owner_cid = self.add_connection(owner)
        self.configure_ai(owner)
        bob = self.member(owner)
        bob_cid = self.add_connection(bob, user='bob', server='server-b', url='http://b')
        self.configure_ai(bob)

        self.assertEqual(owner.post('/api/account/preferences', json={'ai_disabled': True}).status_code, 200)
        self.assertFalse(ai_policy.generative_available(owner_cid))
        self.assertTrue(ai_policy.generative_available(bob_cid))
        self.assertFalse(bob.get('/api/config_status').json()['ai_disabled'])

    def test_preference_survives_logout_and_session_rebuild(self):
        owner = self.owner()
        self.add_connection(owner)
        self.assertEqual(owner.post('/api/account/preferences', json={'ai_disabled': True}).status_code, 200)
        self.assertEqual(owner.post('/api/auth/logout', json={}).status_code, 200)

        again = TestClient(web.app)
        r = again.post('/api/auth/login', headers={'X-MixerBee-Request': '1'},
                       json={'username': 'owner', 'password': 'owner-password'})
        self.assertEqual(r.status_code, 200, r.text)
        self.assertTrue(r.json()['account']['ai_disabled'])
        self.pin(again, r.json())
        self.assertTrue(again.get('/api/config_status').json()['ai_disabled'])

    def test_migration_survives_reinitialising_the_schema(self):
        """Additive migrations run repeatedly; the stored preference must not reset."""
        owner = self.owner()
        self.add_connection(owner)
        self.assertEqual(owner.post('/api/account/preferences', json={'ai_disabled': True}).status_code, 200)
        database.init_db()
        self.assertTrue(owner.get('/api/config_status').json()['ai_disabled'])

    # --- backend enforcement ---------------------------------------------

    def test_direct_http_calls_cannot_bypass_the_switch(self):
        owner = self.owner()
        self.add_connection(owner)
        self.configure_ai(owner)
        self.assertEqual(owner.post('/api/account/preferences', json={'ai_disabled': True}).status_code, 200)

        # 403 with a machine-readable reason, never a generic 500 or an empty result.
        with self.authenticated():
            for method, path, body in (
                ('post', '/api/create_from_text', {'prompt': 'anything'}),
                ('post', '/api/library/enrichment/start', {'batch_size': 1}),
                ('post', '/api/ai/assist/chat', {'prompt': 'hi', 'current_items': [], 'chat_history': []}),
                ('post', '/api/settings/model', {'ollama_model': 'other'}),
            ):
                r = getattr(owner, method)(path, json=body)
                self.assertEqual(r.status_code, 403, f'{path}: {r.text}')
                self.assertEqual(r.json()['detail']['reason'], 'disabled_by_user', path)

            self.assertEqual(owner.get('/api/ollama/status').status_code, 403)
            # Enrichment progress reports unavailable rather than failing.
            self.assertFalse(owner.get('/api/library/iq').json()['available'])
            self.assertEqual(owner.get('/api/library/mood_discovery').json()['tags'], [])

    def test_unconfigured_provider_is_409_not_403(self):
        """A missing setup must stay distinguishable from a deliberate opt-out."""
        owner = self.owner()
        self.add_connection(owner)
        with self.authenticated():
            r = owner.post('/api/create_from_text', json={'prompt': 'anything'})
        self.assertEqual(r.status_code, 409, r.text)
        self.assertEqual(r.json()['detail']['reason'], 'ai_not_configured')

    def test_external_api_key_cannot_outrank_the_account(self):
        owner = self.owner()
        cid = self.add_connection(owner)
        self.configure_ai(owner)
        key = owner.post('/api/settings/external_api_key/regenerate',
                         json={'connection_id': cid}).json()['external_api_key']
        self.assertEqual(owner.post('/api/account/preferences', json={'ai_disabled': True}).status_code, 200)

        external = TestClient(web.app)
        with self.authenticated():
            r = external.post('/api/external/prompt_to_preset', headers={'X-MixerBee-Key': key},
                              json={'prompt': 'anything', 'preset_name': 'From prompt'})
        self.assertEqual(r.status_code, 403, r.text)
        self.assertEqual(r.json()['detail']['reason'], 'disabled_by_user')

    def test_service_layer_blocks_cached_clients_and_jobs(self):
        """A worker holding a cached MediaClient must still be refused."""
        owner = self.owner()
        cid = self.add_connection(owner)
        self.configure_ai(owner)
        media = connections.get_media_client(cid)
        self.assertEqual(owner.post('/api/account/preferences', json={'ai_disabled': True}).status_code, 200)

        with self.assertRaises(ai_policy.AIDisabled):
            enrichment_manager.start_enrichment(cid, media)

        from app.ai import orchestrator
        with patch.object(orchestrator, '_generate_with_ollama',
                          side_effect=AssertionError('provider must not be called')):
            with self.assertRaises(ai_policy.AIDisabled):
                orchestrator.generate_smart_blocks('anything', media=media)

    def test_scheduled_enrichment_is_suspended_not_deleted(self):
        owner = self.owner()
        cid = self.add_connection(owner)
        self.configure_ai(owner)
        with database.get_db_connection() as conn:
            conn.execute("INSERT INTO schedules (id,playlist_name,user_id,job_type,crontab,connection_id,config_data)"
                         " VALUES ('enrich','Nightly tags','alice','enrichment','0 3 * * *',?,'{}')", (cid,))
            conn.commit()
        self.assertEqual(owner.post('/api/account/preferences', json={'ai_disabled': True}).status_code, 200)

        with patch('app.ai.orchestrator.process_enrichment_queue',
                   side_effect=AssertionError('provider must not be called')):
            result = scheduler.run_playlist_job(id='enrich', user_id='alice', playlist_name='Nightly tags',
                                                job_type='enrichment', connection_id=cid,
                                                enrichment_data={'batch_size': 1, 'timeout': 10})
        self.assertEqual(result['status'], 'ok')
        self.assertTrue(result['suspended'])

        # The row and its enabled flag are untouched, and the count is reported.
        with database.get_db_connection() as conn:
            self.assertIsNotNone(conn.execute("SELECT 1 FROM schedules WHERE id='enrich'").fetchone())
        self.assertEqual(owner.get('/api/config_status').json()['retained_ai_schedules'], 1)
        account_id = accounts.authenticate('owner', 'owner-password')['id']
        self.assertEqual(ai_policy.retained_ai_schedule_count(account_id), 1)

    # --- semantic features stay available --------------------------------

    def test_semantic_operations_are_never_gated(self):
        owner = self.owner()
        cid = self.add_connection(owner)
        self.assertEqual(owner.post('/api/account/preferences', json={'ai_disabled': True}).status_code, 200)

        with self.authenticated():
            with patch('app.refresh_semantic_index', return_value={'status': 'ok', 'added': 0,
                                                                  'refreshed': 0, 'removed': 0}) as refresh:
                r = owner.post('/api/library/semantic_refresh', json={})
            self.assertEqual(r.status_code, 200, r.text)
            self.assertTrue(refresh.called)

            with patch('routers.config.reset_media_collection') as reset, \
                 patch('routers.config.threading.Thread'):
                r = owner.post('/api/settings/reset_vector_db', json={'preserve_enrichments': True})
            self.assertEqual(r.status_code, 200, r.text)
            self.assertTrue(reset.called)

            # Stopping a worker must stay usable while disabled.
            self.assertEqual(owner.post('/api/library/enrichment/stop', json={}).status_code, 200)

    def test_echo_blocks_resolve_with_ai_disabled(self):
        """Echo needs the semantic index, not a provider, so it must keep building."""
        owner = self.owner()
        cid = self.add_connection(owner)
        self.assertEqual(owner.post('/api/account/preferences', json={'ai_disabled': True}).status_code, 200)
        media = connections.get_media_client(cid)

        from app import builder
        block = {'type': 'mirror', 'limit': 2,
                 'filters': {'seeds_positive': [{'Id': 'seed'}]}}
        matches = [{'Id': 'one', 'Type': 'Movie'}, {'Id': 'two', 'Type': 'Movie'}]
        with patch('app.ai.vector_store.search_by_composite_similarity',
                   return_value=matches) as search, \
             patch('app.builder.find_movies', return_value=[{'Id': 'one'}, {'Id': 'two'}]):
            items = builder._process_mirror_block(block, 'alice', media, [], 0)
        self.assertTrue(search.called, 'Echo must still reach similarity search')
        self.assertEqual(sorted(item['Id'] for item in items), ['one', 'two'])

    def test_indexing_no_longer_depends_on_a_provider(self):
        """ai_enabled is a generative gate; indexing must not consult it."""
        owner = self.owner()
        cid = self.add_connection(owner)
        media = connections.get_media_client(cid)
        from app.ai import vector_store
        self.assertFalse(vector_store.ai_enabled(media))

        with patch('routers.config.refresh_cache') as refresh, \
             patch('routers.config.ensure_library_indexed', return_value=True) as index:
            from routers import config as config_router
            config_router.warm_connection(media)
        self.assertTrue(refresh.called)
        self.assertTrue(index.called, 'the semantic index must be warmed without a provider')


class ProviderOptinMigrationTests(unittest.TestCase):
    setUp = connection_tests.ConnectionTests.setUp
    save = connection_tests.ConnectionTests.save

    def migrate(self, ai_settings):
        """Save a legacy-shaped connection, clear the marker, and re-run the migration."""
        media = self.save(ai=ai_settings)
        with database.get_db_connection() as conn:
            conn.execute("DELETE FROM settings WHERE key='ai_provider_optin_migrated'")
            ai_policy.migrate_provider_optin(conn)
            conn.commit()
        connections.reload_connections()
        return self.stored(media.connection.id)

    def stored(self, connection_id):
        with database.get_db_connection() as conn:
            row = conn.execute('SELECT ai_settings FROM media_connections WHERE id=?',
                               (connection_id,)).fetchone()
        return json.loads(row['ai_settings'])

    def test_default_only_ollama_needs_one_explicit_save(self):
        stored = self.migrate({'AI_PROVIDER': 'ollama', 'OLLAMA_URL': 'http://localhost:11434',
                               'OLLAMA_MODEL': 'qwen2.5:7b'})
        self.assertEqual(stored['AI_PROVIDER'], '')
        # The values are preserved, so re-enabling is one click rather than re-entry.
        self.assertEqual(stored['OLLAMA_URL'], 'http://localhost:11434')
        self.assertEqual(stored['OLLAMA_MODEL'], 'qwen2.5:7b')

    def test_clearly_configured_providers_are_retained(self):
        for ai in (
            {'AI_PROVIDER': 'gemini', 'GEMINI_API_KEY': 'real-key'},
            {'AI_PROVIDER': 'ollama', 'OLLAMA_URL': 'http://nas:11434', 'OLLAMA_MODEL': 'qwen2.5:7b'},
            {'AI_PROVIDER': 'ollama', 'OLLAMA_URL': 'http://localhost:11434', 'OLLAMA_MODEL': 'mistral-nemo'},
            {'AI_PROVIDER': 'ollama', 'OLLAMA_URL': 'http://localhost:11434',
             'OLLAMA_MODEL': 'qwen2.5:7b', 'STARRED_MODELS': ['qwen2.5:7b']},
        ):
            with self.subTest(ai=ai):
                self.setUp()
                self.assertEqual(self.migrate(ai)['AI_PROVIDER'], ai['AI_PROVIDER'])

    def test_migration_runs_once(self):
        media = self.save(ai={'AI_PROVIDER': 'ollama', 'OLLAMA_URL': 'http://localhost:11434',
                              'OLLAMA_MODEL': 'qwen2.5:7b'})
        with database.get_db_connection() as conn:
            conn.execute("DELETE FROM settings WHERE key='ai_provider_optin_migrated'")
            ai_policy.migrate_provider_optin(conn)
            conn.execute('UPDATE media_connections SET ai_settings=? WHERE id=?',
                         (json.dumps({'AI_PROVIDER': 'ollama', 'OLLAMA_URL': 'http://localhost:11434',
                                      'OLLAMA_MODEL': 'qwen2.5:7b'}), media.connection.id))
            # A second pass must leave a deliberate re-save alone.
            ai_policy.migrate_provider_optin(conn)
            conn.commit()
        self.assertEqual(self.stored(media.connection.id)['AI_PROVIDER'], 'ollama')


if __name__ == '__main__':
    unittest.main()
