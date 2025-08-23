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
import database # Import the new database module
from routers import config, builder, library, quick_playlists, presets
from routers import scheduler as scheduler_router


IS_DOCKER = os.path.exists('/.dockerenv')
ROOT_PATH = "" if IS_DOCKER else "/mixerbee"

app = FastAPI(title="MixerBee API", root_path=ROOT_PATH)
HERE = Path(__file__).parent

# Mount static files
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
    """Initialize DB, load config, and start the scheduler on application startup."""
    database.init_db() # Initialize the database and run migrations
    app_state.load_and_authenticate()
    scheduler.scheduler_manager.start()

@app.on_event("shutdown")
def shutdown_event():
    """Shutdown the scheduler gracefully."""
    scheduler.scheduler_manager.scheduler.shutdown()


# --- Main HTML Endpoint ---
@app.get("/", response_class=HTMLResponse)
def index():
    """Serves the main index.html file."""
    return (HERE / "templates" / "index.html").read_text()
