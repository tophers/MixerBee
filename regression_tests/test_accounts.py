"""Offline HTTP isolation and migration checks for local MixerBee accounts."""
# Import the existing harness first: it isolates runtime paths before app imports.
import test_connections as connection_tests
import json
import asyncio
import io
import logging
import os
import sqlite3
import time
import unittest
from unittest.mock import patch, Mock
from concurrent.futures import ThreadPoolExecutor
from fastapi.testclient import TestClient

import accounts
import connections
import database
import scheduler
import web
import app_state
from app.logger import get_logger, refresh_logger_level
from app.media_client import MediaClient
from preset_manager import preset_manager
from app import build_history, cache
from app.ai import vector_store, enrichment_manager
from app.media_client import media_scope


class AccountTests(unittest.TestCase):
    setUp = connection_tests.ConnectionTests.setUp
    save = connection_tests.ConnectionTests.save

    def bootstrap(self, legacy=True):
        media = self.save() if legacy else None
        accounts._attempts.clear()
        client = TestClient(web.app)
        result = client.post('/api/auth/setup', headers={'X-MixerBee-Request': '1'}, json={
            'username': 'owner', 'password': 'owner-password'})
        self.assertEqual(result.status_code, 200, result.text)
        self.pin(client, result.json())
        return client, media

    def pin(self, client, session):
        client.headers.update({'X-MixerBee-CSRF': session['csrf_token'], 'X-MixerBee-Account': session['account']['id'],
                               'X-MixerBee-Connection': session['connection_id'] or '', 'X-MixerBee-Request': '1'})

    def bob(self, owner):
        r = owner.post('/api/accounts', json={'username': 'bob', 'password': 'bob-password'})
        self.assertEqual(r.status_code, 200, r.text)
        client = TestClient(web.app)
        r = client.post('/api/auth/login', headers={'X-MixerBee-Request': '1'}, json={'username': 'bob', 'password': 'bob-password'})
        self.assertEqual(r.status_code, 200, r.text)
        self.pin(client, r.json())
        return client

    def save_http(self, client, user='bob', server='server-a', **extra):
        payload = {'server_type': 'emby', 'emby_url': 'http://a', 'emby_user': user, 'emby_pass': 'test-password'} | extra
        auth = {'User': {'Id': user, 'Policy': {'IsAdministrator': True}}, 'ServerId': server, 'AccessToken': 'test-token'}
        with patch.object(MediaClient, 'authenticate', return_value=auth), patch('routers.config.threading.Thread'):
            return client.post('/api/settings', json=payload)

    def test_bootstrap_claims_ids_without_changing_presets_or_jobs(self):
        media = self.save()
        preset_manager.save_preset('Evening', [], media.connection.id)
        with database.get_db_connection() as conn:
            conn.execute("INSERT INTO schedules (id,playlist_name,user_id,job_type,crontab,connection_id) VALUES ('job','Test','alice','builder','0 12 * * *',?)", (media.connection.id,))
            conn.commit()
        owner, _ = self.bootstrap(legacy=False)
        owned = owner.get('/api/connections').json()
        self.assertEqual([r['id'] for r in owned], [media.connection.id])
        self.assertEqual(owner.get('/api/presets').json(), {'Evening': []})
        database.init_db()
        self.assertFalse(accounts.setup_token_path().exists())
        self.assertEqual(preset_manager.get_all_presets(media.connection.id), {'Evening': []})
        with database.get_db_connection() as conn:
            self.assertEqual(conn.execute('SELECT connection_id FROM schedules').fetchone()[0], media.connection.id)
            row = conn.execute('SELECT password_hash FROM accounts').fetchone()
            self.assertTrue(row[0].startswith('scrypt$'))
            self.assertNotIn('owner-password', row[0])
        with self.assertRaises(ValueError):
            self.save('someone-else')  # .env cannot silently add unowned connections after setup.

    def test_setup_and_admin_creation_enforced(self):
        owner, _ = self.bootstrap()
        anon = TestClient(web.app)
        self.assertEqual(anon.post('/api/auth/setup', headers={'X-MixerBee-Request': '1'}, json={
            'username': 'another', 'password': 'test-password'}).status_code, 403)
        bob = self.bob(owner)
        self.assertEqual(bob.get('/api/accounts').status_code, 403)
        self.assertEqual(bob.post('/api/accounts', json={'username': 'third', 'password': 'test-password'}).status_code, 403)
        self.assertEqual(owner.post('/api/accounts', json={'username': 'BOB', 'password': 'test-password'}).status_code, 400)

    def test_owner_logging_toggle_persists_and_changes_output_without_connection(self):
        owner, _ = self.bootstrap(legacy=False)
        self.addCleanup(refresh_logger_level)
        with patch.object(app_state, 'VERBOSE_LOGGING', False):
            logger = get_logger('MixerBee.LoggingTest')
            output = io.StringIO()
            handler = logging.StreamHandler(output)
            logger.addHandler(handler)
            self.addCleanup(logger.removeHandler, handler)
            path = '/api/admin/settings/logging'
            self.assertEqual(owner.get(path).json(), {'verbose_logging': False})
            for enabled in (True, False):
                output.truncate(0)
                output.seek(0)
                res = owner.post(path, json={'verbose_logging': enabled})
                self.assertEqual(res.status_code, 200, res.text)
                self.assertEqual(res.json()['verbose_logging'], enabled)
                self.assertEqual(app_state.VERBOSE_LOGGING, enabled)
                self.assertEqual(owner.get(path).json()['verbose_logging'], enabled)
                with database.get_db_connection() as conn:
                    self.assertEqual(conn.execute(
                        "SELECT value FROM settings WHERE key='VERBOSE_LOGGING'").fetchone()[0],
                        'true' if enabled else 'false')
                logger.info('detail')
                logger.warning('warning')
                self.assertEqual('detail' in output.getvalue(), enabled)
                self.assertIn('warning', output.getvalue())
                expected = logging.INFO if enabled else logging.WARNING
                self.assertEqual(logging.getLogger('apscheduler').level, expected)
                self.assertEqual(get_logger('MixerBee.LoggingTest.New').level, expected)

    def test_logging_settings_require_owner_session_csrf_and_boolean(self):
        owner, _ = self.bootstrap(legacy=False)
        member = self.bob(owner)
        anon = TestClient(web.app)
        path = '/api/admin/settings/logging'
        for client, status in ((anon, 401), (member, 403)):
            self.assertEqual(client.get(path).status_code, status)
            self.assertEqual(client.post(path, json={'verbose_logging': True}).status_code, status)
        self.assertEqual(anon.get(path, headers={'X-MixerBee-Key': 'external-key'}).status_code, 401)
        self.assertEqual(owner.post(path, json={'verbose_logging': True},
                                    headers={'X-MixerBee-CSRF': ''}).status_code, 409)
        for value in ('false', 1, None):
            self.assertEqual(owner.post(path, json={'verbose_logging': value}).status_code, 422)
        with database.get_db_connection() as conn:
            self.assertIsNone(conn.execute("SELECT value FROM settings WHERE key='VERBOSE_LOGGING'").fetchone())

    def test_startup_loads_logging_after_setup_without_importing_legacy_settings(self):
        self.bootstrap(legacy=False)
        self.addCleanup(refresh_logger_level)
        with database.get_db_connection() as conn:
            conn.execute("INSERT INTO settings (key,value) VALUES ('VERBOSE_LOGGING','true')")
            conn.commit()

        async def startup():
            async with web.lifespan(web.app):
                self.assertTrue(app_state.VERBOSE_LOGGING)
                self.assertEqual(logging.getLogger('apscheduler').level, logging.INFO)

        with patch.object(app_state, 'VERBOSE_LOGGING', False), \
                patch.object(app_state, 'load_and_authenticate') as legacy, \
                patch.object(app_state, 'sync_env_to_db') as env_sync, \
                patch.object(app_state, 'load_settings_from_db') as legacy_settings, \
                patch('web.threading.Thread'), \
                patch.object(scheduler.scheduler_manager, 'start'), \
                patch.object(scheduler.scheduler_manager.scheduler, 'shutdown'):
            asyncio.run(startup())
            legacy.assert_not_called()
            env_sync.assert_not_called()
            legacy_settings.assert_not_called()

    def test_failed_logging_save_preserves_runtime_level(self):
        self.addCleanup(refresh_logger_level)
        with patch.object(app_state, 'VERBOSE_LOGGING', False):
            logger = get_logger('MixerBee.LoggingTest')
            with patch.object(database, 'get_db_connection', side_effect=sqlite3.OperationalError('unavailable')):
                with self.assertRaises(sqlite3.OperationalError):
                    app_state.set_verbose_logging(True)
            self.assertFalse(app_state.VERBOSE_LOGGING)
            self.assertEqual(logger.level, logging.WARNING)

    def test_legacy_env_logging_preference_can_still_be_imported(self):
        self.addCleanup(refresh_logger_level)
        env_path = database.DB_PATH.parent / '.env'
        env_path.write_text('VERBOSE_LOGGING=yes\n')
        with patch.object(app_state, 'VERBOSE_LOGGING', False), \
                patch.object(app_state, 'ENV_PATH', env_path), patch.dict(os.environ):
            app_state.sync_env_to_db()
            self.assertTrue(app_state.load_logging_settings())
            self.assertEqual(logging.getLogger('apscheduler').level, logging.INFO)

    def test_remove_member_requires_owner_confirmation_and_csrf(self):
        owner, _ = self.bootstrap()
        bob = self.bob(owner)
        aid = bob.headers['X-MixerBee-Account']
        path = f'/api/accounts/{aid}?delete_data=true'
        self.assertEqual(TestClient(web.app).delete(path).status_code, 401)
        self.assertEqual(bob.delete(path).status_code, 403)
        self.assertEqual(owner.delete(path, headers={'X-MixerBee-CSRF': ''}).status_code, 409)
        self.assertEqual(owner.delete(f'/api/accounts/{aid}').status_code, 400)
        self.assertEqual(owner.delete(
            f'/api/accounts/{owner.headers["X-MixerBee-Account"]}?delete_data=true').status_code, 403)
        # Protect every owner, not just the caller.
        with database.get_db_connection() as conn:
            conn.execute('UPDATE accounts SET is_admin=1 WHERE id=?', (aid,))
            conn.commit()
        self.assertEqual(owner.delete(path).status_code, 403)
        self.assertIsNotNone(accounts.authenticate('bob', 'bob-password'))
        self.assertEqual(len(owner.get('/api/accounts').json()), 2)

    def test_remove_member_without_connections_and_repeated_removal(self):
        owner, _ = self.bootstrap(legacy=False)
        bob = self.bob(owner)
        aid = bob.headers['X-MixerBee-Account']
        second_token, _ = accounts.create_session(aid)
        path = f'/api/accounts/{aid}?delete_data=true'
        self.assertEqual(owner.delete(path).status_code, 200)
        self.assertEqual(owner.delete(path).status_code, 404)
        self.assertEqual(bob.get('/api/connections').status_code, 401)
        self.assertIsNone(accounts.read_session(second_token))
        self.assertIsNone(accounts.authenticate('bob', 'bob-password'))
        self.assertFalse(accounts.setup_required())
        self.assertEqual(owner.get('/api/auth/status').json()['account']['username'], 'owner')

    def test_remove_member_cleans_all_connections_and_preserves_other_workspaces(self):
        owner, owner_media = self.bootstrap()
        bob = self.bob(owner)
        aid = bob.headers['X-MixerBee-Account']
        member_ids = []
        for server in ('server-a', 'server-b'):
            # Same media user as the owner: cleanup must use connection ownership.
            res = self.save_http(bob, user='alice', server=server)
            self.assertEqual(res.status_code, 200, res.text)
            member_ids.append(res.json()['connection_id'])
        manager = scheduler.Scheduler()
        all_ids = [owner_media.connection.id] + member_ids
        jobs, runs, media_clients = {}, {}, {}
        for cid in all_ids:
            media_clients[cid] = connections.get_media_client(cid)
            preset_manager.save_preset('Evening', [], cid)
            with database.get_db_connection() as conn:
                conn.execute('INSERT INTO connection_recipes (id,connection_id,name,block_json) VALUES (?,?,?,?)',
                             (cid, cid, 'Recipe', '{}'))
                conn.commit()
            jobs[cid] = manager.add_schedule({
                'connection_id': cid, 'user_id': 'alice', 'playlist_name': 'Evening',
                'job_type': 'builder', 'preset_name': 'Evening',
                'schedule_details': {'frequency': 'interval', 'interval_minutes': 30}})
            manager.scheduler.add_job(lambda: None, 'date', id=f'run_{jobs[cid]}')
            runs[cid] = build_history.record_build_start(cid, 'playlist', 'alice')
            build_history.record_build_finish(runs[cid], 'playlist', 'ok', rows=[{'Id': 'movie', 'Type': 'Movie'}])
            cache.CACHE[cid] = {'test': True}
            with media_scope(media_clients[cid]):
                vector_store.get_media_collection()
            self.addCleanup(vector_store.delete_connection_collection, cid)

        worker = enrichment_manager._get_worker(member_ids[0])
        worker.status = 'running'
        self.addCleanup(enrichment_manager._workers.pop, member_ids[0], None)
        with database.get_db_connection() as conn:
            conn.execute("UPDATE media_connections SET api_key_hash=?, webhook_secret='webhook-secret',"
                         ' webhook_setup_requested_at=1 WHERE id=?',
                         (accounts.token_hash('external-secret'), member_ids[0]))
            conn.execute("INSERT OR REPLACE INTO settings (key,value) VALUES ('active_connection_id',?)", (member_ids[0],))
            conn.commit()

        with patch('scheduler.scheduler_manager', manager):
            res = owner.delete(f'/api/accounts/{aid}?delete_data=true')
        self.assertEqual(res.status_code, 200, res.text)
        self.assertTrue(worker.stop_requested.is_set())
        for cid in member_ids:
            self.assertNotIn(jobs[cid], manager.schedules)
            self.assertIsNone(manager.scheduler.get_job(jobs[cid]))
            self.assertIsNone(manager.scheduler.get_job(f'run_{jobs[cid]}'))
            self.assertNotIn(cid, connections._clients)
            self.assertNotIn(cid, cache.CACHE)
            self.assertNotIn(f'mixerbee_{cid}', vector_store._collections)
            self.assertNotIn(f'mixerbee_{cid}', [c.name for c in vector_store.chroma_client.list_collections()])
            # A stale background worker must not recreate local data after removal.
            with media_scope(media_clients[cid]), self.assertRaises(ValueError):
                vector_store.get_media_collection()
            build_history.record_build_start(cid, 'playlist', 'alice')
            build_history.record_build_finish(runs[cid], 'late', 'ok', rows=[{'Id': 'late'}])

        with database.get_db_connection() as conn:
            for table in ('media_connections', 'connection_presets', 'connection_recipes', 'schedules', 'build_runs', 'build_run_items'):
                self.assertEqual(conn.execute(f'SELECT COUNT(*) FROM {table}').fetchone()[0], 1, table)
            self.assertEqual(conn.execute('SELECT COUNT(*) FROM account_sessions WHERE account_id=?', (aid,)).fetchone()[0], 0)
            self.assertIsNone(conn.execute("SELECT value FROM settings WHERE key='active_connection_id'").fetchone())
            self.assertEqual(conn.execute('PRAGMA foreign_key_check').fetchall(), [])
        self.assertIn(owner_media.connection.id, cache.CACHE)
        self.assertIsNotNone(manager.scheduler.get_job(jobs[owner_media.connection.id]))
        self.assertEqual(owner.get('/api/admin/webhook-requests').json()['requests'], [])
        self.assertEqual(bob.get('/api/settings').status_code, 401)
        self.assertEqual(TestClient(web.app).post('/api/external/build_preset',
            headers={'X-MixerBee-Key': 'external-secret'}, json={}).status_code, 401)
        self.assertEqual(TestClient(web.app).post(f'/api/webhook/{member_ids[0]}',
            params={'token': 'webhook-secret'}, json={'Event': 'item.added'}).status_code, 401)

    def test_cache_refresh_does_not_restore_a_removed_connection(self):
        _, media = self.bootstrap()
        with patch.multiple(cache, tv=Mock(), movies=Mock(), music=Mock(), studios=Mock()):
            # Removal lands after the refresh started, before it publishes data.
            cache.studios.aggregate_all_studios.side_effect = lambda *args: cache.forget_connection(media.connection.id)
            cache.refresh_cache(media)
        self.assertNotIn(media.connection.id, cache.CACHE)

    def test_remove_member_rolls_back_if_sql_cleanup_fails(self):
        owner, _ = self.bootstrap()
        bob = self.bob(owner)
        cid = self.save_http(bob).json()['connection_id']
        aid = bob.headers['X-MixerBee-Account']
        preset_manager.save_preset('Keep me', [], cid)
        original = connections.delete_connection_data

        def fail_after_cleanup(conn, connection_id):
            original(conn, connection_id)
            raise sqlite3.IntegrityError('Simulated cleanup failure')

        with patch('connections.delete_connection_data', side_effect=fail_after_cleanup), \
                patch('connections.cleanup_deleted_connection') as runtime_cleanup:
            with self.assertRaises(sqlite3.IntegrityError):
                accounts.remove_household_member(aid, actor_id=owner.headers['X-MixerBee-Account'], delete_data=True)
            runtime_cleanup.assert_not_called()
        self.assertEqual(preset_manager.get_all_presets(cid), {'Keep me': []})
        self.assertIsNotNone(accounts.authenticate('bob', 'bob-password'))
        self.assertEqual(bob.get('/api/connections').status_code, 200)

    def test_remove_single_connection_also_cleans_recipes_and_history(self):
        owner, media = self.bootstrap()
        cid = media.connection.id
        run = build_history.record_build_start(cid, 'playlist', 'alice')
        with database.get_db_connection() as conn:
            conn.execute("INSERT INTO connection_recipes (id,connection_id,name,block_json) VALUES ('recipe',?,'Recipe','{}')", (cid,))
            conn.commit()
        res = owner.delete(f'/api/connections/{cid}?delete_data=true')
        self.assertEqual(res.status_code, 200, res.text)
        self.assertIsNone(res.json()['connection_id'])
        self.assertIsNone(build_history.get_build_run_detail(run, cid))
        self.assertEqual(owner.get('/api/auth/status').json()['account']['username'], 'owner')

    def test_anonymous_gate_csrf_and_stale_account(self):
        owner, media = self.bootstrap()
        anon = TestClient(web.app)
        for path in ('/api/settings', '/api/config_status', '/api/connections', '/api/presets', '/api/schedules'):
            self.assertEqual(anon.get(path).status_code, 401, path)
        self.assertEqual(anon.get('/api/status').status_code, 200)
        self.assertEqual(anon.post('/api/auth/login', json={'username': 'owner', 'password': 'owner-password'}).status_code, 403)
        self.assertEqual(owner.post('/api/auth/logout', headers={'X-MixerBee-CSRF': ''}).status_code, 409)
        self.assertEqual(owner.post('/api/auth/logout', headers={'Origin': 'http://other'}).status_code, 403)
        self.assertEqual(owner.get('/api/settings', headers={'X-MixerBee-Account': 'different'}).status_code, 409)
        self.assertEqual(owner.get('/api/settings').headers['cache-control'], 'no-store')

    def test_two_accounts_same_media_identity_stay_separate(self):
        owner, a = self.bootstrap()
        bob = self.bob(owner)
        self.assertEqual(bob.get('/api/connections').json(), [])
        self.assertFalse(bob.get('/api/config_status').json()['is_configured'])
        r = self.save_http(bob, user='alice')
        self.assertEqual(r.status_code, 200, r.text)
        b_id = r.json()['connection_id']
        bob.headers['X-MixerBee-Connection'] = b_id
        self.assertNotEqual(a.connection.id, b_id)
        preset_manager.save_preset('Evening', [{'type': 'tv'}], a.connection.id)
        preset_manager.save_preset('Evening', [{'type': 'movie'}], b_id)
        self.assertEqual(owner.get('/api/presets').json()['Evening'][0]['type'], 'tv')
        self.assertEqual(bob.get('/api/presets').json()['Evening'][0]['type'], 'movie')
        for path in ('/api/settings', '/api/presets', '/api/default_user', '/api/schedules'):
            self.assertEqual(bob.get(path, headers={'X-MixerBee-Connection': a.connection.id}).status_code, 404)
        self.assertEqual(bob.post(f'/api/connections/{a.connection.id}/select').status_code, 404)
        self.assertEqual(self.save_http(bob, connection_id=a.connection.id).status_code, 404)
        # Owner privileges manage account creation, not another person's workspace.
        self.assertEqual(owner.get('/api/settings', headers={'X-MixerBee-Connection': b_id}).status_code, 404)
        self.assertEqual(owner.get('/api/connections').json()[0]['id'], a.connection.id)

    def test_session_selection_and_pinned_tabs_do_not_redirect_work(self):
        owner, a = self.bootstrap()
        r = self.save_http(owner, user='other', server='other-server')
        b_id = r.json()['connection_id']
        self.assertNotEqual(a.connection.id, b_id)
        self.assertEqual(owner.get('/api/default_user').json()['connection_id'], a.connection.id)
        owner.headers['X-MixerBee-Connection'] = ''
        self.assertEqual(owner.get('/api/default_user').json()['connection_id'], b_id)
        second = TestClient(web.app)
        r = second.post('/api/auth/login', headers={'X-MixerBee-Request': '1'}, json={'username': 'owner', 'password': 'owner-password'})
        self.pin(second, r.json())
        self.assertEqual(second.get('/api/default_user').json()['connection_id'], a.connection.id)

    def test_schedules_keep_working_after_logout(self):
        owner, media = self.bootstrap()
        preset_manager.save_preset('Evening', [], media.connection.id)
        bob = self.bob(owner)
        manager = scheduler.Scheduler()
        job = {'connection_id': media.connection.id, 'user_id': 'alice', 'playlist_name': 'Evening',
               'job_type': 'builder', 'preset_name': 'Evening',
               'schedule_details': {'frequency': 'interval', 'interval_minutes': 30}}
        jid = manager.add_schedule(job)
        with patch('routers.scheduler.scheduler.scheduler_manager', manager):
            self.assertEqual(owner.get('/api/schedules').json()[0]['id'], jid)
            r = self.save_http(bob)
            bob.headers['X-MixerBee-Connection'] = r.json()['connection_id']
            self.assertEqual(bob.get('/api/schedules').json(), [])
            for method, suffix in (('delete', ''), ('post', '/run')):
                self.assertEqual(getattr(bob, method)(f'/api/schedules/{jid}{suffix}').status_code, 404)
        self.assertEqual(owner.post('/api/auth/logout').status_code, 200)
        self.assertEqual(owner.get('/api/settings').status_code, 401)
        with patch('scheduler.core.create_mixed_playlist', return_value={'status': 'ok'}) as build:
            result = scheduler.run_playlist_job(connection_id=media.connection.id, user_id='alice', playlist_name='Evening', preset_name='Evening')
            self.assertEqual(result['status'], 'ok')
            self.assertEqual(build.call_args.kwargs['media'].connection.id, media.connection.id)

    def test_webhooks_capture_connection_and_require_its_secret(self):
        owner, a = self.bootstrap()
        bob = self.bob(owner)
        r = self.save_http(bob)
        b_id = r.json()['connection_id']
        bob.headers['X-MixerBee-Connection'] = b_id
        secret = owner.post('/api/settings/webhook_secret/regenerate').json()['webhook_secret']
        b_secret = bob.post('/api/settings/webhook_secret/regenerate').json()['webhook_secret']
        anon = TestClient(web.app)
        with patch('routers.webhooks.scheduler_manager.scheduler.add_job') as add:
            endpoint = f'/api/webhook/{a.connection.id}'
            self.assertEqual(anon.post(endpoint, json={'Event': 'item.added'}).status_code, 401)
            self.assertEqual(anon.post(endpoint, params={'token': b_secret}, json={'Event': 'item.added'}).status_code, 401)
            self.assertEqual(anon.post(endpoint, params={'token': secret}, json={'Event': 'item.added'}).json()['status'], 'accepted')
            self.assertEqual(add.call_args.kwargs['args'][2], a.connection.id)
            owner.post('/api/settings/webhook_secret/clear')
            self.assertEqual(anon.post(endpoint, params={'token': secret}, json={'Event': 'item.added'}).status_code, 401)
        self.assertEqual(anon.post('/api/webhook').status_code, 410)

    def test_household_webhook_setup_request_and_verification_workflow(self):
        owner, _ = self.bootstrap()
        bob = self.bob(owner)
        r = self.save_http(bob, user='bob-media')
        connection_id = r.json()['connection_id']
        bob.headers['X-MixerBee-Connection'] = connection_id

        generated = bob.post('/api/settings/webhook_secret/regenerate').json()
        secret = generated['webhook_secret']
        self.assertEqual(generated['webhook_status'], 'setup_requested')
        self.assertEqual(bob.get('/api/settings').json()['webhook_status'], 'setup_requested')
        self.assertEqual(bob.get('/api/admin/webhook-requests').status_code, 403)

        invalid_base = owner.post('/api/admin/settings/webhook-base-url', json={'url': 'https://user:pass@example.test'})
        self.assertEqual(invalid_base.status_code, 400)
        self.assertEqual(bob.post('/api/admin/settings/webhook-base-url', json={'url': 'https://mixerbee.example.test'}).status_code, 403)
        self.assertEqual(owner.post('/api/admin/settings/webhook-base-url', json={
            'url': 'https://mixerbee.example.test/household'
        }).status_code, 200)

        inbox = owner.get('/api/admin/webhook-requests').json()
        self.assertEqual(len(inbox['requests']), 1)
        request = inbox['requests'][0]
        self.assertEqual(request['connection_id'], connection_id)
        self.assertEqual(request['mixerbee_username'], 'bob')
        self.assertEqual(request['media_username'], 'bob-media')
        self.assertTrue(request['webhook_url'].startswith(
            f'https://mixerbee.example.test/household/api/webhook/{connection_id}?token='))
        self.assertIn(secret, request['webhook_url'])

        acknowledged = owner.post(f'/api/admin/webhook-requests/{connection_id}/acknowledge')
        self.assertEqual(acknowledged.status_code, 200)
        self.assertEqual(bob.get('/api/settings').json()['webhook_status'], 'waiting_for_event')

        anonymous = TestClient(web.app)
        endpoint = f'/api/webhook/{connection_id}'
        self.assertEqual(anonymous.post(endpoint, params={'token': secret}, json={}).json()['status'], 'ignored')
        self.assertEqual(bob.get('/api/settings').json()['webhook_status'], 'waiting_for_event')
        with patch('routers.webhooks.scheduler_manager.scheduler.add_job'):
            result = anonymous.post(endpoint, params={'token': secret}, json={'Event': 'item.added'})
        self.assertEqual(result.json()['status'], 'accepted')
        settings = bob.get('/api/settings').json()
        self.assertEqual(settings['webhook_status'], 'connected')
        self.assertEqual(owner.get('/api/admin/webhook-requests').json()['requests'], [])

        rotated = bob.post('/api/settings/webhook_secret/regenerate').json()
        self.assertEqual(rotated['webhook_status'], 'setup_requested')
        self.assertEqual(len(owner.get('/api/admin/webhook-requests').json()['requests']), 1)
        bob.post('/api/settings/webhook_secret/clear')
        self.assertEqual(bob.get('/api/settings').json()['webhook_status'], 'disabled')
        self.assertEqual(owner.get('/api/admin/webhook-requests').json()['requests'], [])

    def test_external_key_limited_to_its_connection_and_external_routes(self):
        owner, a = self.bootstrap()
        key = 'external-test-secret'
        r = self.save_http(owner, user='alice', connection_id=a.connection.id, external_api_key=key)
        self.assertEqual(r.status_code, 200, r.text)
        anon = TestClient(web.app, headers={'X-MixerBee-Key': key})
        self.assertEqual(anon.get('/api/settings').status_code, 401)
        preset_manager.save_preset('Evening', [{'type': 'movie'}], a.connection.id)
        with patch('routers.builder.core.create_mixed_playlist', return_value={'status': 'ok'}) as build:
            r = anon.post('/api/external/build_preset', json={'preset_name': 'Evening', 'playlist_name': 'Test'},
                          headers={'X-MixerBee-Connection': 'some-other-connection', 'Origin': 'http://external-dashboard.local'})
            self.assertEqual(r.status_code, 200, r.text)
            self.assertEqual(build.call_args.kwargs['media'].connection.id, a.connection.id)
        self.assertTrue(owner.get('/api/settings').json()['external_api_key_set'])
        self.assertEqual(owner.get('/api/settings').json()['external_api_key'], key)
        self.save_http(owner, user='alice', connection_id=a.connection.id, clear_external_api_key=True)
        self.assertEqual(anon.post('/api/external/build_preset', json={'preset_name': 'Evening', 'playlist_name': 'Test'}).status_code, 401)

    def test_password_change_revokes_all_sessions_and_expiry(self):
        owner, _ = self.bootstrap()
        second = TestClient(web.app)
        r = second.post('/api/auth/login', headers={'X-MixerBee-Request': '1'}, json={'username': 'OWNER', 'password': 'owner-password'})
        self.pin(second, r.json())
        r = owner.post('/api/auth/password', json={'current_password': 'owner-password', 'new_password': 'new-password'})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(second.get('/api/settings').status_code, 401)
        self.assertIsNone(accounts.authenticate('owner', 'owner-password'))
        self.assertIsNotNone(accounts.authenticate('owner', 'new-password'))
        with database.get_db_connection() as conn:
            aid = conn.execute('SELECT id FROM accounts').fetchone()[0]
        token, _ = accounts.create_session(aid)
        with patch('accounts.time.time', return_value=time.time() + accounts.SESSION_SECONDS + 1):
            self.assertIsNone(accounts.read_session(token))

    def test_settings_no_longer_write_global_settings_or_change_identity(self):
        owner, a = self.bootstrap()
        with database.get_db_connection() as conn:
            before = [tuple(r) for r in conn.execute('SELECT * FROM settings')]
        # Configure AI deliberately first, through the endpoint that owns ai_settings.
        r = owner.post('/api/settings/ai', json={'ai_provider': 'ollama',
                                                'ollama_url': 'http://ollama.local:11434',
                                                'ollama_model': 'local-model'})
        self.assertEqual(r.status_code, 200, r.text)
        r = self.save_http(owner, user='alice', connection_id=a.connection.id, label='My Emby',
                           ai_provider='gemini', ollama_model='clobbered')
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(r.json()['connection_id'], a.connection.id)
        settings = owner.get('/api/settings').json()
        # A connection save leaves ai_settings alone: the stale AI fields it posted must
        # not overwrite the provider setup, which is how a saved key used to be erased.
        self.assertEqual(settings['ollama_model'], 'local-model')
        self.assertEqual(settings['ai_provider'], 'ollama')
        self.assertEqual(settings['label'], 'My Emby')
        with database.get_db_connection() as conn:
            self.assertEqual(before, [tuple(r) for r in conn.execute('SELECT * FROM settings')])
        self.assertEqual(self.save_http(owner, user='wrong', connection_id=a.connection.id).status_code, 400)
        self.assertEqual(connections.get_media_client(a.connection.id).user_id, 'alice')

    def test_ai_settings_endpoint(self):
        owner, a = self.bootstrap()
        with patch('routers.config.threading.Thread'):
            res = owner.post('/api/settings/ai', json={
                'ai_provider': 'gemini',
                'gemini_key': 'test-gemini-key',
                'ollama_url': 'http://localhost:11434',
                'ollama_model': 'llama3.1',
                'ollama_timeout': 90
            })
        self.assertEqual(res.status_code, 200, res.text)
        settings = owner.get('/api/settings').json()
        self.assertEqual(settings['ai_provider'], 'gemini')
        self.assertEqual(settings['gemini_key'], 'test-gemini-key')
        self.assertEqual(settings['ollama_timeout'], 90)

        # Invalid provider rejected
        bad_provider = owner.post('/api/settings/ai', json={'ai_provider': 'unsupported'})
        self.assertEqual(bad_provider.status_code, 400)

        # Invalid timeout rejected
        bad_timeout = owner.post('/api/settings/ai', json={'ai_provider': 'ollama', 'ollama_timeout': 5})
        self.assertEqual(bad_timeout.status_code, 400)

    def test_ai_settings_partial_update_preserves_stored_values(self):
        """A field the caller omits keeps its saved value.

        The AI hub modal can be opened straight from the header, before the saved
        settings have loaded into the store. A post shaped like that one must not
        blank the Gemini key and reset the Ollama configuration.
        """
        owner, a = self.bootstrap()
        with patch('routers.config.threading.Thread'):
            full = owner.post('/api/settings/ai', json={
                'ai_provider': 'gemini',
                'gemini_key': 'keep-me',
                'ollama_url': 'http://ollama.local:11434',
                'ollama_model': 'llama3.1',
                'ollama_timeout': 90,
                'starred_models': ['llama3.1']
            })
        self.assertEqual(full.status_code, 200, full.text)

        with patch('routers.config.threading.Thread'):
            partial = owner.post('/api/settings/ai', json={'ai_provider': 'ollama'})
        self.assertEqual(partial.status_code, 200, partial.text)

        settings = owner.get('/api/settings').json()
        self.assertEqual(settings['ai_provider'], 'ollama')
        self.assertEqual(settings['gemini_key'], 'keep-me')
        self.assertEqual(settings['ollama_url'], 'http://ollama.local:11434')
        self.assertEqual(settings['ollama_model'], 'llama3.1')
        self.assertEqual(settings['ollama_timeout'], 90)
        self.assertEqual(settings['starred_models'], ['llama3.1'])

        # An explicit empty string is still a deliberate clear (the "Remove key" button).
        with patch('routers.config.threading.Thread'):
            cleared = owner.post('/api/settings/ai', json={'gemini_key': ''})
        self.assertEqual(cleared.status_code, 200, cleared.text)
        self.assertEqual(owner.get('/api/settings').json()['gemini_key'], '')

    def test_concurrent_initial_setup_only_one_owner(self):
        def create(name):
            try:
                return accounts.create_account(name, 'test-password', initial_only=True)
            except PermissionError:
                return None
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(create, ('one', 'two')))
        self.assertEqual(sum(r is not None for r in results), 1)
        with database.get_db_connection() as conn:
            self.assertEqual(conn.execute('SELECT count(*) FROM accounts WHERE is_admin=1').fetchone()[0], 1)

    def test_external_api_key_endpoints(self):
        owner, media = self.bootstrap()
        # Generate random key
        r = owner.post('/api/settings/external_api_key/regenerate', json={'connection_id': media.connection.id})
        self.assertEqual(r.status_code, 200, r.text)
        key = r.json()['external_api_key']
        self.assertGreaterEqual(len(key), 16)

        # Save custom valid key
        custom = 'custom-secret-key-12345'
        r = owner.post('/api/settings/external_api_key/regenerate', json={'connection_id': media.connection.id, 'key': custom})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()['external_api_key'], custom)

        # Short key fails
        r = owner.post('/api/settings/external_api_key/regenerate', json={'connection_id': media.connection.id, 'key': 'short'})
        self.assertEqual(r.status_code, 400)

        # Clear key disables external access
        r = owner.post('/api/settings/external_api_key/clear', json={'connection_id': media.connection.id})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()['external_api_key'], '')

    def test_login_rate_limit_and_cookie_flags(self):
        owner, _ = self.bootstrap()
        anonymous = TestClient(web.app)
        accounts._attempts.clear()
        for i in range(10):
            r = anonymous.post('/api/auth/login', headers={'X-MixerBee-Request': '1'}, json={'username': 'none', 'password': 'bad-password'})
            self.assertEqual(r.status_code, 401)
        self.assertEqual(anonymous.post('/api/auth/login', headers={'X-MixerBee-Request': '1'}, json={'username': 'owner', 'password': 'owner-password'}).status_code, 429)
        accounts._attempts.clear()
        secure = TestClient(web.app, base_url='https://testserver')
        r = secure.post('/api/auth/login', headers={'X-MixerBee-Request': '1'}, json={'username': 'owner', 'password': 'owner-password'})
        cookie = r.headers['set-cookie']
        for flag in ('HttpOnly', 'SameSite=strict', 'Secure'):
            self.assertIn(flag, cookie)


if __name__ == '__main__':
    unittest.main()
