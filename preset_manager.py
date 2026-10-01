"""
presets_manager.py – Manages presets with envelope support, tags, favorites, and recipes.
"""

import json
import uuid
from datetime import datetime, timezone
from typing import Dict, List, Any, Optional, Tuple

import database

from app.logger import get_logger

logger = get_logger("MixerBee.PresetStore")


def _unpack_preset_data(data_raw: str) -> Tuple[List[Dict[str, Any]], Dict[str, Any], int]:
    parsed = json.loads(data_raw)
    if isinstance(parsed, dict) and "blocks" in parsed:
        return parsed.get("blocks", []), parsed.get("mix_options", {}), parsed.get("schema_version", 1)
    if isinstance(parsed, list):
        return parsed, {}, 1
    return [], {}, 1


class PresetManager:

    def get_preset_records(self, connection_id: str) -> List[Dict[str, Any]]:
        """Return stable preset identities and decoded data for one connection."""
        records = []
        try:
            with database.get_db_connection() as conn:
                rows = conn.execute(
                    "SELECT id, name, data, tags_json, is_favorite FROM connection_presets WHERE connection_id=? ORDER BY name COLLATE NOCASE",
                    (connection_id,)
                ).fetchall()
            for row in rows:
                try:
                    blocks, mix_options, schema_ver = _unpack_preset_data(row['data'])
                    tags = json.loads(row['tags_json']) if row['tags_json'] else []
                    records.append({
                        'id': row['id'],
                        'name': row['name'],
                        'data': blocks,
                        'mix_options': mix_options,
                        'schema_version': schema_ver,
                        'tags': tags,
                        'is_favorite': bool(row['is_favorite'])
                    })
                except json.JSONDecodeError as exc:
                    logger.error("PRESET_MGR: Skipping corrupted preset '%s': %s", row['name'], exc)
        except Exception as exc:
            logger.error("PRESET_MGR: Error loading preset records: %s", exc, exc_info=True)
        return records

    def get_preset_by_id(self, preset_id: str, connection_id: str):
        if not preset_id:
            return None
        with database.get_db_connection() as conn:
            row = conn.execute(
                "SELECT id, name, data, tags_json, is_favorite FROM connection_presets WHERE id=? AND connection_id=?",
                (preset_id, connection_id)
            ).fetchone()
        if not row:
            return None
        try:
            blocks, mix_options, schema_ver = _unpack_preset_data(row['data'])
            tags = json.loads(row['tags_json']) if row['tags_json'] else []
            return {
                'id': row['id'],
                'name': row['name'],
                'data': blocks,
                'mix_options': mix_options,
                'schema_version': schema_ver,
                'tags': tags,
                'is_favorite': bool(row['is_favorite'])
            }
        except json.JSONDecodeError:
            logger.error("PRESET_MGR: Preset '%s' contains invalid JSON.", row['name'])
            return None

    def get_preset_by_name(self, preset_name: str, connection_id: str):
        if not preset_name:
            return None
        with database.get_db_connection() as conn:
            row = conn.execute(
                "SELECT id, name, data, tags_json, is_favorite FROM connection_presets WHERE name=? AND connection_id=?",
                (preset_name, connection_id)
            ).fetchone()
        if not row:
            return None
        try:
            blocks, mix_options, schema_ver = _unpack_preset_data(row['data'])
            tags = json.loads(row['tags_json']) if row['tags_json'] else []
            return {
                'id': row['id'],
                'name': row['name'],
                'data': blocks,
                'mix_options': mix_options,
                'schema_version': schema_ver,
                'tags': tags,
                'is_favorite': bool(row['is_favorite'])
            }
        except json.JSONDecodeError:
            logger.error("PRESET_MGR: Preset '%s' contains invalid JSON.", row['name'])
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
                        blocks, _, _ = _unpack_preset_data(data_raw)
                        presets[name] = blocks
                    except json.JSONDecodeError as json_err:
                        logger.error(f"PRESET_MGR: Skipping corrupted preset '{name}'. Invalid JSON: {json_err}")
                    except Exception as e:
                        logger.error(f"PRESET_MGR: Unexpected error loading preset '{name}': {e}")
            return presets
        except Exception as e:
            logger.error(f"PRESET_MGR: Error loading presets from database: {e}", exc_info=True)
            return {}

    def save_preset(
        self,
        preset_name: str,
        preset_data: Any,
        connection_id: str,
        mix_options: Optional[Dict[str, Any]] = None,
        tags: Optional[List[str]] = None,
        is_favorite: Optional[bool] = None
    ):
        if not preset_name or preset_name == "__autosave__":
            logger.warning(f"PRESET_MGR: Invalid preset name '{preset_name}' provided for saving.")
            return False

        try:
            if isinstance(preset_data, dict) and "blocks" in preset_data:
                blocks = preset_data["blocks"]
                opt = mix_options or preset_data.get("mix_options", {})
            else:
                blocks = preset_data if isinstance(preset_data, list) else []
                opt = mix_options or {}

            envelope = {
                "schema_version": 1,
                "blocks": blocks,
                "mix_options": opt
            }
            data_json = json.dumps(envelope)

            with database.get_db_connection() as conn:
                candidate_id = uuid.uuid4().hex
                tags_json = json.dumps(tags) if tags is not None else "[]"
                fav_val = 1 if is_favorite else 0

                conn.execute(
                    "INSERT INTO connection_presets (id, connection_id, name, data, tags_json, is_favorite) VALUES (?, ?, ?, ?, ?, ?) "
                    "ON CONFLICT(connection_id, name) DO UPDATE SET data=excluded.data",
                    (candidate_id, connection_id, preset_name, data_json, tags_json, fav_val)
                )
                preset_id = conn.execute(
                    "SELECT id FROM connection_presets WHERE connection_id=? AND name=?",
                    (connection_id, preset_name)
                ).fetchone()['id']
                conn.commit()
            return preset_id
        except Exception as e:
            logger.error(f"PRESET_MGR: Error saving preset '{preset_name}' to database: {e}", exc_info=True)
            return False

    def rename_preset(self, preset_id: str, connection_id: str, new_name: str) -> bool:
        if not preset_id or not new_name or not new_name.strip():
            return False
        try:
            with database.get_db_connection() as conn:
                cursor = conn.execute(
                    "UPDATE connection_presets SET name=? WHERE id=? AND connection_id=?",
                    (new_name.strip(), preset_id, connection_id)
                )
                conn.commit()
                return cursor.rowcount > 0
        except Exception as e:
            logger.error(f"PRESET_MGR: Error renaming preset {preset_id}: {e}", exc_info=True)
            return False

    def update_preset_metadata(
        self,
        preset_id: str,
        connection_id: str,
        tags: Optional[List[str]] = None,
        is_favorite: Optional[bool] = None
    ) -> bool:
        try:
            with database.get_db_connection() as conn:
                updates = []
                params = []
                if tags is not None:
                    updates.append("tags_json=?")
                    params.append(json.dumps(tags))
                if is_favorite is not None:
                    updates.append("is_favorite=?")
                    params.append(1 if is_favorite else 0)
                if not updates:
                    return True
                params.extend([preset_id, connection_id])
                cursor = conn.execute(
                    f"UPDATE connection_presets SET {', '.join(updates)} WHERE id=? AND connection_id=?",
                    tuple(params)
                )
                conn.commit()
                return cursor.rowcount > 0
        except Exception as e:
            logger.error(f"PRESET_MGR: Error updating metadata for {preset_id}: {e}", exc_info=True)
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
            logger.error(f"PRESET_MGR: Error deleting preset '{preset_name}' from database: {e}", exc_info=True)
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
            logger.error("PRESET_MGR: Error deleting preset ID '%s': %s", preset_id, exc, exc_info=True)
            return False

    def list_recipes(
        self,
        connection_id: str,
        query: Optional[str] = None,
        tag: Optional[str] = None,
        favorites_only: bool = False
    ) -> List[Dict[str, Any]]:
        try:
            with database.get_db_connection() as conn:
                rows = conn.execute(
                    "SELECT id, name, description, block_json, tags_json, is_favorite, created_at, updated_at "
                    "FROM connection_recipes WHERE connection_id=? ORDER BY name COLLATE NOCASE",
                    (connection_id,)
                ).fetchall()
                results = []
                for r in rows:
                    rec = dict(r)
                    try:
                        rec["block"] = json.loads(rec["block_json"])
                        rec["tags"] = json.loads(rec["tags_json"])
                    except Exception:
                        rec["block"] = {}
                        rec["tags"] = []
                    rec["is_favorite"] = bool(rec["is_favorite"])

                    if query and query.strip().lower() not in rec["name"].lower() and query.strip().lower() not in rec["description"].lower():
                        continue
                    if tag and tag.lower() not in [t.lower() for t in rec["tags"]]:
                        continue
                    if favorites_only and not rec["is_favorite"]:
                        continue

                    results.append(rec)
                return results
        except Exception as e:
            logger.error(f"PRESET_MGR: Error listing recipes: {e}", exc_info=True)
            return []

    def save_recipe(
        self,
        connection_id: str,
        name: str,
        block_def: Dict[str, Any],
        description: str = "",
        tags: Optional[List[str]] = None,
        is_favorite: bool = False,
        recipe_id: Optional[str] = None
    ) -> Optional[str]:
        rid = recipe_id or uuid.uuid4().hex
        tags_json = json.dumps(tags or [])
        block_json = json.dumps(block_def)
        fav_val = 1 if is_favorite else 0
        now = datetime.now(timezone.utc).isoformat()
        try:
            with database.get_db_connection() as conn:
                conn.execute(
                    """
                    INSERT INTO connection_recipes (id, connection_id, name, description, block_json, tags_json, is_favorite, created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(id) DO UPDATE SET
                        name=excluded.name, description=excluded.description,
                        block_json=excluded.block_json, tags_json=excluded.tags_json,
                        is_favorite=excluded.is_favorite, updated_at=excluded.updated_at
                    """,
                    (rid, connection_id, name, description, block_json, tags_json, fav_val, now, now)
                )
                conn.commit()
            return rid
        except Exception as e:
            logger.error(f"PRESET_MGR: Error saving recipe: {e}", exc_info=True)
            return None

    def delete_recipe(self, recipe_id: str, connection_id: str) -> bool:
        try:
            with database.get_db_connection() as conn:
                cursor = conn.execute(
                    "DELETE FROM connection_recipes WHERE id=? AND connection_id=?",
                    (recipe_id, connection_id)
                )
                conn.commit()
                return cursor.rowcount > 0
        except Exception as e:
            logger.error(f"PRESET_MGR: Error deleting recipe {recipe_id}: {e}", exc_info=True)
            return False


preset_manager = PresetManager()
