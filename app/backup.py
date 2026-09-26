"""
app/backup.py - Configuration Backup and Restore subsystem.
Provides safe SQLite online backup, ChromaDB snapshot capture, archive inspection,
and staged restoration with rollback protection.
"""

import os
import json
import shutil
import sqlite3
import zipfile
import tempfile
from pathlib import Path
from datetime import datetime, timezone
from typing import Dict, Any, Optional

import database
from database import DB_PATH
from runtime_paths import CONFIG_DIR
from app.logger import get_logger

logger = get_logger("MixerBee.Backup")


def create_backup_archive(target_path: Optional[Path] = None) -> Path:
    """
    Creates a zip archive containing an online SQLite backup of mixerbee.db,
    ChromaDB vector collection snapshot, and manifest metadata.
    """
    logger.info("Starting configuration backup archive creation...")
    temp_dir = Path(tempfile.mkdtemp(prefix="mixerbee_backup_"))
    try:
        temp_db_path = temp_dir / "mixerbee_backup.db"

        # 1. Consistent database backup using SQLite's online backup API
        with database.get_db_connection() as src_conn:
            dest_conn = sqlite3.connect(str(temp_db_path))
            src_conn.backup(dest_conn)
            dest_conn.close()

        # 2. Extract database statistics for manifest
        check_conn = sqlite3.connect(str(temp_db_path))
        check_conn.row_factory = sqlite3.Row
        cur = check_conn.cursor()

        def table_count(tname: str) -> int:
            try:
                return cur.execute(f"SELECT COUNT(*) FROM {tname}").fetchone()[0]
            except Exception:
                return 0

        chroma_dir = CONFIG_DIR / "chroma_db"
        has_chromadb = chroma_dir.is_dir() and any(chroma_dir.iterdir())

        manifest = {
            "schema_version": 2,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "database_counts": {
                "accounts": table_count("accounts"),
                "connections": table_count("media_connections"),
                "presets": table_count("connection_presets"),
                "recipes": table_count("connection_recipes"),
                "schedules": table_count("schedules"),
                "build_runs": table_count("build_runs"),
            },
            "has_chromadb": has_chromadb,
            "warning": "Contains connection credentials, webhook secrets, and access keys. Keep this archive secure."
        }
        check_conn.close()

        # 3. Create zip archive
        if target_path:
            archive_path = target_path
            archive_path.parent.mkdir(parents=True, exist_ok=True)
        else:
            timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
            archive_path = temp_dir / f"mixerbee_backup_{timestamp}.zip"

        with zipfile.ZipFile(str(archive_path), "w", compression=zipfile.ZIP_DEFLATED) as zf:
            zf.writestr("manifest.json", json.dumps(manifest, indent=2))
            zf.write(temp_db_path, arcname="mixerbee.db")

            if has_chromadb:
                for root, _, files in os.walk(chroma_dir):
                    for file in files:
                        fp = Path(root) / file
                        rel = fp.relative_to(CONFIG_DIR)
                        zf.write(fp, arcname=str(rel))

        logger.info("Backup archive created successfully at %s (%d bytes)", archive_path, archive_path.stat().st_size)
        return archive_path

    finally:
        # Clean up temporary database copy if we used a separate output path
        if temp_db_path.exists():
            try:
                temp_db_path.unlink()
            except Exception:
                pass


def inspect_backup_archive(archive_path: Path) -> Dict[str, Any]:
    """
    Inspects a backup zip archive without restoring it.
    Validates manifest and checks SQLite integrity.
    """
    if not archive_path.exists():
        raise FileNotFoundError(f"Backup archive not found: {archive_path}")

    temp_dir = Path(tempfile.mkdtemp(prefix="mixerbee_inspect_"))
    try:
        with zipfile.ZipFile(str(archive_path), "r") as zf:
            names = zf.namelist()
            if "manifest.json" not in names:
                raise ValueError("Archive is invalid: missing manifest.json.")
            if "mixerbee.db" not in names:
                raise ValueError("Archive is invalid: missing mixerbee.db.")

            manifest_raw = zf.read("manifest.json").decode("utf-8")
            manifest = json.loads(manifest_raw)

            # Extract database to check integrity
            extracted_db = temp_dir / "mixerbee.db"
            with open(extracted_db, "wb") as f:
                f.write(zf.read("mixerbee.db"))

            # Run SQLite integrity check
            conn = sqlite3.connect(str(extracted_db))
            res = conn.execute("PRAGMA integrity_check").fetchone()
            integrity_ok = res and res[0] == "ok"
            conn.close()

            if not integrity_ok:
                raise ValueError("Database within backup archive failed integrity check.")

            has_chroma = any(n.startswith("chroma_db/") for n in names)

            return {
                "status": "ok",
                "valid": True,
                "manifest": manifest,
                "archive_size_bytes": archive_path.stat().st_size,
                "has_chromadb": has_chroma,
                "integrity_check": "ok"
            }
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)


def restore_backup_archive(archive_path: Path) -> Dict[str, Any]:
    """
    Safely restores database and ChromaDB collections from a backup archive.
    Performs inspection and creates a pre-restore rollback backup first.
    """
    logger.info("Initiating configuration restore from %s", archive_path)
    inspect_result = inspect_backup_archive(archive_path)
    if not inspect_result.get("valid"):
        raise ValueError("Cannot restore: Archive inspection failed.")

    temp_dir = Path(tempfile.mkdtemp(prefix="mixerbee_restore_"))
    pre_restore_backup = temp_dir / "mixerbee_pre_restore.db"

    try:
        # 1. Create safety rollback backup of live DB
        with database.get_db_connection() as live_conn:
            rollback_dest = sqlite3.connect(str(pre_restore_backup))
            live_conn.backup(rollback_dest)
            rollback_dest.close()

        # 2. Extract archive contents to temporary folder
        with zipfile.ZipFile(str(archive_path), "r") as zf:
            zf.extractall(temp_dir)

        restored_db_path = temp_dir / "mixerbee.db"
        if not restored_db_path.exists():
            raise ValueError("Extracted archive did not contain mixerbee.db.")

        # 3. Restore SQLite database in-place via online backup
        with database.get_db_connection() as live_conn:
            restore_src = sqlite3.connect(str(restored_db_path))
            restore_src.backup(live_conn)
            restore_src.close()

        # 4. Restore ChromaDB if present in archive
        extracted_chroma = temp_dir / "chroma_db"
        live_chroma = CONFIG_DIR / "chroma_db"
        if extracted_chroma.is_dir():
            logger.info("Restoring ChromaDB directory...")
            if live_chroma.exists():
                live_chroma_backup = temp_dir / "chroma_db_live_backup"
                shutil.copytree(live_chroma, live_chroma_backup, dirs_exist_ok=True)
            shutil.copytree(extracted_chroma, live_chroma, dirs_exist_ok=True)

        # 5. Reload connections and schedules in memory
        try:
            import connections
            import scheduler
            database.init_db()
            connections.reload_connections()
            scheduler.scheduler_manager._load_schedules()
            logger.info("MixerBee subsystems reloaded after restore.")
        except Exception as reload_err:
            logger.warning("Subsystems reload notification: %s", reload_err)

        return {
            "status": "ok",
            "message": "Configuration and data restored successfully.",
            "manifest": inspect_result.get("manifest")
        }

    except Exception as e:
        logger.error("Restore failed! Attempting rollback to pre-restore state: %s", e, exc_info=True)
        if pre_restore_backup.exists():
            try:
                with database.get_db_connection() as live_conn:
                    rollback_src = sqlite3.connect(str(pre_restore_backup))
                    rollback_src.backup(live_conn)
                    rollback_src.close()
                logger.info("Rollback restored previous database state.")
            except Exception as rollback_err:
                logger.critical("Rollback failed! %s", rollback_err, exc_info=True)
        raise RuntimeError(f"Restore failed and was rolled back: {e}")

    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)
