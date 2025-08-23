# database.py
import os
import json
import logging
import sqlite3
from pathlib import Path

# Import the single source of truth for paths
from app_state import CONFIG_DIR

DB_PATH = CONFIG_DIR / "mixerbee.db"
PRESETS_JSON_PATH = CONFIG_DIR / "presets.json"
SCHEDULES_JSON_PATH = CONFIG_DIR / "schedules.json"

# The .migrated files might exist from previous attempts
PRESETS_MIGRATED_PATH = CONFIG_DIR / "presets.json.migrated"
SCHEDULES_MIGRATED_PATH = CONFIG_DIR / "schedules.json.migrated"


def get_db_connection():
    """Returns a new database connection object."""
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn

def _migrate_presets(conn):
    """Migrates data from presets.json to the database."""
    source_path = PRESETS_JSON_PATH if PRESETS_JSON_PATH.exists() else PRESETS_MIGRATED_PATH
    if not source_path.exists():
        return

    logging.info(f"Found {source_path.name}, attempting one-time migration to database...")
    try:
        with open(source_path, 'r') as f:
            presets_data = json.load(f)

        if not isinstance(presets_data, dict):
            logging.warning(f"{source_path.name} is not a valid dictionary. Skipping migration.")
            os.rename(source_path, str(source_path) + '.invalid')
            return

        cursor = conn.cursor()
        for name, data in presets_data.items():
            data_json = json.dumps(data)
            cursor.execute(
                "INSERT OR REPLACE INTO presets (name, data) VALUES (?, ?)",
                (name, data_json)
            )
        conn.commit()

        final_migrated_name = str(PRESETS_JSON_PATH) + '.migrated'
        if os.path.exists(final_migrated_name): # Clean up old .migrated if it exists
             if source_path != final_migrated_name: os.remove(final_migrated_name)
        os.rename(source_path, final_migrated_name)
        logging.info(f"Successfully migrated {len(presets_data)} presets. Final migrated file is {final_migrated_name}.")

    except Exception as e:
        logging.error(f"Error migrating presets data: {e}", exc_info=True)


def _migrate_schedules(conn):
    """Migrates data from schedules.json to the database."""
    source_path = SCHEDULES_JSON_PATH if SCHEDULES_JSON_PATH.exists() else SCHEDULES_MIGRATED_PATH
    if not source_path.exists():
        return

    logging.info(f"Found {source_path.name}, attempting one-time migration to database...")
    try:
        schedules_data = json.loads(source_path.read_text())
        if not isinstance(schedules_data, dict):
            logging.warning(f"{source_path.name} is not a valid dictionary. Skipping migration.")
            os.rename(source_path, str(source_path) + '.invalid')
            return

        cursor = conn.cursor()
        for schedule_id, data in schedules_data.items():
            config_payload = {
                "preset_name": data.get("preset_name"),
                "blocks": data.get("blocks"),
                "quick_playlist_data": data.get("quick_playlist_data"),
                "schedule_details": data.get("schedule_details")
            }
            cursor.execute(
                """
                INSERT OR REPLACE INTO schedules 
                (id, playlist_name, user_id, job_type, crontab, config_data, last_run)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    schedule_id, data.get("playlist_name"), data.get("user_id"),
                    data.get("job_type"), data.get("crontab"),
                    json.dumps(config_payload), json.dumps(data.get("last_run"))
                )
            )
        conn.commit()
        
        final_migrated_name = str(SCHEDULES_JSON_PATH) + '.migrated'
        if os.path.exists(final_migrated_name):
             if source_path != final_migrated_name: os.remove(final_migrated_name)
        os.rename(source_path, final_migrated_name)
        logging.info(f"Successfully migrated {len(schedules_data)} schedules. Final migrated file is {final_migrated_name}.")
        
    except Exception as e:
        logging.error(f"Error migrating schedules data: {e}", exc_info=True)


def init_db():
    """Initializes the database, creating tables and running migrations if needed."""
    conn = get_db_connection()
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
    conn.commit()

    _migrate_presets(conn)
    _migrate_schedules(conn)

    conn.close()