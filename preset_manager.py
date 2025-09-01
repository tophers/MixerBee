"""
presets_manager.py – Manages presets.
"""
import json
import logging
from typing import Dict, List, Any

import database

class PresetManager:

    def get_all_presets(self) -> Dict[str, Any]:
        presets = {}
        try:
            conn = database.get_db_connection()
            rows = conn.execute("SELECT name, data FROM presets").fetchall()
            conn.close()

            for row in rows:
                presets[row['name']] = json.loads(row['data'])
            return presets
        except Exception as e:
            logging.error(f"PRESET_MGR: Error loading presets from database: {e}", exc_info=True)
            return {}

    def save_preset(self, preset_name: str, preset_data: List[Dict]) -> bool:
        if not preset_name or preset_name == "__autosave__":
            logging.warning(f"PRESET_MGR: Invalid preset name '{preset_name}' provided for saving.")
            return False
        
        try:
            conn = database.get_db_connection()
            data_json = json.dumps(preset_data)
            conn.execute(
                "INSERT OR REPLACE INTO presets (name, data) VALUES (?, ?)",
                (preset_name, data_json)
            )
            conn.commit()
            conn.close()
            return True
        except Exception as e:
            logging.error(f"PRESET_MGR: Error saving preset '{preset_name}' to database: {e}", exc_info=True)
            return False

    def delete_preset(self, preset_name: str) -> bool:
        try:
            conn = database.get_db_connection()
            cursor = conn.cursor()
            cursor.execute("DELETE FROM presets WHERE name = ?", (preset_name,))
            conn.commit()
            success = cursor.rowcount > 0 # Check if a row was actually deleted
            conn.close()
            return success
        except Exception as e:
            logging.error(f"PRESET_MGR: Error deleting preset '{preset_name}' from database: {e}", exc_info=True)
            return False


preset_manager = PresetManager()