#!/usr/bin/env python
import json
import logging
import os
from pathlib import Path
from typing import Dict, List, Any
import threading

# --- Path Resolution (mirrors scheduler.py and app_state.py) ---
IS_DOCKER = os.path.exists('/.dockerenv')
HERE = Path(__file__).parent

if IS_DOCKER:
    CONFIG_DIR = Path("/config")
else:
    CONFIG_DIR = HERE / "config"

CONFIG_DIR.mkdir(parents=True, exist_ok=True)

PRESETS_FILE = CONFIG_DIR / "presets.json"
_presets_lock = threading.Lock()


class PresetManager:
    """Handles loading and saving of presets to a JSON file."""

    def __init__(self):
        self.presets = self._load_presets()

    def _load_presets(self) -> Dict[str, Any]:
        """Loads presets from the JSON file."""
        with _presets_lock:
            if not PRESETS_FILE.exists():
                return {}
            try:
                with open(PRESETS_FILE, 'r') as f:
                    presets_data = json.load(f)
                    return presets_data if isinstance(presets_data, dict) else {}
            except (json.JSONDecodeError, IOError) as e:
                logging.error(f"PRESET_MGR: Error loading presets file: {e}. Starting fresh.")
                return {}

    def _save_presets(self):
        """Saves the current presets to the JSON file."""
        with _presets_lock:
            try:
                with open(PRESETS_FILE, 'w') as f:
                    json.dump(self.presets, f, indent=4)
            except IOError as e:
                logging.error(f"PRESET_MGR: Error saving presets file: {e}")

    def get_all_presets(self) -> Dict[str, Any]:
        """Returns a dictionary of all presets."""
        # We reload from disk each time to ensure consistency across multiple workers/reloads
        return self._load_presets()

    def save_preset(self, preset_name: str, preset_data: List[Dict]) -> bool:
        """Saves a single preset and writes to the file."""
        if not preset_name or preset_name == "__autosave__":
            logging.warning(f"PRESET_MGR: Invalid preset name '{preset_name}' provided for saving.")
            return False
        
        self.presets = self._load_presets()
        self.presets[preset_name] = preset_data
        self._save_presets()
        return True

    def delete_preset(self, preset_name: str) -> bool:
        """Deletes a single preset and writes to the file."""
        self.presets = self._load_presets()
        if preset_name in self.presets:
            del self.presets[preset_name]
            self._save_presets()
            return True
        return False


preset_manager = PresetManager()