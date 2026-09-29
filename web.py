"""
web.py – FastAPI wrapper
"""

import os
import secrets
import accounts
import logging
from pathlib import Path
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

import threading
from concurrent.futures import ThreadPoolExecutor
from app.ai.vector_store import ensure_cosine_similarity, ensure_library_indexed

import scheduler
import app_state
import database
from app.cache import refresh_cache
from app import build_history
from routers import config, builder, library, quick_playlists, presets
from routers import assist as assist_router
from routers import scheduler as scheduler_router
from routers import webhooks
from routers import accounts as account_routes

IS_CONTAINER = os.path.exists('/.dockerenv') or os.path.exists('/run/.containerenv')

ROOT_PATH = os.getenv("MIXERBEE_ROOT_PATH")
if ROOT_PATH is None:
    ROOT_PATH = "" if IS_CONTAINER else "/mixerbee"

@asynccontextmanager
async def lifespan(app: FastAPI):
    database.init_db()
    # Import legacy environment credentials only before the first local account.
    if accounts.setup_required():
        app_state.load_and_authenticate()
        logging.info("MixerBee initial setup required: Open the web UI to create the owner account.")

    # A build killed mid-flight (container stop, SIGKILL) leaves its row at 'running'
    # forever. Nothing can still be running in a process that just started.
    build_history.reconcile_interrupted_runs()

    def warm_one(media):
        try:
            ensure_cosine_similarity(media=media)
            refresh_cache(media)
            # Indexing is unconditional: Echo blocks and semantic search read this
            # index and need no AI provider, so warming it must not depend on one.
            ensure_library_indexed(media.user_id, media)
        except Exception:
            logging.warning("Could not warm saved connection %s", media.connection.id)

    def warm_connections():
        from connections import all_media_clients
        clients = list(all_media_clients())
        if not clients:
            return
        # Warm connections concurrently: one unreachable server used to stall every
        # connection queued behind it for its full timeout budget.
        with ThreadPoolExecutor(max_workers=min(4, len(clients)),
                                thread_name_prefix='warm') as pool:
            list(pool.map(warm_one, clients))
    threading.Thread(target=warm_connections, daemon=True).start()

    scheduler.scheduler_manager.start()

    yield

    # wait=True: APScheduler's executor wraps concurrent.futures.ThreadPoolExecutor,
    # whose non-daemon workers are joined at interpreter exit regardless, so wait=False
    # never shortened shutdown -- it only let the rest of teardown run underneath a
    # build that was still mutating the media server. Let in-flight builds finish.
    scheduler.scheduler_manager.scheduler.shutdown(wait=True)

app = FastAPI(title="MixerBee API", root_path=ROOT_PATH, lifespan=lifespan)

PUBLIC_API_PATHS = {'/api/auth/status', '/api/auth/setup', '/api/auth/login', '/api/status'}

@app.middleware("http")
async def enforce_accounts(request: Request, call_next):
    from starlette._utils import get_route_path
    path = get_route_path(request.scope)
    if path.startswith('/api/'):
        # A custom header + same-origin check protects pre-login requests too.
        if (request.method not in ('GET', 'HEAD', 'OPTIONS')
                and not path.startswith('/api/webhook')
                and not path.startswith('/api/external/')):
            origin = request.headers.get('origin')
            expected = f"{request.url.scheme}://{request.url.netloc}"
            if origin and origin != expected:
                return JSONResponse({'detail': 'Cross-origin request rejected.'}, status_code=403)
        if path not in PUBLIC_API_PATHS and not (path == '/api/webhook' or path.startswith('/api/webhook/')):
            session = accounts.read_session(request.cookies.get(accounts.cookie_name(request)))
            api_key = request.headers.get('x-mixerbee-key', '')
            external = None
            if path.startswith('/api/external/') and api_key:
                with database.get_db_connection() as conn:
                    external = conn.execute('SELECT id FROM media_connections WHERE api_key_hash=? AND owner_id IS NOT NULL',
                                            (accounts.token_hash(api_key),)).fetchone()
                if not external:
                    return JSONResponse({'detail': 'Invalid external API key.'}, status_code=401)
            if external:
                request.state.external_connection_id = external['id']
            else:
                if not session:
                    return JSONResponse({'detail': 'Sign in to MixerBee.'}, status_code=401)
                pinned_account = request.headers.get('x-mixerbee-account')
                if pinned_account and pinned_account != session['id']:
                    return JSONResponse({'detail': 'The signed-in account changed. Reload this page.'}, status_code=409)
                if request.method not in ('GET', 'HEAD', 'OPTIONS'):
                    if not secrets.compare_digest(request.headers.get('x-mixerbee-csrf', ''), session['csrf_token']):
                        return JSONResponse({'detail': 'Session changed. Reload this page.'}, status_code=409)
                request.state.account = session
        elif path in ('/api/auth/login', '/api/auth/setup'):
            if request.headers.get('x-mixerbee-request') != '1':
                return JSONResponse({'detail': 'Missing login request header.'}, status_code=403)
    response = await call_next(request)
    if path.startswith('/api/'):
        response.headers['Cache-Control'] = 'no-store'
    return response

HERE = Path(__file__).parent
app.mount("/static", StaticFiles(directory=HERE / "static"), name="static")
templates = Jinja2Templates(directory=str(HERE / "templates"))

app.include_router(account_routes.router)
app.include_router(config.router)
app.include_router(builder.router)
app.include_router(library.router)
app.include_router(assist_router.router)
app.include_router(quick_playlists.router)
app.include_router(scheduler_router.router)
app.include_router(presets.router)
app.include_router(webhooks.router)
@app.get("/api/status")
def health_status():
    return {"status": "ok"}
@app.get("/", response_class=HTMLResponse)
def index(request: Request):
    return templates.TemplateResponse(
    request=request, 
    name="index.html", 
)
