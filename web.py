"""
web.py – FastAPI wrapper
"""

import os
import secrets
from pathlib import Path
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

import threading
from app.ai.vector_store import index_library_for_vibes, ensure_cosine_similarity

import scheduler
import app_state
import database
from app.cache import refresh_cache
from routers import config, builder, library, quick_playlists, presets
from routers import scheduler as scheduler_router
from routers import webhooks

IS_CONTAINER = os.path.exists('/.dockerenv') or os.path.exists('/run/.containerenv')

ROOT_PATH = os.getenv("MIXERBEE_ROOT_PATH")
if ROOT_PATH is None:
    ROOT_PATH = "" if IS_CONTAINER else "/mixerbee"

@asynccontextmanager
async def lifespan(app: FastAPI):
    database.init_db()
    app_state.load_and_authenticate()

    if app_state.is_configured:
        ensure_cosine_similarity()

        auth_details = {
            "token": app_state.token,
            "login_uid": app_state.login_uid
        }
        refresh_cache(auth_details)

        ai_enabled = bool(app_state.GEMINI_API_KEY) or (app_state.AI_PROVIDER == "ollama")
        
        if ai_enabled:
            threading.Thread(
                target=index_library_for_vibes,
                args=(app_state.DEFAULT_UID, app_state.HDR),
                daemon=True
            ).start()

    scheduler.scheduler_manager.start()

    yield

    scheduler.scheduler_manager.scheduler.shutdown()

app = FastAPI(title="MixerBee API", root_path=ROOT_PATH, lifespan=lifespan)

# Paths that stay reachable without X-MixerBee-Key:
#  - /api/webhook: Emby/Jellyfin notification plugins can't send custom headers. It has its
#    own separate, opt-in secret (see routers/webhooks.py) checked via a URL query param instead.
#  - /api/status, /api/config_status: no secrets, used for pre-auth health/bootstrap checks.
GATE_EXEMPT_PATHS = {"/api/webhook", "/api/status", "/api/config_status"}

@app.middleware("http")
async def enforce_access_key(request: Request, call_next):
    # Opt-in: MixerBee stays open on the LAN (today's behavior) until the admin sets an
    # Access Key from Settings. Once set, everything below requires it.
    if not app_state.ACCESS_KEY:
        return await call_next(request)

    path = request.url.path
    if request.method == "OPTIONS" or not path.startswith("/api/") or path in GATE_EXEMPT_PATHS:
        return await call_next(request)

    supplied = request.headers.get("x-mixerbee-key", "")
    candidates = [k for k in (app_state.ACCESS_KEY, app_state.EXTERNAL_API_KEY) if k]
    if not supplied or not any(secrets.compare_digest(supplied, k) for k in candidates):
        return JSONResponse(status_code=401, content={"detail": "Missing or invalid X-MixerBee-Key header."})

    return await call_next(request)

HERE = Path(__file__).parent
app.mount("/static", StaticFiles(directory=HERE / "static"), name="static")
templates = Jinja2Templates(directory=str(HERE / "templates"))

app.include_router(config.router)
app.include_router(builder.router)
app.include_router(library.router)
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
