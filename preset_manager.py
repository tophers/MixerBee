"""
presets_manager.py – Manages presets with per-item error handling
"""

import json
import logging
from typing import Dict, List, Any

import database

class PresetManager:

    def get_all_presets(self) -> Dict[str, Any]:
        presets = {}
        try:
            with database.get_db_connection() as conn:
                rows = conn.execute("SELECT name, data FROM presets").fetchall()
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

    def save_preset(self, preset_name: str, preset_data: List[Dict]) -> bool:
        if not preset_name or preset_name == "__autosave__":
            logging.warning(f"PRESET_MGR: Invalid preset name '{preset_name}' provided for saving.")
            return False

        try:
            with database.get_db_connection() as conn:
                data_json = json.dumps(preset_data)
                conn.execute(
                    "INSERT OR REPLACE INTO presets (name, data) VALUES (?, ?)",
                    (preset_name, data_json)
                )
                conn.commit()
            return True
        except Exception as e:
            logging.error(f"PRESET_MGR: Error saving preset '{preset_name}' to database: {e}", exc_info=True)
            return False

    def delete_preset(self, preset_name: str) -> bool:
        try:
            with database.get_db_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("DELETE FROM presets WHERE name = ?", (preset_name,))
                conn.commit()
                success = cursor.rowcount > 0
            return success
        except Exception as e:
            logging.error(f"PRESET_MGR: Error deleting preset '{preset_name}' from database: {e}", exc_info=True)
            return False

preset_manager = PresetManager()