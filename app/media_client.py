"""An authenticated media connection, independent of application-wide settings."""
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from functools import wraps
import inspect
import threading
import time
from urllib.parse import quote

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

CLIENT_NAME = 'MixerBee'
CLIENT_VERSION = '2026.10.0'


@dataclass(frozen=True)
class Connection:
    id: str
    base_url: str
    server_type: str
    username: str
    password: str = field(repr=False)
    user_id: str = ''
    server_id: str = ''
    ai_settings: dict = field(default_factory=dict, repr=False)


class ConnectionUnavailable(RuntimeError):
    pass


# How long to stop re-attempting authentication after the server has actively
# rejected these credentials. Without it, a disabled media user or a changed
# password costs two failing HTTP round-trips on every single request, forever.
AUTH_FAILURE_COOLDOWN = 60

# Consecutive rejections before the cooldown is armed. A server restarting under a
# reverse proxy can answer a single request with 401 before its user database is
# ready; arming on that one answer would lock out a healthy server for a minute --
# and app/cache.py reads the resulting ConnectionUnavailable as revoked access and
# drops the library snapshot. Two in a row is no longer plausibly transient.
AUTH_FAILURE_THRESHOLD = 2


def _is_credential_rejection(exc):
    """True when the server refused the credentials, as opposed to being unreachable.

    Only a refusal earns a cooldown: a timeout or refused connection is transient and
    must keep retrying, and must not be reported to callers as an access change.
    """
    if isinstance(exc, ConnectionUnavailable):
        return True
    status = getattr(getattr(exc, 'response', None), 'status_code', None)
    return status in (401, 403)


class MediaClient:
    """Credentials and token checks are scoped to one saved connection.

    Sessions are thread-local: scheduler jobs and HTTP workers never concurrently
    mutate the same requests.Session. Requests cannot override connection auth.
    """
    def __init__(self, connection: Connection, token: str = '', session_factory=None, user_profile=None):
        self.connection = connection
        self._token = token
        self._user_profile = user_profile
        self._last_check = time.monotonic() if token else 0
        self._auth_failed_until = 0.0
        self._auth_error = ''
        self._auth_failures = 0
        self._auth_lock = threading.Lock()
        self._local = threading.local()
        self._session_factory = session_factory or self._new_session

    @staticmethod
    def _new_session():
        session = requests.Session()
        adapter = HTTPAdapter(max_retries=Retry(total=3, backoff_factor=0.3, status_forcelist=(502, 503, 504)))
        session.mount('http://', adapter)
        session.mount('https://', adapter)
        return session

    @property
    def session(self):
        if not hasattr(self._local, 'session'):
            self._local.session = self._session_factory()
        return self._local.session

    @property
    def user_id(self):
        return self.connection.user_id

    def require_user(self, user_id):
        if user_id != self.user_id:
            raise PermissionError('Requested media user does not match this connection.')
        return self

    def _headers(self, token=''):
        c = self.connection
        value = (f'MediaBrowser Client="{CLIENT_NAME}", Device="MixerBee", '
                 f'DeviceId="MixerBee-{c.id}", Version="{CLIENT_VERSION}"')
        if token:
            value += f', UserId="{c.user_id}", Token="{token}"'
        headers = {'Authorization' if c.server_type == 'jellyfin' else 'X-Emby-Authorization': value}
        if token:
            headers.update({'X-Emby-Token': token, 'X-MediaBrowser-Token': token, 'X-Emby-User-Id': c.user_id})
        return headers

    def authenticate(self):
        c = self.connection
        response = self.session.post(c.base_url.rstrip('/') + '/Users/AuthenticateByName',
                                     json={'Username': c.username, 'Pw': c.password},
                                     headers=self._headers(), timeout=10)
        response.raise_for_status()
        data = response.json()
        if c.user_id and data['User']['Id'] != c.user_id:
            raise ConnectionUnavailable('Server returned a different user. Reconnect this account.')
        if c.server_id and data.get('ServerId') and data['ServerId'] != c.server_id:
            raise ConnectionUnavailable('Server identity changed. Reconnect this account.')
        self._token = data['AccessToken']
        self._user_profile = data.get('User') or {}
        self._last_check = time.monotonic()
        # Working credentials clear any standing rejection cooldown immediately, so
        # re-saving a fixed password takes effect without waiting it out.
        self._auth_failed_until = 0.0
        self._auth_error = ''
        self._auth_failures = 0
        return data

    def ensure_authenticated(self):
        with self._auth_lock:
            if self._token and time.monotonic() - self._last_check < 300:
                return
            if time.monotonic() < self._auth_failed_until:
                raise ConnectionUnavailable(
                    self._auth_error or 'Media server rejected these credentials.'
                )
            if self._token:
                # User profile checks work for ordinary accounts; /System/Info can require
                # permissions unrelated to the user's playlist capabilities.
                response = self.session.get(self.connection.base_url.rstrip('/') + '/Users/' + self.user_id,
                                            headers=self._headers(self._token), timeout=5)
                if response.ok:
                    profile = response.json()
                    if profile.get('Id') != self.user_id:
                        raise ConnectionUnavailable('Token does not belong to this connection.')
                    self._user_profile = profile
                    self._last_check = time.monotonic()
                    # The token still works, so any earlier rejection was transient.
                    self._auth_failures = 0
                    return
                if response.status_code not in (401, 403):
                    response.raise_for_status()
            try:
                self.authenticate()
            except Exception as exc:
                if _is_credential_rejection(exc):
                    self._auth_failures += 1
                    if self._auth_failures >= AUTH_FAILURE_THRESHOLD:
                        self._auth_failed_until = time.monotonic() + AUTH_FAILURE_COOLDOWN
                        self._auth_error = f'Media server rejected these credentials: {exc}'
                raise

    def can_manage_collections(self):
        """Return the media server's current administrator capability for this user."""
        self.ensure_authenticated()
        if 'Policy' not in (self._user_profile or {}):
            response = self.session.get(
                self.connection.base_url.rstrip('/') + '/Users/' + self.user_id,
                headers=self._headers(self._token), timeout=5
            )
            response.raise_for_status()
            profile = response.json()
            if profile.get('Id') != self.user_id:
                raise ConnectionUnavailable('Profile does not belong to this connection.')
            self._user_profile = profile
        policy = self._user_profile.get('Policy') or {}
        return bool(policy.get('IsAdministrator'))

    def request(self, method, path, **kwargs):
        if not path.startswith('/') or path.startswith('//') or '://' in path:
            raise ValueError('Media requests require a server-relative path.')
        params = dict(kwargs.get('params') or {})
        if params.get('UserId') is not None:
            self.require_user(params['UserId'])
        if path.startswith('/Users/'):
            target = path.split('/')[2]
            if target not in ('Me', self.user_id):
                raise PermissionError('Cannot access another media user through this connection.')
        if method.upper() == 'GET' and (path == '/Items' or path.startswith('/Shows/') or path in ('/Persons', '/Studios', '/Genres', '/Artists')):
            params['UserId'] = self.user_id
        kwargs['params'] = params
        self.ensure_authenticated()
        headers = dict(kwargs.pop('headers', {}))
        headers.update(self._headers(self._token))
        kwargs.setdefault('timeout', 15)
        # Do not replay writes on auth/network errors: the server may have applied them.
        response = self.session.request(method, self.connection.base_url.rstrip('/') + path,
                                        headers=headers, **kwargs)
        if response.status_code == 401:
            self._last_check = 0
        return response

    def get(self, path, **kwargs):
        return self.request('GET', path, **kwargs)

    def post(self, path, **kwargs):
        return self.request('POST', path, **kwargs)

    def delete(self, path, **kwargs):
        return self.request('DELETE', path, **kwargs)

    def item_url(self, item_id):
        if not item_id:
            return None
        c = self.connection
        route = 'details' if c.server_type == 'jellyfin' else 'item'
        url = f'{c.base_url.rstrip("/")}/web/index.html#!/{route}?id={quote(str(item_id), safe="")}'
        if c.server_type != 'jellyfin' and c.server_id:
            url += '&serverId=' + quote(c.server_id, safe='')
        return url

    def image_url(self, item_id, image_type='Primary', tag='', max_height=450):
        """Browser-facing artwork URL, built the same way as item_url.

        Both Emby and Jellyfin serve item images without a token, so the poster grid
        can point straight at the server the user already browses.
        """
        if not item_id:
            return None
        url = (f'{self.connection.base_url.rstrip("/")}/Items/{quote(str(item_id), safe="")}'
               f'/Images/{quote(str(image_type), safe="")}?maxHeight={int(max_height)}')
        if tag:
            url += '&tag=' + quote(str(tag), safe='')
        return url

    def as_active(self):
        return media_scope(self)


_current_media = ContextVar('mixerbee_media_connection')


def current_media():
    """For synchronous AI tool callbacks, which cannot accept extra tool parameters."""
    return _current_media.get()


@contextmanager
def media_scope(media):
    token = _current_media.set(media)
    try:
        yield
    finally:
        _current_media.reset(token)


def media_operation(func):
    """Bind explicitly supplied media for nested AI tools; never use a global fallback."""
    signature = inspect.signature(func)

    @wraps(func)
    def wrapped(*args, **kwargs):
        media = signature.bind(*args, **kwargs).arguments.get('media')
        if media is None:
            media = current_media()
        with media_scope(media):
            return func(*args, **kwargs)
    return wrapped
