"""
app/log_buffer.py - Bounded in-memory capture of MixerBee's own log records.

Feeds the owner-only live log viewer. Nothing here touches the database, the network, or
the media server: emit() runs on whatever thread produced the line -- a request worker, an
APScheduler job, an enrichment thread, a connection-warming thread -- so it only formats,
redacts, and appends under a short lock.

The buffer is a ring keyed by an increasing sequence number inside a capture generation.
Slow readers lose old records rather than growing memory or blocking a build. A generation
changes on process start and on every verbose-logging enable, so a stale cursor from a
previous run can never be mistaken for current history.
"""

import json
import logging
import re
import threading
import time
import traceback
import uuid
from collections import deque

# Retention, kept as named constants so tests can lower them.
MAX_RECORDS = 2_000
MAX_BYTES = 2 * 1024 * 1024
MAX_RECORD_BYTES = 16 * 1024
BATCH_RECORDS = 100
BATCH_BYTES = 64 * 1024
MAX_STREAMS_PER_SESSION = 2
MAX_STREAMS_PER_PROCESS = 8

# Loggers captured in addition to every named MixerBee.* logger. APScheduler's own
# logger explains why a schedule did or did not fire, which is the single most common
# thing an owner is looking for. Uvicorn access logs and third-party libraries are
# deliberately absent: they would drown the buffer and leak unrelated request detail.
EXTRA_LOGGERS = ('apscheduler',)

TRUNCATION_MARKER = '\n... [truncated by MixerBee live logs]'
MASK = '[redacted]'

# Key names whose value is a credential. Matched with surrounding word characters so
# 'emby_pass', 'AccessToken', 'X-Emby-Token', 'gemini_api_key' and 'webhook_secret' all
# qualify. 'pass' is included bare because that is the field name this codebase actually
# uses; over-redacting a hypothetical 'bypass_cache=1' is the harmless direction.
# The surrounding runs are length-bounded and preceded by a lookbehind on purpose.
# emit() runs on a build thread, and an unanchored unbounded prefix made these patterns
# O(n^2): one 32 KiB log line took 20 seconds to scan, because the prefix was retried at
# every character. No real key name has 40 characters either side of the keyword.
_KEY_EDGE = r'[A-Za-z0-9_\-]{0,40}'
_KEYISH = (r'(?<![A-Za-z0-9_\-])' + _KEY_EDGE +
           r'(?:password|passwd|pass|secret|token|apikey|api[_\-]key|access[_\-]key|credential|authorization)'
           + _KEY_EDGE)

_MASKED = re.escape(MASK)

# Order matters. The authorization rule runs first because its value is two tokens
# ('Bearer abc') and the generic rules would otherwise leave the second one behind. The
# quoted forms run before the bare form so a redacted value is never rescanned.
_REDACTIONS = (
    # Authorization: Bearer abc  /  X-Authorization=Basic abc. Takes the rest of the
    # line; no DOTALL, so it stops at a newline and cannot eat a following message.
    (re.compile(r'(?i)\b([A-Za-z0-9_\-]{0,40}authorization[A-Za-z0-9_\-]{0,40}\s*[:=]\s*).+'),
     lambda m: f'{m.group(1)}{MASK}'),
    # A bare 'Bearer abc' with no key in front of it.
    (re.compile(r'(?i)\b(bearer\s+)([A-Za-z0-9._\-=+/]{4,})'),
     lambda m: f'{m.group(1)}{MASK}'),
    # scheme://user:password@host -- keeps the user, which is often the point of the line.
    (re.compile(r'(?i)\b([a-z][a-z0-9+.\-]*://)([^/\s:@]{1,128}):([^/\s@]{1,256})@'),
     lambda m: f'{m.group(1)}{m.group(2)}:{MASK}@'),
    # "password": "value"  /  'password': 'value'
    (re.compile(r'(?i)("?' + _KEYISH + r'"?\s*[:=]\s*)"(?:[^"\\]|\\.)*"'),
     lambda m: f'{m.group(1)}"{MASK}"'),
    (re.compile(r"(?i)('?" + _KEYISH + r"'?\s*[:=]\s*)'(?:[^'\\]|\\.)*'"),
     lambda m: f"{m.group(1)}'{MASK}'"),
    # password=value, token: value, ?token=value&next=... The lookahead skips a value an
    # earlier rule already masked, which would otherwise be re-cut at its own bracket.
    (re.compile(r'(?i)\b(' + _KEYISH + r')(\s*[:=]\s*)(?!\s|' + _MASKED + r')([^\s,;&)\]}\'"]+)'),
     lambda m: f'{m.group(1)}{m.group(2)}{MASK}'),
)

# Rough fixed cost of a serialized record's non-message fields. Used only for the byte
# budget, so an estimate is enough and avoids serializing twice on every log line.
_FIELD_OVERHEAD = 180


def redact(text: str) -> str:
    """Remove recognized credentials from one formatted log message.

    This is a safety net for values that reach a log line incidentally, inside a tool
    argument dump or an exception message. It is not a guarantee about arbitrary free
    text -- call sites must still avoid logging credentials in the first place.
    """
    if not text:
        return text
    for pattern, replacement in _REDACTIONS:
        text = pattern.sub(replacement, text)
    return text


class _CaptureHandler(logging.Handler):
    """Mirrors records into the shared buffer without disturbing console output."""

    def __init__(self, capture):
        # NOTSET: the owning logger's level already decides what INFO reaches us, so
        # this handler must not add a second, independent threshold.
        super().__init__(level=logging.NOTSET)
        self._capture = capture

    def emit(self, record):
        try:
            self._capture.store(record)
        except Exception:
            # Reporting a capture failure through logging would re-enter this handler.
            # Dropping the record is the only non-recursive option.
            pass

    def handleError(self, record):
        pass


class LogCapture:
    """The process-wide ring buffer and its handler."""

    def __init__(self):
        self._lock = threading.Lock()
        self._records = deque()
        self._bytes = 0
        self._seq = 0
        self._generation = uuid.uuid4().hex[:12]
        self._dropped = 0
        self._enabled = False
        self._handler = _CaptureHandler(self)
        self._attached = set()
        self._stream_lock = threading.Lock()
        self._streams_by_session = {}

    # -- lifecycle ---------------------------------------------------------------

    @property
    def enabled(self) -> bool:
        return self._enabled

    @property
    def generation(self) -> str:
        return self._generation

    def attach(self, logger: logging.Logger) -> None:
        """Add the capture handler to one logger, exactly once.

        Safe to call for a logger created long after startup: app.logger.get_logger()
        routes every new subsystem logger through here.
        """
        if logger is None:
            return
        with self._lock:
            if logger.name in self._attached:
                return
            self._attached.add(logger.name)
        if self._handler not in logger.handlers:
            logger.addHandler(self._handler)

    def attach_all(self) -> None:
        """Attach to every logger that already exists, plus the extra allowlist."""
        from app.logger import registered_loggers

        for logger in registered_loggers():
            self.attach(logger)
        for name in EXTRA_LOGGERS:
            self.attach(logging.getLogger(name))

    def set_enabled(self, enabled: bool) -> None:
        """Follow the installation-wide verbose logging setting.

        Disabling clears retained records immediately: the viewer is a troubleshooting
        tool, and keeping captured text around after the owner turned capture off would
        leave prompts and media titles in memory for no reason. Re-enabling starts a new
        generation, which invalidates every outstanding browser cursor.
        """
        enabled = bool(enabled)
        with self._lock:
            if enabled == self._enabled:
                return
            self._enabled = enabled
            self._records.clear()
            self._bytes = 0
            self._dropped = 0
            if enabled:
                self._generation = uuid.uuid4().hex[:12]
                self._seq = 0

    # -- capture -----------------------------------------------------------------

    def store(self, record: logging.LogRecord) -> None:
        if not self._enabled:
            return

        try:
            message = record.getMessage()
        except Exception:
            # Bad %-args must not lose the line entirely, and must not raise into the
            # caller's thread, which may be mid-build.
            message = str(getattr(record, 'msg', ''))

        if record.exc_info:
            try:
                # Not self.format(): logging.Formatter caches its result onto
                # record.exc_text, which the console handler would then reuse. Console
                # output must be byte-identical with and without the viewer attached.
                message += '\n' + ''.join(traceback.format_exception(*record.exc_info)).rstrip()
            except Exception:
                message += '\n[traceback unavailable]'
        elif record.exc_text:
            message += '\n' + record.exc_text
        if record.stack_info:
            message += '\n' + record.stack_info

        message = redact(message)

        truncated = False
        encoded = message.encode('utf-8', 'replace')
        if len(encoded) > MAX_RECORD_BYTES:
            # Cut on a character boundary, then mark it so the viewer can say the text
            # is incomplete rather than silently showing half a traceback.
            message = encoded[:MAX_RECORD_BYTES].decode('utf-8', 'ignore') + TRUNCATION_MARKER
            encoded = message.encode('utf-8', 'replace')
            truncated = True

        size = len(encoded) + _FIELD_OVERHEAD
        with self._lock:
            if not self._enabled:
                return
            self._seq += 1
            entry = {
                'id': f'{self._generation}:{self._seq}',
                'gen': self._generation,
                'seq': self._seq,
                'ts': record.created,
                'level': record.levelname,
                'levelno': record.levelno,
                'logger': record.name,
                'thread': record.threadName or '',
                'message': message,
                'truncated': truncated,
            }
            self._records.append((size, entry))
            self._bytes += size
            while self._records and (len(self._records) > MAX_RECORDS or self._bytes > MAX_BYTES):
                dropped_size, _ = self._records.popleft()
                self._bytes -= dropped_size
                self._dropped += 1

    # -- reading -----------------------------------------------------------------

    def limits(self) -> dict:
        return {'max_records': MAX_RECORDS, 'max_bytes': MAX_BYTES,
                'max_record_bytes': MAX_RECORD_BYTES, 'batch_records': BATCH_RECORDS,
                'batch_bytes': BATCH_BYTES}

    def read_after(self, generation: str | None, seq: int):
        """Return one bounded batch of records newer than the caller's cursor.

        The result is ``(status, records, skipped, generation)``. The generation is
        returned rather than read separately so a caller cannot advance its cursor into a
        generation that replaced the one it just read from.

        - ``'reset'``  the cursor belongs to another capture generation; the caller must
          discard it and start again from the retained history.
        - ``'gap'``    the requested record has already been evicted; ``skipped`` says how
          many were lost, and ``records`` continues from the oldest still held.
        - ``'ok'``     ``records`` continues directly from the cursor and may be empty.
        """
        with self._lock:
            if generation is not None and generation != self._generation:
                return 'reset', [], 0, self._generation
            if not self._records:
                return 'ok', [], 0, self._generation

            oldest = self._records[0][1]['seq']
            skipped = 0
            status = 'ok'
            if seq + 1 < oldest:
                skipped = oldest - seq - 1
                status = 'gap'
                seq = oldest - 1

            batch, batch_bytes = [], 0
            for size, entry in self._records:
                if entry['seq'] <= seq:
                    continue
                if batch and (len(batch) >= BATCH_RECORDS or batch_bytes + size > BATCH_BYTES):
                    break
                batch.append(entry)
                batch_bytes += size
            return status, batch, skipped, self._generation

    def stats(self) -> dict:
        with self._lock:
            return {'generation': self._generation, 'enabled': self._enabled,
                    'retained': len(self._records), 'bytes': self._bytes,
                    'dropped': self._dropped, 'latest_seq': self._seq}

    # -- stream slots ------------------------------------------------------------

    def acquire_stream(self, session_key: str) -> bool:
        """Reserve one of the bounded stream slots, per session and per process."""
        with self._stream_lock:
            total = sum(self._streams_by_session.values())
            per_session = self._streams_by_session.get(session_key, 0)
            if total >= MAX_STREAMS_PER_PROCESS or per_session >= MAX_STREAMS_PER_SESSION:
                return False
            self._streams_by_session[session_key] = per_session + 1
            return True

    def release_stream(self, session_key: str) -> None:
        with self._stream_lock:
            remaining = self._streams_by_session.get(session_key, 0) - 1
            if remaining > 0:
                self._streams_by_session[session_key] = remaining
            else:
                self._streams_by_session.pop(session_key, None)

    def active_streams(self) -> int:
        with self._stream_lock:
            return sum(self._streams_by_session.values())


capture = LogCapture()


def parse_cursor(value: str | None):
    """Validate an ``after`` cursor from a browser.

    The cursor is a position, not a credential: it is rejected when malformed, but a
    valid one grants nothing a fresh stream would not already deliver.
    """
    if not value or len(value) > 64:
        return None, 0
    generation, _, raw_seq = value.partition(':')
    if not re.fullmatch(r'[0-9a-f]{1,32}', generation) or not re.fullmatch(r'\d{1,16}', raw_seq):
        return None, 0
    return generation, int(raw_seq)


def sse_event(name: str, payload: dict, event_id: str | None = None) -> str:
    """Frame one server-sent event.

    json.dumps escapes newlines, so a multiline log message always stays on a single
    ``data:`` line and cannot be split into two events by its own content.
    """
    head = f'id: {event_id}\n' if event_id else ''
    return f'{head}event: {name}\ndata: {json.dumps(payload, default=str)}\n\n'


def heartbeat() -> str:
    """An SSE comment, which keeps proxies from idling the response out."""
    return f': keepalive {int(time.time())}\n\n'
