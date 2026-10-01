"""Owner-only live delivery of captured log records.

The response is long-lived, so initial authorization is not enough: the original session
is re-read from SQLite before every batch and at least every few seconds while idle, and
delivery stops the moment it stops being a valid owner session. A logout, password change,
or expiry therefore ends the stream without the browser having to reload.
"""

import asyncio
import time

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import StreamingResponse

import accounts
import app_state
from app.log_buffer import capture, heartbeat, parse_cursor, sse_event

router = APIRouter()

# Poll interval for new records. emit() runs on arbitrary threads and must not touch the
# event loop, so the stream waits rather than being woken -- there is no cross-thread
# signal to deliver and a quarter second is well inside the one-second delivery target.
POLL_SECONDS = 0.25
HEARTBEAT_SECONDS = 15.0
IDLE_RECHECK_SECONDS = 5.0


async def _session_for(token: str):
    """Re-read the session off the event loop; SQLite access here is synchronous."""
    return await asyncio.to_thread(accounts.read_session, token)


def _is_owner(session, account_id: str) -> bool:
    return bool(session and session['is_admin'] and session['id'] == account_id)


@router.get('/api/admin/logs/stream')
async def stream_logs(request: Request, after: str | None = Query(default=None, max_length=64)):
    account = request.state.account
    if not account['is_admin']:
        raise HTTPException(403, 'Only the installation owner can read MixerBee logs.')

    token = request.cookies.get(accounts.cookie_name(request))
    if not token:
        raise HTTPException(401, 'Sign in to MixerBee.')

    if not app_state.VERBOSE_LOGGING or not capture.enabled:
        # A structured reason, so the viewer treats this as "capture is off" and stops,
        # instead of the stale-session reload that a bare 409 triggers.
        raise HTTPException(409, {'detail': 'Verbose logging is off.', 'reason': 'logging_disabled'})

    # The slot is taken here, not inside the generator, because the limit has to be
    # answerable as a 429 status before a response body exists. Starlette always steps
    # a StreamingResponse's iterator, so the generator's finally always runs and gives
    # the slot back; anything that stops iterating this response must still reach it.
    session_key = accounts.token_hash(token)
    if not capture.acquire_stream(session_key):
        raise HTTPException(429, {'detail': 'Too many log viewers are open. Close one and try again.',
                                  'reason': 'stream_limit'})

    account_id = account['id']
    cursor_generation, cursor_seq = parse_cursor(after)

    async def events():
        nonlocal cursor_generation, cursor_seq
        last_write = time.monotonic()
        last_check = last_write
        try:
            yield sse_event('ready', {'generation': capture.generation, 'enabled': True,
                                      'limits': capture.limits(),
                                      'poll_ms': int(POLL_SECONDS * 1000)})
            while True:
                if await request.is_disconnected():
                    return

                now = time.monotonic()
                if now - last_check >= IDLE_RECHECK_SECONDS:
                    if not _is_owner(await _session_for(token), account_id):
                        yield sse_event('auth_expired', {'detail': 'This session is no longer signed in.'})
                        return
                    last_check = time.monotonic()

                if not app_state.VERBOSE_LOGGING or not capture.enabled:
                    yield sse_event('state', {'enabled': False, 'reason': 'logging_disabled'})
                    return

                status, batch, skipped, generation = capture.read_after(cursor_generation, cursor_seq)

                if status == 'reset':
                    cursor_generation, cursor_seq = None, 0
                    yield sse_event('reset', {'generation': generation})
                    last_write = time.monotonic()
                    continue

                if batch:
                    # Fail closed before handing over any content: a session revoked
                    # one moment ago must not receive this batch.
                    if not _is_owner(await _session_for(token), account_id):
                        yield sse_event('auth_expired', {'detail': 'This session is no longer signed in.'})
                        return
                    last_check = time.monotonic()

                    if status == 'gap':
                        yield sse_event('gap', {'skipped': skipped, 'generation': generation})

                    cursor_generation = generation
                    cursor_seq = batch[-1]['seq']
                    yield sse_event('logs', {'generation': cursor_generation, 'records': batch},
                                    event_id=batch[-1]['id'])
                    last_write = time.monotonic()
                    # A full batch means more history is waiting. Drain it without a
                    # sleep so opening the drawer shows the whole buffer at once.
                    continue

                await asyncio.sleep(POLL_SECONDS)
                if time.monotonic() - last_write >= HEARTBEAT_SECONDS:
                    yield heartbeat()
                    last_write = time.monotonic()
        except asyncio.CancelledError:
            raise
        finally:
            capture.release_stream(session_key)

    return StreamingResponse(events(), media_type='text/event-stream', headers={
        'Cache-Control': 'no-store, no-transform',
        # Nginx buffers proxied responses by default, which would hold a log line until
        # the buffer filled. Other proxies need their own configuration; see USAGE.md.
        'X-Accel-Buffering': 'no',
    })
