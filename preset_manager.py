"""
presets_manager.py – Manages presets with per-item error handling
"""

import json
import logging
import uuid
from typing import Dict, List, Any

import database

class PresetManager:

    def get_preset_records(self, connection_id: str) -> List[Dict[str, Any]]:
        """Return stable preset identities and decoded data for one connection."""
        records = []
        try:
            with database.get_db_connection() as conn:
                rows = conn.execute(
                    "SELECT id, name, data FROM connection_presets WHERE connection_id=? ORDER BY name COLLATE NOCASE",
                    (connection_id,)
                ).fetchall()
            for row in rows:
                try:
                    records.append({'id': row['id'], 'name': row['name'], 'data': json.loads(row['data'])})
                except json.JSONDecodeError as exc:
                    logging.error("PRESET_MGR: Skipping corrupted preset '%s': %s", row['name'], exc)
        except Exception as exc:
            logging.error("PRESET_MGR: Error loading preset records: %s", exc, exc_info=True)
        return records

    def get_preset_by_id(self, preset_id: str, connection_id: str):
        if not preset_id:
            return None
        with database.get_db_connection() as conn:
            row = conn.execute(
                "SELECT id, name, data FROM connection_presets WHERE id=? AND connection_id=?",
                (preset_id, connection_id)
            ).fetchone()
        if not row:
            return None
        try:
            return {'id': row['id'], 'name': row['name'], 'data': json.loads(row['data'])}
        except json.JSONDecodeError:
            logging.error("PRESET_MGR: Preset '%s' contains invalid JSON.", row['name'])
            return None

    def get_preset_by_name(self, preset_name: str, connection_id: str):
        if not preset_name:
            return None
        with database.get_db_connection() as conn:
            row = conn.execute(
                "SELECT id, name, data FROM connection_presets WHERE name=? AND connection_id=?",
                (preset_name, connection_id)
            ).fetchone()
        if not row:
            return None
        try:
            return {'id': row['id'], 'name': row['name'], 'data': json.loads(row['data'])}
        except json.JSONDecodeError:
            logging.error("PRESET_MGR: Preset '%s' contains invalid JSON.", row['name'])
            return None

    def get_all_presets(self, connection_id: str) -> Dict[str, Any]:
        presets = {}
        try:
            with database.get_db_connection() as conn:
                rows = conn.execute("SELECT name, data FROM connection_presets WHERE connection_id = ?", (connection_id,)).fetchall()
                for row in rows:
                    name = row['name']
                    data_raw = row['data']
                    try:
                        presets[name] = json.loads(data_raw)
                    except json.JSONDecodeError as json_err:
                        logging.error(f"PRESET_MGR: Skipping corrupted preset '{name}'. Invalid JSON: {json_err}")
                    except Exception as e:
                        logging.error(f"PRESET_MGR: Unexpected error loading preset '{name}': {e}")
            return presets
        except Exception as e:
            logging.error(f"PRESET_MGR: Error loading presets from database: {e}", exc_info=True)
            return {}

    def save_preset(self, preset_name: str, preset_data: List[Dict], connection_id: str):
        if not preset_name or preset_name == "__autosave__":
            logging.warning(f"PRESET_MGR: Invalid preset name '{preset_name}' provided for saving.")
            return False

        try:
            with database.get_db_connection() as conn:
                data_json = json.dumps(preset_data)
                candidate_id = uuid.uuid4().hex
                conn.execute(
                    "INSERT INTO connection_presets (id, connection_id, name, data) VALUES (?, ?, ?, ?) "
                    "ON CONFLICT(connection_id, name) DO UPDATE SET data=excluded.data",
                    (candidate_id, connection_id, preset_name, data_json)
                )
                preset_id = conn.execute(
                    "SELECT id FROM connection_presets WHERE connection_id=? AND name=?",
                    (connection_id, preset_name)
                ).fetchone()['id']
                conn.commit()
            return preset_id
        except Exception as e:
            logging.error(f"PRESET_MGR: Error saving preset '{preset_name}' to database: {e}", exc_info=True)
            return False

    def schedule_usage_count(self, preset_id: str, connection_id: str) -> int:
        with database.get_db_connection() as conn:
            return conn.execute(
                "SELECT COUNT(*) FROM schedules WHERE preset_id=? AND connection_id=?",
                (preset_id, connection_id)
            ).fetchone()[0]

    def delete_preset(self, preset_name: str, connection_id: str) -> bool:
        try:
            with database.get_db_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("DELETE FROM connection_presets WHERE name = ? AND connection_id = ?", (preset_name, connection_id))
                conn.commit()
                success = cursor.rowcount > 0
            return success
        except Exception as e:
            logging.error(f"PRESET_MGR: Error deleting preset '{preset_name}' from database: {e}", exc_info=True)
            return False

    def delete_preset_by_id(self, preset_id: str, connection_id: str) -> bool:
        try:
            with database.get_db_connection() as conn:
                cursor = conn.execute(
                    "DELETE FROM connection_presets WHERE id=? AND connection_id=?",
                    (preset_id, connection_id)
                )
                conn.commit()
                return cursor.rowcount > 0
        except Exception as exc:
            logging.error("PRESET_MGR: Error deleting preset ID '%s': %s", preset_id, exc, exc_info=True)
            return False

preset_manager = PresetManager()
