"""
web.py – FastAPI wrapper for MixerBee.
"""

import os
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

import threading
from app.ai.vector_store import index_library_for_vibes

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

app = FastAPI(title="MixerBee API", root_path=ROOT_PATH)
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

@app.on_event("startup")
def startup_event():
    database.init_db()
    app_state.load_and_authenticate()
    if app_state.is_configured:
        auth_details = {
            "token": app_state.token,
            "login_uid": app_state.login_uid
        }
        refresh_cache(auth_details)

        if app_state.GEMINI_API_KEY:
            threading.Thread(
                target=index_library_for_vibes,
                args=(app_state.DEFAULT_UID, app_state.HDR),
                daemon=True
            ).start()

    scheduler.scheduler_manager.start()

@app.on_event("shutdown")
def shutdown_event():
    scheduler.scheduler_manager.scheduler.shutdown()

@app.get("/", response_class=HTMLResponse)
def index(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})
