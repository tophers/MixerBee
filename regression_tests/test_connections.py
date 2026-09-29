"""Offline connection/migration regressions. Never opens the development database."""
import os
import tempfile

_storage = tempfile.TemporaryDirectory(prefix='mixerbee-connection-tests-')
os.environ['MIXERBEE_CONFIG_DIR'] = _storage.name
os.environ['ANONYMIZED_TELEMETRY'] = 'False'

import json
from pathlib import Path
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import Mock, patch

import requests
import database
import connections
import app_state
from app.media_client import Connection, MediaClient, current_media, media_scope, ConnectionUnavailable
from app import items, builder, cache
from app.ai import vector_store, tools
from preset_manager import preset_manager
import scheduler
from routers import scheduler as schedule_routes, presets as preset_routes, webhooks, config, builder as builder_routes
from fastapi import HTTPException
import models


def response(data=None, status=200):
    r = Mock()
    r.status_code = status
    r.ok = status < 400
    r.json.return_value = data or {}
    if status >= 400:
        r.raise_for_status.side_effect = requests.HTTPError(response=r)
    return r


class ConnectionTests(unittest.TestCase):
    def setUp(self):
        self.db_dir = tempfile.TemporaryDirectory(dir=_storage.name)
        database.DB_PATH = Path(self.db_dir.name) / 'mixerbee.db'
        database.init_db()
        connections._clients.clear()
        cache.CACHE.clear()
        vector_store._collections.clear()
        self.addCleanup(vector_store._collections.clear)
        # Fail any accidental network call; individual tests provide fake transports.
        self.network = patch('requests.sessions.Session.request', side_effect=AssertionError('Unexpected network access'))
        self.network.start()
        self.addCleanup(self.network.stop)
        self.addCleanup(self.db_dir.cleanup)

    def save(self, user='alice', server='server-a', url='http://a', ai=None):
        return connections.save_authenticated_connection(url, 'emby', user, 'test-password',
            {'User': {'Id': user, 'Policy': {'IsAdministrator': True}}, 'ServerId': server,
             'AccessToken': f'{server}-{user}-token'}, ai or {})

    def auth(self, media):
        return {'media': media, 'login_uid': media.user_id, 'connection_id': media.connection.id}

    def test_migration_is_once_only_and_preserves_unmatched_jobs(self):
        with database.get_db_connection() as conn:
            conn.execute("INSERT INTO presets (name,data) VALUES ('Evening', '[]')")
            for uid in ('alice', 'bob'):
                conn.execute('INSERT INTO schedules (id,playlist_name,user_id,job_type,crontab) VALUES (?,?,?,?,?)',
                             (uid, 'Evening', uid, 'builder', '0 12 * * *'))
            conn.commit()
        alice = self.save()
        bob = self.save('bob')
        database.init_db()
        self.save('bob')
        self.assertEqual(preset_manager.get_all_presets(alice.connection.id), {'Evening': []})
        self.assertEqual(preset_manager.get_all_presets(bob.connection.id), {})
        with database.get_db_connection() as conn:
            rows = {r['id']: r['connection_id'] for r in conn.execute('SELECT id,connection_id FROM schedules')}
            self.assertEqual(conn.execute('SELECT COUNT(*) FROM presets').fetchone()[0], 1)
        self.assertEqual(rows['alice'], alice.connection.id)
        self.assertIsNone(rows['bob'])

    def test_presets_same_name_are_independent(self):
        a, b = self.save(), self.save('bob')
        preset_manager.save_preset('Evening', [{'type': 'movie'}], a.connection.id)
        preset_manager.save_preset('Evening', [{'type': 'tv'}], b.connection.id)
        preset_manager.delete_preset('Evening', b.connection.id)
        self.assertEqual(preset_manager.get_all_presets(a.connection.id)['Evening'][0]['type'], 'movie')
        self.assertEqual(preset_manager.get_all_presets(b.connection.id), {})

    def test_schedule_preset_ids_survive_updates_and_name_changes(self):
        media = self.save()
        preset_id = preset_manager.save_preset('Evening', [{'type': 'movie', 'version': 1}], media.connection.id)
        self.assertEqual(
            preset_manager.save_preset('Evening', [{'type': 'movie', 'version': 2}], media.connection.id),
            preset_id
        )
        submitted = schedule_routes.bind_schedule_preset(
            {'job_type': 'builder', 'preset_name': 'Evening'}, media.connection.id
        )
        self.assertEqual(submitted['preset_id'], preset_id)
        other = self.save('bob')
        with self.assertRaises(ValueError):
            schedule_routes.bind_schedule_preset(
                {'job_type': 'builder', 'preset_id': preset_id}, other.connection.id
            )
        manager = scheduler.Scheduler()
        job = {'connection_id': media.connection.id, 'user_id': 'alice', 'playlist_name': 'Evening Mix',
               'job_type': 'builder', 'preset_id': preset_id, 'preset_name': 'Evening',
               'schedule_details': {'frequency': 'interval', 'interval_minutes': 30}}
        schedule_id = manager.add_schedule(job)
        with database.get_db_connection() as conn:
            conn.execute("UPDATE connection_presets SET name='Renamed' WHERE id=?", (preset_id,))
            conn.commit()
        loaded = manager._load_schedules()[schedule_id]
        self.assertEqual(loaded['preset_id'], preset_id)
        self.assertEqual(loaded['preset_name'], 'Renamed')
        with patch('scheduler.core.create_mixed_playlist', return_value={'status': 'ok'}) as build:
            self.assertEqual(scheduler.run_playlist_job(**loaded)['status'], 'ok')
            self.assertEqual(build.call_args.kwargs['blocks'][0]['version'], 2)
        with patch.object(schedule_routes.scheduler, 'scheduler_manager', manager):
            with self.assertRaises(HTTPException) as error:
                preset_routes.api_delete_preset('Renamed', self.auth(media))
        self.assertEqual(error.exception.status_code, 400)

    def test_legacy_schedule_preset_name_is_backfilled_to_id(self):
        media = self.save()
        preset_id = preset_manager.save_preset('Evening', [{'type': 'movie'}], media.connection.id)
        with database.get_db_connection() as conn:
            conn.execute('''INSERT INTO schedules
                (id, playlist_name, user_id, job_type, crontab, config_data, connection_id)
                VALUES ('legacy', 'Evening Mix', 'alice', 'builder', '0 12 * * *', ?, ?)''',
                (json.dumps({'preset_name': 'Evening'}), media.connection.id))
            connections.backfill_schedule_preset_ids(conn, media.connection.id)
            conn.commit()
            bound_id = conn.execute("SELECT preset_id FROM schedules WHERE id='legacy'").fetchone()['preset_id']
        self.assertEqual(bound_id, preset_id)

    def test_connections_survive_active_change_and_restart(self):
        a = self.save()
        b = self.save('bob', 'server-b', 'http://b')
        connections._clients.clear()
        self.assertEqual(connections.active_connection_id(), b.connection.id)
        self.assertEqual(connections.get_media_client(a.connection.id).connection.base_url, 'http://a')
        self.assertEqual(connections.get_media_client(a.connection.id).user_id, 'alice')

    def test_concurrent_requests_do_not_mix_hosts_or_tokens(self):
        barrier = threading.Barrier(2)
        observed = []
        def run(cid, host, user, server_type):
            transport = Mock()
            def request(method, url, **kwargs):
                barrier.wait(timeout=5)
                observed.append((url, kwargs['headers'], kwargs['params']))
                return response({'Items': []})
            transport.request.side_effect = request
            media = MediaClient(Connection(cid, host, server_type, user, 'pw', user), f'{user}-token', lambda: transport)
            items.get_playlists(user, media)
        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = [pool.submit(run, 'a', 'http://a', 'alice', 'emby'),
                       pool.submit(run, 'b', 'http://b', 'bob', 'jellyfin')]
            for f in futures:
                f.result()
        for url, headers, params in observed:
            user = 'alice' if url.startswith('http://a/') else 'bob'
            self.assertEqual(headers['X-Emby-Token'], f'{user}-token')
            self.assertIn(f'/Users/{user}/', url)
            self.assertIn('X-Emby-Authorization' if user == 'alice' else 'Authorization', headers)

    def test_rejects_foreign_users_and_absolute_urls(self):
        media = self.save()
        for path, kwargs in [('/Users/bob/Items', {}), ('/Items', {'params': {'UserId': 'bob'}})]:
            with self.assertRaises(PermissionError):
                media.get(path, **kwargs)
        with self.assertRaises(ValueError):
            media.get('http://elsewhere/Items')

    def test_search_injects_own_user_and_does_not_mutate_params(self):
        transport = Mock()
        transport.request.return_value = response()
        media = MediaClient(Connection('a', 'http://a', 'emby', 'alice', 'pw', 'alice'), 'token', lambda: transport)
        params = {'SearchTerm': 'Show'}
        media.get('/Items', params=params)
        self.assertEqual(transport.request.call_args.kwargs['params']['UserId'], 'alice')
        self.assertNotIn('UserId', params)

    def test_expired_token_reauthenticates_only_its_connection(self):
        transport = Mock()
        transport.get.return_value = response(status=401)
        transport.post.return_value = response({'User': {'Id': 'alice'}, 'ServerId': 'a', 'AccessToken': 'new'})
        transport.request.return_value = response()
        media = MediaClient(Connection('a', 'http://a', 'emby', 'alice', 'pw', 'alice', 'a'), 'old', lambda: transport)
        media._last_check = 0
        media.get('/Items')
        self.assertEqual(transport.get.call_args.args[0], 'http://a/Users/alice')
        self.assertEqual(transport.post.call_args.kwargs['json']['Username'], 'alice')
        self.assertEqual(transport.request.call_args.kwargs['headers']['X-Emby-Token'], 'new')

    def test_auth_refuses_changed_server_identity(self):
        transport = Mock()
        transport.post.return_value = response({'User': {'Id': 'alice'}, 'ServerId': 'wrong', 'AccessToken': 'new'})
        media = MediaClient(Connection('a', 'http://a', 'emby', 'alice', 'pw', 'alice', 'expected'), session_factory=lambda: transport)
        with self.assertRaises(ConnectionUnavailable):
            media.ensure_authenticated()

    def test_schedule_uses_saved_connection_after_active_change(self):
        a, b = self.save(), self.save('bob', 'b', 'http://b')
        preset_manager.save_preset('Evening', [{'type': 'movie'}], a.connection.id)
        job = {'connection_id': a.connection.id, 'user_id': 'alice', 'playlist_name': 'Evening', 'preset_name': 'Evening'}
        with patch('scheduler.core.create_mixed_playlist', return_value={'status': 'ok'}) as build:
            self.assertEqual(scheduler.run_playlist_job(**job)['status'], 'ok')
            self.assertEqual(build.call_args.kwargs['media'].connection.id, a.connection.id)
            self.assertEqual(build.call_args.kwargs['blocks'], [{'type': 'movie'}])
        self.assertEqual(connections.active_connection_id(), b.connection.id)

    def test_scheduler_persists_connection_and_scopes_routes(self):
        a, b = self.save(), self.save('bob')
        manager = scheduler.Scheduler()
        job = {'connection_id': a.connection.id, 'user_id': 'alice', 'playlist_name': 'Evening',
               'job_type': 'builder', 'schedule_details': {'frequency': 'interval', 'interval_minutes': 30}}
        jid = manager.add_schedule(job)
        self.assertEqual(manager._load_schedules()[jid]['connection_id'], a.connection.id)
        with patch.object(schedule_routes.scheduler, 'scheduler_manager', manager), patch.object(app_state, 'is_configured', True):
            for action in (schedule_routes.api_delete_schedule, schedule_routes.api_run_schedule_now):
                with self.assertRaises(HTTPException) as error:
                    action(jid, self.auth(b))
                self.assertEqual(error.exception.status_code, 404)
            self.assertIn(jid, manager.schedules)
            self.assertEqual(json.loads(schedule_routes.api_get_schedules(self.auth(b)).body), [])

    def test_webhook_routes_only_captured_connection(self):
        a, b = self.save(), self.save('alice', 'b', 'http://b')
        jobs = [{'id': 'a', 'connection_id': a.connection.id, 'user_id': 'alice'},
                {'id': 'b', 'connection_id': b.connection.id, 'user_id': 'alice'}]
        with patch.object(webhooks.scheduler_manager, 'get_all_schedules', return_value=jobs), \
             patch.object(webhooks.scheduler_manager, 'run_schedule_now') as run:
            webhooks.trigger_relevant_schedules(connection_id=a.connection.id)
            run.assert_called_once_with('a')

    def test_cache_and_ai_tools_use_bound_connection_even_in_worker_thread(self):
        a, b = self.save(), self.save('bob')
        cache.CACHE[a.connection.id] = {'movieGenreData': [{'Name': 'Alice genre'}]}
        cache.CACHE[b.connection.id] = {'movieGenreData': [{'Name': 'Bob genre'}]}
        with media_scope(a):
            bound = {tool.__name__: tool for tool in tools.tools_for_connection()}
        with media_scope(b), ThreadPoolExecutor(max_workers=1) as pool:
            self.assertEqual(pool.submit(bound['get_valid_movie_genres']).result(), ['Alice genre'])
            self.assertEqual(tools.get_valid_movie_genres(), ['Bob genre'])
        with self.assertRaises(LookupError):
            current_media()

    def test_vector_collections_are_separate_and_reset_only_one(self):
        a, b = self.save(), self.save('bob')
        vector_store._collections.clear()
        fake = Mock()
        fake.get_or_create_collection.side_effect = lambda **kw: kw['name']
        with patch.object(vector_store, 'chroma_client', fake):
            with media_scope(a):
                self.assertEqual(vector_store.get_media_collection(), 'mixerbee_' + a.connection.id)
            with media_scope(b):
                self.assertEqual(vector_store.get_media_collection(), 'mixerbee_' + b.connection.id)
            vector_store.reset_media_collection(False, media=a)
            fake.delete_collection.assert_called_once_with(name='mixerbee_' + a.connection.id)
            self.assertIn('mixerbee_' + b.connection.id, vector_store._collections)

    def test_movie_preview_route_passes_explicit_client(self):
        a = self.save()
        req = models.BuilderPreviewRequest(user_id='alice', blocks=[{'type': 'movie'}])
        with patch('app.builder.find_movies', return_value=[{'Id': 'one', 'Name': 'Movie', 'Type': 'Movie'}]) as find:
            result = builder_routes.api_builder_preview(req, self.auth(a))
            self.assertEqual(result['data'][0]['Id'], 'one')
            self.assertIs(find.call_args.kwargs['media'], a)

    def test_http_playlist_lifecycle_uses_active_connection(self):
        from fastapi.testclient import TestClient
        from urllib.parse import urlsplit
        import web
        media = self.save()
        state = {"exists": False, "ids": []}
        transport = Mock()
        def dispatch(method, url, **kwargs):
            self.assertTrue(url.startswith('http://a/'))
            self.assertEqual(kwargs['headers']['X-Emby-Token'], 'server-a-alice-token')
            path = urlsplit(url).path
            params = kwargs.get('params', {})
            if method == 'GET' and path == '/Users/alice/Items':
                if params.get('IncludeItemTypes') == 'Playlist':
                    return response({'Items': [{'Id': 'playlist', 'Name': 'Test'}] if state['exists'] else []})
                if params.get('Ids') == 'playlist':
                    return response({'Items': [{'Id': 'playlist', 'Name': 'Test', 'Type': 'Playlist'}]})
            if method == 'POST' and path == '/Playlists':
                state.update(exists=True, ids=params['Ids'].split(','))
                return response({'Id': 'playlist'})
            if path == '/Playlists/playlist/Items':
                if method == 'GET':
                    return response({'Items': [{'Id': mid, 'PlaylistItemId': f'e-{i}'} for i, mid in enumerate(state['ids'])]})
                if method == 'DELETE':
                    state['ids'] = []
                    return response()
                if method == 'POST':
                    state['ids'] += params['Ids'].split(',')
                    return response()
            if method == 'DELETE' and path == '/Items/playlist':
                state.update(exists=False, ids=[])
                return response()
            raise AssertionError((method, path, params))
        transport.request.side_effect = dispatch
        media._session_factory = lambda: transport
        with patch.object(app_state, 'is_configured', True):
            client = TestClient(web.app)  # No lifespan: don't start schedules or real indexing.
            import accounts
            accounts._attempts.clear()
            login = client.post('/api/auth/setup', headers={'X-MixerBee-Request': '1'}, json={
                'username': 'owner', 'password': 'test-password'})
            self.assertEqual(login.status_code, 200, login.text)
            client.headers['X-MixerBee-CSRF'] = login.json()['csrf_token']
            result = client.post('/api/create_mixed_playlist' , json={
                'user_id': 'alice', 'playlist_name': 'Test', 'item_ids': ['one', 'two']})
            self.assertEqual(result.status_code, 200, result.text)
            self.assertEqual(state['ids'], ['one', 'two'])
            self.assertIn('http://a/', result.json()['newItemUrl'])
            result = client.post('/api/items/playlist/reorder', json={'user_id': 'alice', 'item_ids': ['two', 'one']})
            self.assertEqual(result.status_code, 200, result.text)
            self.assertEqual(state['ids'], ['two', 'one'])
            result = client.post('/api/delete_item', json={'user_id': 'bob', 'item_id': 'playlist'})
            self.assertEqual(result.status_code, 403, result.text)
            self.assertTrue(state['exists'])
            result = client.post('/api/delete_item', json={'user_id': 'alice', 'item_id': 'playlist'})
            self.assertEqual(result.status_code, 200, result.text)
            self.assertFalse(state['exists'])

    def test_settings_test_authenticates_candidate_not_saved_server(self):
        self.save()
        req = models.SettingsRequest(server_type='jellyfin', emby_url='http://candidate', emby_user='bob', emby_pass='pw')
        fake = Mock()
        fake.post.return_value = response({'User': {'Id': 'bob'}, 'AccessToken': 'candidate-token'})
        with patch.object(MediaClient, '_new_session', return_value=fake):
            self.assertEqual(config.api_test_settings(req)['status'], 'ok')
        self.assertEqual(fake.post.call_args.args[0], 'http://candidate/Users/AuthenticateByName')
        self.assertEqual(connections.active_media_client().user_id, 'alice')

    def test_ai_provider_is_loaded_from_job_connection(self):
        from app.ai import orchestrator
        # A configured Ollama setup needs both a URL and a model: a bare provider name
        # is the ambiguous default state that no longer counts as configured.
        a = self.save(ai={'AI_PROVIDER': 'ollama', 'OLLAMA_URL': 'http://ollama.local:11434',
                          'OLLAMA_MODEL': 'alice-model'})
        self.save('bob', ai={'AI_PROVIDER': 'gemini', 'GEMINI_API_KEY': 'bob-key'})
        def generate(prompt, tweaks):
            self.assertEqual(current_media().connection.ai_settings['OLLAMA_MODEL'], 'alice-model')
            return [], 'alice-model', []
        with patch.object(orchestrator, '_generate_with_ollama', side_effect=generate), \
             patch.object(orchestrator, '_generate_with_gemini', side_effect=AssertionError('Wrong provider')):
            self.assertEqual(orchestrator.generate_smart_blocks('test', media=a)[1], 'alice-model')

    def test_domain_tv_music_and_curated_dispatch_preserves_connection(self):
        media = self.save()
        blocks = [
            {'type': 'tv', 'shows': [{'id': 'show', 'season': 1, 'episode': 1}], 'count': 1},
            {'type': 'music', 'music': {'mode': 'album', 'albumId': 'album'}},
            {'type': 'curated', 'movies': [{'Id': 'movie'}]},
        ]
        with patch('app.builder.episodes', return_value=[{'Id': 'ep'}]) as episodes, \
             patch('app.builder.get_songs_by_album', return_value=[{'Id': 'song'}]) as songs, \
             patch('app.builder.find_movies', return_value=[{'Id': 'movie'}]) as movies:
            result = builder.generate_items_from_blocks('alice', blocks, media, [])
        self.assertEqual([item['Id'] for item in result], ['ep', 'song', 'movie'])
        self.assertIs(episodes.call_args.args[4], media)
        self.assertIs(songs.call_args.args[1], media)
        self.assertIs(movies.call_args.kwargs['media'], media)

    def test_startup_saves_authenticated_connection_without_admin_endpoint(self):
        import app
        transport = Mock()
        transport.post.return_value = response({'User': {'Id': 'alice'}, 'ServerId': 'server-a', 'AccessToken': 'token'})
        with patch.object(app_state, 'sync_env_to_db'), patch.object(app_state, 'load_settings_from_db'), \
             patch.multiple(app, EMBY_URL='http://a', EMBY_USER='alice', EMBY_PASS='pw'), \
             patch.object(app_state, 'is_configured', False), \
             patch.object(MediaClient, '_new_session', return_value=transport):
            self.assertTrue(app_state.load_and_authenticate())
            self.assertEqual(connections.active_media_client().user_id, 'alice')
        transport.get.assert_not_called()
        transport.request.assert_not_called()

    def test_echo_resolves_seed_search_inside_explicit_connection(self):
        media = self.save()
        def search(**kwargs):
            self.assertIs(current_media(), media)
            return [{'Id': 'movie', 'Type': 'Movie'}]
        block = {'type': 'mirror', 'filters': {'seeds_positive': [{'Id': 'seed'}]}, 'limit': 1}
        with patch.object(vector_store, 'search_by_composite_similarity', side_effect=search), \
             patch('app.builder.find_movies', return_value=[{'Id': 'movie'}]):
            self.assertEqual(builder.generate_items_from_blocks('alice', [block], media, []), [{'Id': 'movie'}])
        with self.assertRaises(LookupError):
            current_media()

    def test_random_block_without_music_or_tv(self):
        media = self.save()
        with patch.object(builder_routes, 'get_library_data', return_value={'movieGenreData': [{'Name': 'Sci-Fi'}], 'libraryData': [{'Id': '1'}]}):
            block = builder_routes.api_get_random_block(self.auth(media))
            self.assertEqual(block.get('type'), 'movie')

    def test_similarity_functions_bind_media(self):
        media = self.save()
        mock_col = Mock()
        mock_col.get.return_value = {'ids': ['a'], 'embeddings': [[0.1, 0.2]], 'metadatas': [{'type': 'Movie'}]}
        mock_col.query.return_value = {'ids': [['b']], 'distances': [[0.1]], 'metadatas': [[{'name': 'Match', 'type': 'Movie'}]]}
        def fake_get_col():
            self.assertIs(current_media(), media)
            return mock_col
        with patch.object(vector_store, 'get_media_collection', side_effect=fake_get_col):
            results = vector_store.search_by_composite_similarity(['a'], [], media=media)
            self.assertEqual(len(results), 1)
            self.assertEqual(results[0]['Id'], 'b')
            sim_results = vector_store.search_by_similarity('a', media=media)
            self.assertEqual(len(sim_results), 1)

    def test_schedule_creation_failure_raises_500(self):
        a = self.save()
        manager = scheduler.Scheduler()
        req = models.ScheduleRequest(
            job_type='builder', playlist_name='Evening', user_id='alice',
            schedule_details=models.ScheduleDetails(frequency='daily', time='12:00')
        )
        with patch.object(schedule_routes.scheduler, 'scheduler_manager', manager), \
             patch.object(manager, 'add_schedule', return_value=None):
            with self.assertRaises(HTTPException) as ctx:
                schedule_routes.api_create_schedule(req, self.auth(a))
            self.assertEqual(ctx.exception.status_code, 500)


if __name__ == '__main__':
    unittest.main()
