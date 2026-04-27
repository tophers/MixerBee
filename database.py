"""
database.py – Manages database connections
"""

import os
import json
import logging
import sqlite3
from pathlib import Path
from contextlib import contextmanager

from app_state import CONFIG_DIR

DB_PATH = CONFIG_DIR / "mixerbee.db"

@contextmanager
def get_db_connection():
    """Yields a database connection and guarantees it is closed afterward."""
    conn = sqlite3.connect(DB_PATH, check_same_thread=False, timeout=10.0)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
    finally:
        conn.close()

def init_db():
    """Initializes the database, creating tables and running migrations if needed."""
    with get_db_connection() as conn:
        cursor = conn.cursor()

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS presets (
                name TEXT PRIMARY KEY,
                data TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS schedules (
                id TEXT PRIMARY KEY,
                playlist_name TEXT NOT NULL,
                user_id TEXT NOT NULL,
                job_type TEXT NOT NULL,
                crontab TEXT NOT NULL,
                config_data TEXT,
                last_run TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS settings (
                key TEXT PRIMARY KEY,
                value TEXT,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        
        conn.commit()
