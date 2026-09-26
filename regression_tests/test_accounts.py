"""Offline HTTP isolation and migration checks for local MixerBee accounts."""
# Import the existing harness first: it isolates runtime paths before app imports.
import test_connections as connection_tests
import json
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
from app.media_client import MediaClient
from preset_manager import preset_manager


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
        r = self.save_http(owner, user='alice', connection_id=a.connection.id, label='My Emby', ai_provider='ollama', ollama_model='local-model')
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(r.json()['connection_id'], a.connection.id)
        settings = owner.get('/api/settings').json()
        self.assertEqual(settings['ollama_model'], 'local-model')
        self.assertEqual(settings['label'], 'My Emby')
        with database.get_db_connection() as conn:
            self.assertEqual(before, [tuple(r) for r in conn.execute('SELECT * FROM settings')])
        self.assertEqual(self.save_http(owner, user='wrong', connection_id=a.connection.id).status_code, 400)
        self.assertEqual(connections.get_media_client(a.connection.id).user_id, 'alice')

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
