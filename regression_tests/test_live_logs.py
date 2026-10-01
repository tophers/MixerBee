"""Offline coverage for the owner-only live log viewer: capture, access, and streaming."""
# Import the existing harness first: it isolates runtime paths before app imports.
import test_connections as connection_tests
import test_accounts as account_tests

import asyncio
import io
import json
import logging
import threading
import time
import unittest
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch

from fastapi import HTTPException
from fastapi.testclient import TestClient
from starlette.requests import Request

import accounts
import app_state
import database
import web
from routers import logs as logs_router
from app import log_buffer
from app.log_buffer import capture, parse_cursor, redact
from app.logger import get_logger, refresh_logger_level, registered_loggers

STREAM = '/api/admin/logs/stream'


def read_events(response, limit=None, stop_on=()):
    """Parse an SSE body into (event_name, payload) pairs, ignoring heartbeats."""
    events, name, data = [], 'message', []
    for raw in response.iter_lines():
        line = raw.decode() if isinstance(raw, bytes) else raw
        if line.startswith(':'):
            continue
        if line == '':
            if data:
                events.append((name, json.loads('\n'.join(data))))
                if events[-1][0] in stop_on or (limit and len(events) >= limit):
                    break
            name, data = 'message', []
        elif line.startswith('event:'):
            name = line[6:].strip()
        elif line.startswith('data:'):
            data.append(line[5:].lstrip(' '))
    return events


class LiveLogTests(unittest.TestCase):
    setUp = connection_tests.ConnectionTests.setUp
    save = connection_tests.ConnectionTests.save
    bootstrap = account_tests.AccountTests.bootstrap
    pin = account_tests.AccountTests.pin
    bob = account_tests.AccountTests.bob

    def setUpCapture(self):
        """Leave the shared capture exactly as it was found."""
        self.addCleanup(refresh_logger_level)
        self.addCleanup(capture.set_enabled, False)
        capture.attach_all()
        capture.set_enabled(False)
        # capture is process-wide, so leave its stream slots clean for the next test
        # the same way the harness clears connections._clients and cache.CACHE.
        capture._streams_by_session.clear()
        self.addCleanup(capture._streams_by_session.clear)
        self.quiet_console()

    def quiet_console(self):
        """Mute the factory's own stdout handlers for the duration of one test.

        These tests emit thousands of lines on purpose. Raising the level on the
        handler rather than the logger keeps capture and any handler a test adds
        itself working, which is what the console-parity test depends on.
        """
        import sys
        for logger in registered_loggers():
            for handler in logger.handlers:
                if isinstance(handler, logging.StreamHandler) and handler.stream in (sys.stdout, sys.stderr):
                    previous = handler.level
                    handler.setLevel(logging.CRITICAL + 1)
                    self.addCleanup(handler.setLevel, previous)

    def enable(self):
        """Turn capture on the way the server does, without touching the database."""
        patcher = patch.object(app_state, 'VERBOSE_LOGGING', True)
        patcher.start()
        self.addCleanup(patcher.stop)
        refresh_logger_level()
        capture.attach_all()
        capture.set_enabled(True)

    def logger(self, name='MixerBee.LiveLogTest'):
        log = get_logger(name)
        # get_logger may have just created this one, so it was not in the roster when
        # setUpCapture muted the console.
        self.quiet_console()
        return log

    def messages(self):
        _, batch, _, _ = capture.read_after(None, 0)
        return [record['message'] for record in batch]

    # -- capture -----------------------------------------------------------------

    def test_capture_is_off_by_default_and_follows_the_setting(self):
        self.setUpCapture()
        log = self.logger()
        with patch.object(app_state, 'VERBOSE_LOGGING', False):
            refresh_logger_level()
            log.warning('while off')
        self.assertFalse(capture.enabled)
        self.assertEqual(self.messages(), [])

        self.enable()
        log.info('while on')
        self.assertIn('while on', self.messages())

        # Disabling drops retained text immediately rather than leaving it in memory.
        capture.set_enabled(False)
        self.assertEqual(self.messages(), [])

    def test_enabling_starts_a_new_generation_and_invalidates_old_cursors(self):
        self.setUpCapture()
        self.enable()
        first = capture.generation
        self.logger().info('first run')
        capture.set_enabled(False)
        capture.set_enabled(True)
        self.assertNotEqual(capture.generation, first)

        status, batch, _, generation = capture.read_after(first, 5)
        self.assertEqual(status, 'reset')
        self.assertEqual(batch, [])
        self.assertEqual(generation, capture.generation)

    def test_loggers_created_after_enabling_are_captured_exactly_once(self):
        self.setUpCapture()
        self.enable()
        late = self.logger('MixerBee.LiveLogTest.Late')
        late.info('late logger')
        # Re-registering the same name must not add a second handler, or every line
        # would appear twice in the viewer.
        self.logger('MixerBee.LiveLogTest.Late').info('again')
        handlers = [h for h in late.handlers if isinstance(h, log_buffer._CaptureHandler)]
        self.assertEqual(len(handlers), 1)
        self.assertEqual(self.messages().count('late logger'), 1)

    def test_console_output_is_unchanged_by_capture(self):
        self.setUpCapture()
        self.enable()
        log = self.logger()
        console = io.StringIO()
        handler = logging.StreamHandler(console)
        handler.setFormatter(logging.Formatter('%(levelname)s: [%(name)s] %(message)s'))
        log.addHandler(handler)
        self.addCleanup(log.removeHandler, handler)

        try:
            raise ValueError('boom')
        except ValueError:
            log.error('failed %s/%s', 2, 3, exc_info=True)

        printed = console.getvalue()
        self.assertIn('ERROR: [MixerBee.LiveLogTest] failed 2/3', printed)
        self.assertIn('ValueError: boom', printed)
        self.assertIn('Traceback (most recent call last)', printed)

        captured = self.messages()[-1]
        self.assertIn('failed 2/3', captured)
        self.assertIn('ValueError: boom', captured)

    def test_levels_formatting_and_multiline_are_retained(self):
        self.setUpCapture()
        self.enable()
        log = self.logger()
        log.info('count %d of %s', 3, 'seven')
        log.warning('line one\nline two')
        log.error('plain error')
        log.critical('critical error')

        _, batch, _, _ = capture.read_after(None, 0)
        by_level = {record['level']: record['message'] for record in batch}
        self.assertEqual(by_level['INFO'], 'count 3 of seven')
        self.assertEqual(by_level['WARNING'], 'line one\nline two')
        self.assertEqual(set(by_level), {'INFO', 'WARNING', 'ERROR', 'CRITICAL'})
        self.assertTrue(all(record['logger'] == 'MixerBee.LiveLogTest' for record in batch))
        self.assertTrue(all(record['thread'] for record in batch))

    def test_bad_format_arguments_do_not_raise_into_the_caller(self):
        self.setUpCapture()
        self.enable()
        log = self.logger()
        # logging swallows the formatting error itself; the point is that capture
        # neither raises nor loses the line.
        log.handle(logging.LogRecord('MixerBee.LiveLogTest', logging.INFO, __file__, 1,
                                     'needs %d args', (), None))
        self.assertTrue(any('needs' in m for m in self.messages()))

    def test_record_truncation_marks_the_entry(self):
        self.setUpCapture()
        self.enable()
        self.logger().info('x' * (log_buffer.MAX_RECORD_BYTES * 2))
        _, batch, _, _ = capture.read_after(None, 0)
        record = batch[-1]
        self.assertTrue(record['truncated'])
        self.assertIn('truncated', record['message'])
        self.assertLess(len(record['message'].encode()),
                        log_buffer.MAX_RECORD_BYTES + len(log_buffer.TRUNCATION_MARKER) + 8)

    def test_formatting_a_long_line_stays_cheap(self):
        """Guards the redaction patterns against quadratic backtracking.

        emit() runs on whatever thread logged the line -- often a build -- so the cost
        of one pathological message is the cost of stalling that build. An unanchored
        unbounded prefix on the quoted-secret patterns took 20 seconds for 32 KiB.
        """
        started = time.monotonic()
        redact('x' * 1_000_000)
        self.assertLess(time.monotonic() - started, 1.0)

        self.setUpCapture()
        self.enable()
        started = time.monotonic()
        self.logger().info('%s', 'y' * 1_000_000)
        self.assertLess(time.monotonic() - started, 1.0)

    def test_count_and_byte_limits_bound_retention_and_report_the_gap(self):
        self.setUpCapture()
        self.enable()
        log = self.logger()
        with patch.object(log_buffer, 'MAX_RECORDS', 10):
            for index in range(40):
                log.info('entry %d', index)
            stats = capture.stats()
            self.assertEqual(stats['retained'], 10)
            self.assertEqual(stats['dropped'], 30)

            # A cursor older than the retained window reports exactly what was lost
            # instead of silently resuming.
            status, batch, skipped, _ = capture.read_after(capture.generation, 1)
            self.assertEqual(status, 'gap')
            self.assertEqual(skipped, 29)
            self.assertEqual(batch[0]['message'], 'entry 30')

        with patch.object(log_buffer, 'MAX_BYTES', 4096):
            for index in range(200):
                log.info('padded %d %s', index, 'y' * 400)
            self.assertLessEqual(capture.stats()['bytes'], 4096)

    def test_batches_are_bounded_by_count_and_bytes(self):
        self.setUpCapture()
        self.enable()
        log = self.logger()
        for index in range(500):
            log.info('batched %d', index)
        _, batch, _, _ = capture.read_after(None, 0)
        self.assertEqual(len(batch), log_buffer.BATCH_RECORDS)

        with patch.object(log_buffer, 'BATCH_BYTES', 1024):
            _, small, _, _ = capture.read_after(None, 0)
        self.assertLess(len(small), log_buffer.BATCH_RECORDS)
        self.assertGreaterEqual(len(small), 1)

    def test_concurrent_writers_get_unique_ordered_ids(self):
        self.setUpCapture()
        self.enable()
        log = self.logger()
        start = threading.Barrier(8)

        def write(worker):
            start.wait()
            for index in range(50):
                log.info('worker %d entry %d', worker, index)

        with patch.object(log_buffer, 'MAX_RECORDS', 10_000):
            with ThreadPoolExecutor(max_workers=8) as pool:
                list(pool.map(write, range(8)))
            seqs = []
            cursor = 0
            while True:
                _, batch, _, _ = capture.read_after(capture.generation, cursor)
                if not batch:
                    break
                seqs.extend(record['seq'] for record in batch)
                cursor = batch[-1]['seq']

        self.assertEqual(len(seqs), 400)
        self.assertEqual(len(set(seqs)), 400)
        self.assertEqual(seqs, sorted(seqs))

    def test_capture_failure_does_not_recurse_or_raise(self):
        self.setUpCapture()
        self.enable()
        log = self.logger()
        with patch.object(log_buffer.LogCapture, 'store', side_effect=RuntimeError('buffer broken')):
            log.info('still returns')  # must not raise into the calling thread

    # -- redaction ----------------------------------------------------------------

    def test_redaction_covers_structured_nested_and_multiline_credentials(self):
        self.setUpCapture()
        self.enable()
        log = self.logger()
        secret = 'sup3r-s3cret-value'
        cases = [
            f'emby_pass={secret}',
            f'{{"password": "{secret}"}}',
            f"{{'gemini_api_key': '{secret}'}}",
            f'Authorization: Bearer {secret}',
            f'POST /api/webhook/conn-1?token={secret}&event=play',
            f'http://alice:{secret}@media.example/emby',
            f'tool args: {{"outer": {{"X-Emby-Token": "{secret}"}}}}',
            f'AccessToken: {secret}\nnext line is fine',
            f'webhook_secret = {secret}; external_api_key={secret}',
        ]
        for case in cases:
            log.info('%s', case)

        for message in self.messages():
            self.assertNotIn(secret, message, message)
            self.assertIn(log_buffer.MASK, message, message)

        # Redaction must not eat the surrounding context it is there to explain.
        joined = '\n'.join(self.messages())
        self.assertIn('event=play', joined)
        self.assertIn('alice', joined)
        self.assertIn('next line is fine', joined)

        # Nor should it fire on ordinary text that merely looks similar.
        self.assertEqual(redact('Selected 12 movies for Tokens of Affection (2011)'),
                         'Selected 12 movies for Tokens of Affection (2011)')

    def test_redaction_leaves_console_output_alone(self):
        self.setUpCapture()
        self.enable()
        log = self.logger()
        console = io.StringIO()
        handler = logging.StreamHandler(console)
        log.addHandler(handler)
        self.addCleanup(log.removeHandler, handler)
        log.info('password=plaintext-on-console')
        self.assertIn('password=plaintext-on-console', console.getvalue())
        self.assertNotIn('plaintext-on-console', '\n'.join(self.messages()))

    def test_cursor_parsing_rejects_malformed_values(self):
        self.assertEqual(parse_cursor('abc123:45'), ('abc123', 45))
        for bad in (None, '', 'nogeneration', 'abc123:', ':5', 'ZZZZ:5', 'abc123:x',
                    'abc123:' + '9' * 40, 'a' * 80 + ':1', 'abc123:5:7'):
            self.assertEqual(parse_cursor(bad), (None, 0), bad)

    def test_stream_slots_are_bounded_per_session_and_process(self):
        self.setUpCapture()
        with patch.object(log_buffer, 'MAX_STREAMS_PER_SESSION', 2), \
                patch.object(log_buffer, 'MAX_STREAMS_PER_PROCESS', 3):
            self.assertTrue(capture.acquire_stream('session-a'))
            self.assertTrue(capture.acquire_stream('session-a'))
            self.assertFalse(capture.acquire_stream('session-a'))
            self.assertTrue(capture.acquire_stream('session-b'))
            self.assertFalse(capture.acquire_stream('session-b'))

            capture.release_stream('session-a')
            self.assertTrue(capture.acquire_stream('session-b'))
            for key in ('session-a', 'session-b', 'session-b'):
                capture.release_stream(key)
        self.assertEqual(capture.active_streams(), 0)

    # -- access -------------------------------------------------------------------

    def test_stream_requires_an_owner_session(self):
        self.setUpCapture()
        owner, _ = self.bootstrap(legacy=False)
        member = self.bob(owner)
        anon = TestClient(web.app)
        self.enable()

        self.assertEqual(anon.get(STREAM).status_code, 401)
        self.assertEqual(member.get(STREAM).status_code, 403)
        self.assertEqual(anon.get(STREAM, headers={'X-MixerBee-Key': 'external-key'}).status_code, 401)
        # A stale account pin is rejected by the middleware before the stream opens.
        self.assertEqual(owner.get(STREAM, headers={'X-MixerBee-Account': 'someone-else'}).status_code, 409)
        self.assertEqual(capture.active_streams(), 0)

    def test_stream_refuses_while_logging_is_disabled(self):
        self.setUpCapture()
        owner, _ = self.bootstrap(legacy=False)
        with patch.object(app_state, 'VERBOSE_LOGGING', False):
            response = owner.get(STREAM)
        self.assertEqual(response.status_code, 409)
        # A structured reason, so the viewer stops instead of reloading the page.
        self.assertEqual(response.json()['detail']['reason'], 'logging_disabled')
        self.assertEqual(capture.active_streams(), 0)

    def test_stream_limit_returns_429_and_releases_the_slot(self):
        self.setUpCapture()
        owner, _ = self.bootstrap(legacy=False)
        self.enable()
        with patch.object(log_buffer, 'MAX_STREAMS_PER_SESSION', 0):
            response = owner.get(STREAM)
        self.assertEqual(response.status_code, 429)
        self.assertEqual(response.json()['detail']['reason'], 'stream_limit')
        self.assertEqual(capture.active_streams(), 0)

    def test_middleware_still_sets_no_store_on_ordinary_api_responses(self):
        """The stream needs its own Cache-Control, so the middleware stopped
        overwriting one that is already set. Ordinary endpoints must be unaffected."""
        self.setUpCapture()
        owner, _ = self.bootstrap(legacy=False)
        for path in ('/api/status', '/api/auth/status', '/api/admin/settings/logging'):
            response = owner.get(path)
            self.assertEqual(response.headers['cache-control'], 'no-store', path)

        self.enable()
        stream, next_event, _, close = self.open_stream(owner)
        self.assertEqual(stream.headers['cache-control'], 'no-store, no-transform')
        self.assertEqual(next_event()[0], 'ready')
        close()

    def test_household_member_cannot_reach_the_stream_router_directly(self):
        """Belt and braces: the router's own owner check, not just the middleware."""
        self.setUpCapture()
        owner, _ = self.bootstrap(legacy=False)
        member = self.bob(owner)
        self.enable()
        with self.assertRaises(HTTPException) as caught:
            self.run_async(logs_router.stream_logs(self.request_for(member), after=None))
        self.assertEqual(caught.exception.status_code, 403)
        self.assertEqual(capture.active_streams(), 0)

    # -- live delivery -------------------------------------------------------------
    #
    # Driven against the endpoint's own response generator rather than through
    # TestClient: TestClient buffers a response body to completion before returning,
    # so it can never read from a stream that stays open.

    def scope_for(self, client):
        """An ASGI scope matching the one TestClient produces, cookies included.

        root_path matters: cookie_name() keys the session cookie on host + root path so
        two instances on one hostname cannot overwrite each other, and outside a
        container the app's root path is /mixerbee.
        """
        cookies = '; '.join(f'{name}={value}' for name, value in client.cookies.items())
        return {
            'type': 'http', 'http_version': '1.1', 'method': 'GET', 'scheme': 'http',
            'path': '/api/admin/logs/stream', 'raw_path': b'/api/admin/logs/stream',
            'root_path': web.ROOT_PATH, 'query_string': b'',
            'server': ('testserver', 80), 'client': ('testclient', 50000),
            'headers': [(b'host', b'testserver'), (b'cookie', cookies.encode())],
            'state': {},
        }

    @staticmethod
    async def never_receives():
        # is_disconnected() cancels its own scope before awaiting, so this only has to
        # be a checkpoint that never resolves on its own.
        await asyncio.Event().wait()

    def session_token(self, client):
        probe = Request(self.scope_for(client), receive=self.never_receives)
        return client.cookies.get(accounts.cookie_name(probe))

    def request_for(self, client):
        """A Request carrying this TestClient's session, as the middleware leaves it."""
        request = Request(self.scope_for(client), receive=self.never_receives)
        request.state.account = accounts.read_session(self.session_token(client))
        return request

    def run_async(self, coroutine):
        return asyncio.run(coroutine)

    def open_stream(self, client, after=None):
        """Returns (response, next_event, next_raw, close) for one open log stream.

        The stream slot is taken by the handler, before the response generator exists,
        so the generator has to be stepped at least once for close() to run its finally
        and give the slot back. Read the `ready` event before asserting on slot counts.
        """
        loop = asyncio.new_event_loop()
        self.addCleanup(loop.close)
        response = loop.run_until_complete(
            logs_router.stream_logs(self.request_for(client), after=after))
        frames = response.body_iterator

        def next_event(timeout=5.0):
            async def pull():
                while True:
                    chunk = await asyncio.wait_for(frames.__anext__(), timeout)
                    if chunk.startswith(':'):
                        continue            # heartbeat comment
                    name, payload = 'message', []
                    for line in chunk.strip('\n').split('\n'):
                        if line.startswith('event:'):
                            name = line[6:].strip()
                        elif line.startswith('data:'):
                            payload.append(line[5:].lstrip(' '))
                    return name, json.loads('\n'.join(payload))
            return loop.run_until_complete(pull())

        def next_raw(timeout=5.0):
            return loop.run_until_complete(asyncio.wait_for(frames.__anext__(), timeout))

        def close():
            loop.run_until_complete(frames.aclose())

        self.addCleanup(close)
        return response, next_event, next_raw, close

    def test_owner_streams_recent_history_with_no_media_connection(self):
        self.setUpCapture()
        owner, _ = self.bootstrap(legacy=False)
        self.enable()
        self.logger().info('no connection needed')

        response, next_event, _, close = self.open_stream(owner)
        self.assertEqual(response.media_type, 'text/event-stream')
        self.assertIn('no-store', response.headers['cache-control'])
        self.assertIn('no-transform', response.headers['cache-control'])
        self.assertEqual(response.headers['x-accel-buffering'], 'no')
        self.assertEqual(capture.active_streams(), 1)

        name, ready = next_event()
        self.assertEqual(name, 'ready')
        self.assertTrue(ready['enabled'])
        self.assertEqual(ready['generation'], capture.generation)
        self.assertEqual(ready['limits']['max_records'], log_buffer.MAX_RECORDS)

        name, batch = next_event()
        self.assertEqual(name, 'logs')
        self.assertEqual([r['message'] for r in batch['records']], ['no connection needed'])

        # New records arrive on the same open stream.
        self.logger().info('arrived later')
        name, batch = next_event()
        self.assertEqual(name, 'logs')
        self.assertEqual([r['message'] for r in batch['records']], ['arrived later'])

        close()
        self.assertEqual(capture.active_streams(), 0)

    def test_history_is_delivered_in_bounded_batches(self):
        self.setUpCapture()
        owner, _ = self.bootstrap(legacy=False)
        self.enable()
        log = self.logger()
        for index in range(250):
            log.info('history %d', index)

        _, next_event, _, close = self.open_stream(owner)
        self.assertEqual(next_event()[0], 'ready')
        sizes, delivered = [], []
        for _ in range(3):
            name, batch = next_event()
            self.assertEqual(name, 'logs')
            sizes.append(len(batch['records']))
            delivered.extend(r['message'] for r in batch['records'])
        close()

        self.assertEqual(sizes, [log_buffer.BATCH_RECORDS] * 2 + [50])
        self.assertEqual(delivered, [f'history {index}' for index in range(250)])

    def test_heartbeat_is_sent_while_idle(self):
        self.setUpCapture()
        owner, _ = self.bootstrap(legacy=False)
        self.enable()
        with patch.object(logs_router, 'HEARTBEAT_SECONDS', 0.0), \
                patch.object(logs_router, 'POLL_SECONDS', 0.01):
            _, next_event, next_raw, close = self.open_stream(owner)
            self.assertIn('event: ready', next_raw())
            self.assertTrue(next_raw().startswith(':'))
            close()

    def test_stream_stops_when_the_session_is_revoked(self):
        self.setUpCapture()
        owner, _ = self.bootstrap(legacy=False)
        self.enable()
        self.logger().info('before revocation')

        with patch.object(logs_router, 'IDLE_RECHECK_SECONDS', 0.0):
            _, next_event, _, close = self.open_stream(owner)
            self.assertEqual(next_event()[0], 'ready')
            self.assertEqual(next_event()[0], 'logs')

            with database.get_db_connection() as conn:
                conn.execute('DELETE FROM account_sessions')
                conn.commit()
            self.logger().info('after revocation')

            name, payload = next_event()
            self.assertEqual(name, 'auth_expired')
            self.assertIn('no longer signed in', payload['detail'])
            with self.assertRaises(StopAsyncIteration):
                next_event()
            close()
        self.assertEqual(capture.active_streams(), 0)

    def test_losing_owner_role_stops_delivery(self):
        self.setUpCapture()
        owner, _ = self.bootstrap(legacy=False)
        self.enable()
        with patch.object(logs_router, 'IDLE_RECHECK_SECONDS', 0.0):
            _, next_event, _, close = self.open_stream(owner)
            self.assertEqual(next_event()[0], 'ready')
            with database.get_db_connection() as conn:
                conn.execute('UPDATE accounts SET is_admin=0')
                conn.commit()
            self.logger().info('must not be delivered')
            self.assertEqual(next_event()[0], 'auth_expired')
            close()

    def test_password_change_stops_delivery(self):
        self.setUpCapture()
        owner, _ = self.bootstrap(legacy=False)
        self.enable()
        with patch.object(logs_router, 'IDLE_RECHECK_SECONDS', 0.0):
            _, next_event, _, close = self.open_stream(owner)
            self.assertEqual(next_event()[0], 'ready')
            # change_password deletes every session for the account.
            session = accounts.read_session(self.session_token(owner))
            accounts.change_password(session['id'], 'another-long-password')
            self.logger().info('must not be delivered')
            self.assertEqual(next_event()[0], 'auth_expired')
            close()

    def test_expired_session_stops_delivery(self):
        self.setUpCapture()
        owner, _ = self.bootstrap(legacy=False)
        self.enable()
        with patch.object(logs_router, 'IDLE_RECHECK_SECONDS', 0.0):
            _, next_event, _, close = self.open_stream(owner)
            self.assertEqual(next_event()[0], 'ready')
            with database.get_db_connection() as conn:
                conn.execute('UPDATE account_sessions SET expires_at=?', (time.time() - 1,))
                conn.commit()
            self.assertEqual(next_event()[0], 'auth_expired')
            close()

    def test_stream_stops_when_logging_is_turned_off_elsewhere(self):
        self.setUpCapture()
        owner, _ = self.bootstrap(legacy=False)
        self.enable()
        _, next_event, _, close = self.open_stream(owner)
        self.assertEqual(next_event()[0], 'ready')

        capture.set_enabled(False)
        name, payload = next_event()
        self.assertEqual(name, 'state')
        self.assertFalse(payload['enabled'])
        self.assertEqual(payload['reason'], 'logging_disabled')
        with self.assertRaises(StopAsyncIteration):
            next_event()
        close()
        self.assertEqual(capture.active_streams(), 0)

    def test_generation_change_sends_reset_then_current_history(self):
        self.setUpCapture()
        owner, _ = self.bootstrap(legacy=False)
        self.enable()
        self.logger().info('current generation')

        stale = f'{"0" * 12}:9999'
        _, next_event, _, close = self.open_stream(owner, after=stale)
        self.assertEqual(next_event()[0], 'ready')
        name, payload = next_event()
        self.assertEqual(name, 'reset')
        self.assertEqual(payload['generation'], capture.generation)
        name, batch = next_event()
        self.assertEqual(name, 'logs')
        self.assertEqual([r['message'] for r in batch['records']], ['current generation'])
        close()

    def test_reconnect_with_a_cursor_resumes_without_repeating(self):
        self.setUpCapture()
        owner, _ = self.bootstrap(legacy=False)
        self.enable()
        log = self.logger()
        log.info('already seen')

        _, next_event, _, close = self.open_stream(owner)
        self.assertEqual(next_event()[0], 'ready')
        _, batch = next_event()
        last = batch['records'][-1]
        close()

        log.info('only after reconnect')
        _, next_event, _, close = self.open_stream(owner, after=f"{last['gen']}:{last['seq']}")
        self.assertEqual(next_event()[0], 'ready')
        name, batch = next_event()
        self.assertEqual(name, 'logs')
        self.assertEqual([r['message'] for r in batch['records']], ['only after reconnect'])
        close()

    def test_malformed_cursor_falls_back_to_full_history(self):
        self.setUpCapture()
        owner, _ = self.bootstrap(legacy=False)
        self.enable()
        self.logger().info('still delivered')
        _, next_event, _, close = self.open_stream(owner, after='not-a-cursor')
        self.assertEqual(next_event()[0], 'ready')
        name, batch = next_event()
        self.assertEqual(name, 'logs')
        self.assertEqual([r['message'] for r in batch['records']], ['still delivered'])
        close()

    def test_gap_is_reported_to_a_slow_client(self):
        self.setUpCapture()
        owner, _ = self.bootstrap(legacy=False)
        self.enable()
        log = self.logger()
        with patch.object(log_buffer, 'MAX_RECORDS', 5):
            for index in range(30):
                log.info('fast %d', index)
            _, next_event, _, close = self.open_stream(
                owner, after=f'{capture.generation}:2')
            self.assertEqual(next_event()[0], 'ready')
            name, payload = next_event()
            self.assertEqual(name, 'gap')
            # 30 written, 5 retained (seq 26-30), cursor at 2: seq 3-25 are gone.
            self.assertEqual(payload['skipped'], 23)
            self.assertEqual(payload['generation'], capture.generation)
            name, batch = next_event()
            self.assertEqual(name, 'logs')
            self.assertEqual(batch['records'][0]['message'], 'fast 25')
            close()

    def test_html_in_a_log_message_is_delivered_as_data(self):
        self.setUpCapture()
        owner, _ = self.bootstrap(legacy=False)
        self.enable()
        payload = '<img src=x onerror="alert(1)"> & </script>'
        self.logger().info('%s', payload)
        _, next_event, next_raw, close = self.open_stream(owner)
        self.assertEqual(next_event()[0], 'ready')
        frame = next_raw()
        close()
        # One data: line, JSON-escaped, so the message cannot break SSE framing. The
        # drawer renders it with x-text; it is never handed to x-html.
        self.assertEqual(frame.count('\ndata:'), 1)
        self.assertEqual(json.loads(frame.split('data:', 1)[1])['records'][0]['message'], payload)

    def test_a_burst_cannot_back_up_behind_an_idle_reader(self):
        self.setUpCapture()
        owner, _ = self.bootstrap(legacy=False)
        self.enable()
        log = self.logger('MixerBee.Builder')
        _, next_event, _, close = self.open_stream(owner)
        self.assertEqual(next_event()[0], 'ready')

        with patch.object(log_buffer, 'MAX_RECORDS', 50):
            started = time.monotonic()
            for index in range(5_000):
                log.info('resolved block %d', index)
            elapsed = time.monotonic() - started

        # A reader that never reads must never become backpressure on a build, and
        # retention has to stay at the configured bound rather than queueing per client.
        self.assertLess(elapsed, 10.0)
        self.assertLessEqual(capture.stats()['retained'], 50)
        close()
        self.assertEqual(capture.active_streams(), 0)

    def test_cancelling_a_stream_releases_its_slot(self):
        self.setUpCapture()
        owner, _ = self.bootstrap(legacy=False)
        self.enable()
        _, next_event, _, close = self.open_stream(owner)
        self.assertEqual(next_event()[0], 'ready')
        self.assertEqual(capture.active_streams(), 1)
        close()
        self.assertEqual(capture.active_streams(), 0)
        # Closing twice must not drive the count negative.
        close()
        self.assertEqual(capture.active_streams(), 0)

    def test_preference_endpoint_still_drives_capture(self):
        self.setUpCapture()
        owner, _ = self.bootstrap(legacy=False)
        path = '/api/admin/settings/logging'
        self.assertEqual(owner.post(path, json={'verbose_logging': True}).status_code, 200)
        self.assertTrue(capture.enabled)
        self.logger().info('enabled through the API')
        self.assertIn('enabled through the API', self.messages())

        self.assertEqual(owner.post(path, json={'verbose_logging': False}).status_code, 200)
        self.assertFalse(capture.enabled)
        self.assertEqual(self.messages(), [])


if __name__ == '__main__':
    unittest.main()
