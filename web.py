#!/usr/bin/env python3
"""
web.py – FastAPI wrapper for MixerBee.
"""
import os
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles

import scheduler
import app_state
import database
from app.cache import refresh_cache 
from routers import config, builder, library, quick_playlists, presets
from routers import scheduler as scheduler_router

IS_DOCKER = os.path.exists('/.dockerenv')
ROOT_PATH = "" if IS_DOCKER else "/mixerbee"

app = FastAPI(title="MixerBee API", root_path=ROOT_PATH)
HERE = Path(__file__).parent

app.mount("/static", StaticFiles(directory=HERE / "static"), name="static")

# Include all the API routers
app.include_router(config.router)
app.include_router(builder.router)
app.include_router(library.router)
app.include_router(quick_playlists.router)
app.include_router(scheduler_router.router)
app.include_router(presets.router)


# --- Startup and Shutdown ---
@app.on_event("startup")
def startup_event():
    database.init_db()
    app_state.load_and_authenticate()
    # Perform the initial, blocking cache population before starting the scheduler.
    # This ensures the cache is ready before any requests can be served.
    if app_state.is_configured:
        auth_details = {
            "token": app_state.token,
            "login_uid": app_state.login_uid
        }
        refresh_cache(auth_details)
    scheduler.scheduler_manager.start()

@app.on_event("shutdown")
def shutdown_event():
    scheduler.scheduler_manager.scheduler.shutdown()

@app.get("/", response_class=HTMLResponse)
def index():
    return (HERE / "templates" / "index.html").read_text()
