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

# Archive manifest versions this build can restore. create_backup_archive writes the
# newest one.
BACKUP_SCHEMA_VERSION = 2
SUPPORTED_BACKUP_SCHEMA_VERSIONS = {2}

# Tables a database must already contain to be recognized as a MixerBee database
# (migrations would otherwise create them empty and mask a wrong file).
IDENTIFYING_TABLES = ("accounts", "media_connections", "schedules", "settings")


def _validate_manifest(manifest: Any) -> None:
    if not isinstance(manifest, dict):
        raise ValueError("Archive is invalid: manifest.json is not an object.")
    version = manifest.get("schema_version")
    if isinstance(version, bool) or not isinstance(version, int):
        raise ValueError("Archive is invalid: manifest.json has no schema_version.")
    if version not in SUPPORTED_BACKUP_SCHEMA_VERSIONS:
        raise ValueError(
            f"Unsupported backup schema_version {version}; this MixerBee restores "
            f"{', '.join(map(str, sorted(SUPPORTED_BACKUP_SCHEMA_VERSIONS)))}."
        )


def _table_columns(conn: sqlite3.Connection, table: str) -> set:
    return {row[1] for row in conn.execute(f"PRAGMA table_info({table})")}


def _schema_of(conn: sqlite3.Connection) -> Dict[str, set]:
    tables = [row[0] for row in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")]
    return {table: _table_columns(conn, table) for table in tables}


def _expected_schema() -> Dict[str, set]:
    """Every table and column the current code creates, from a fresh in-memory database.

    Derived rather than hand-listed so it cannot drift from the initialize_schema
    functions. A staged backup must contain all of it after its own migrations run:
    migrations only add what is absent, so a table that exists with a column missing
    (or under a different shape) would otherwise slip through.
    """
    conn = sqlite3.connect(":memory:")
    try:
        conn.row_factory = sqlite3.Row
        database.initialize_schema(conn)
        return _schema_of(conn)
    finally:
        conn.close()


def _stage_database(db_path: Path) -> None:
    """Validate a staged database file and apply MixerBee's schema migrations to it.

    Raises ValueError if the file is not an intact, compatible MixerBee database.
    The file is modified in place, so only call this on a copy.
    """
    try:
        conn = sqlite3.connect(str(db_path))
    except sqlite3.Error as e:
        raise ValueError(f"Database within backup archive could not be opened: {e}") from None
    try:
        conn.row_factory = sqlite3.Row
        try:
            res = conn.execute("PRAGMA integrity_check").fetchone()
        except sqlite3.DatabaseError as e:
            raise ValueError(f"Database within backup archive is not a valid SQLite file: {e}") from None
        if not res or res[0] != "ok":
            raise ValueError("Database within backup archive failed integrity check.")

        tables = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        missing = [t for t in IDENTIFYING_TABLES if t not in tables]
        if missing:
            raise ValueError(f"Archive is not a MixerBee backup: missing table(s) {', '.join(missing)}.")

        try:
            database.initialize_schema(conn)
        except sqlite3.Error as e:
            raise ValueError(f"Backup database could not be migrated to the current schema: {e}") from None

        staged = _schema_of(conn)
        for table, columns in _expected_schema().items():
            absent = columns - staged.get(table, set())
            if absent:
                raise ValueError(f"Backup database table '{table}' is missing column(s): "
                                 f"{', '.join(sorted(absent))}.")

        # The scheduler parses these on reload; catch a malformed row at inspection.
        for row in conn.execute("SELECT id, config_data, last_run FROM schedules"):
            for field in ("config_data", "last_run"):
                if row[field]:
                    try:
                        json.loads(row[field])
                    except (TypeError, ValueError):
                        raise ValueError(f"Backup schedule {row['id']} has malformed {field}.") from None

        # Restoring a database without an owner would reopen first-owner setup to
        # anyone who reaches the UI.
        if not conn.execute("SELECT 1 FROM accounts WHERE is_admin=1 LIMIT 1").fetchone():
            raise ValueError("Backup database has no owner account.")
    finally:
        conn.close()


def _replace_dir(src: Path, dest: Path):
    """Make dest an exact copy of src, discarding whatever dest held before.

    copytree(dirs_exist_ok=True) merges: it overwrites the paths it finds in src and
    leaves everything else in place. For ChromaDB that means per-collection segment
    directories from the displaced index survive alongside a chroma.sqlite3 that has
    no rows for them -- a state the store was never in. Clearing dest first avoids it.
    """
    if dest.exists():
        shutil.rmtree(dest, ignore_errors=True)
    # dirs_exist_ok covers a partial rmtree (an open handle on Windows, say); the
    # merge fallback is still better than not copying at all.
    shutil.copytree(src, dest, dirs_exist_ok=True)


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
            "schema_version": BACKUP_SCHEMA_VERSION,
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
    Validates the manifest version, SQLite integrity, and the MixerBee schema
    (after additive migrations, applied to a scratch copy only).
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

            try:
                manifest = json.loads(zf.read("manifest.json").decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError):
                raise ValueError("Archive is invalid: manifest.json is not valid JSON.") from None
            _validate_manifest(manifest)

            # Validate and migrate a scratch copy: integrity, MixerBee tables, and
            # the columns the current code needs once additive migrations run.
            extracted_db = temp_dir / "mixerbee.db"
            with open(extracted_db, "wb") as f:
                f.write(zf.read("mixerbee.db"))
            _stage_database(extracted_db)

            has_chroma = any(n.startswith("chroma_db/") for n in names)

            return {
                "status": "ok",
                "valid": True,
                "manifest": manifest,
                "archive_size_bytes": archive_path.stat().st_size,
                "has_chromadb": has_chroma,
                "integrity_check": "ok",
                "schema_check": "ok"
            }
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)


def _reload_subsystems(strict: bool = True) -> None:
    import connections
    import scheduler
    database.init_db()
    connections.reload_connections()
    scheduler.scheduler_manager.reload_schedules(strict=strict)


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
    live_chroma_backup = None

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
        # Migrate the staged copy before anything live is touched.
        _stage_database(restored_db_path)

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
            # Replace rather than merge: dirs_exist_ok only overwrites paths present
            # in the source, so collection directories that exist solely in the live
            # index would survive next to a chroma.sqlite3 that no longer lists them.
            _replace_dir(extracted_chroma, live_chroma)
            # Memoized collection handles point at what was just overwritten.
            # NOTE: this drops the cached Collection objects only. vector_store's
            # chroma_client is a module-level PersistentClient created at import and
            # still holds an open connection to the chroma.sqlite3 we just replaced,
            # so AI search can keep serving the pre-restore index until a restart.
            # Rebuilding that client safely needs the warm/enrichment threads quiesced
            # first; until then, restarting after a restore is still advised.
            try:
                from app.ai.vector_store import drop_collection_cache
                drop_collection_cache()
            except Exception as cache_err:
                logger.warning("Could not drop vector collection cache: %s", cache_err)

        # 5. Reload connections and schedules in memory. A failure here leaves the
        # process out of step with the restored data, so it fails the restore and
        # rolls back rather than reporting success.
        _reload_subsystems()
        logger.info("MixerBee subsystems reloaded after restore.")

        return {
            "status": "ok",
            "message": "Configuration and data restored successfully.",
            "manifest": inspect_result.get("manifest")
        }

    except Exception as e:
        logger.error("Restore failed! Attempting rollback to pre-restore state: %s", e, exc_info=True)
        # The Chroma safety copy lives under temp_dir, which `finally` deletes -- roll
        # it back here, while it still exists. Previously it was taken and then thrown
        # away without ever being used, so a half-applied Chroma restore was permanent.
        if live_chroma_backup is not None and live_chroma_backup.is_dir():
            try:
                _replace_dir(live_chroma_backup, CONFIG_DIR / "chroma_db")
                try:
                    from app.ai.vector_store import drop_collection_cache
                    drop_collection_cache()
                except Exception:
                    pass
                logger.info("Rollback restored the previous ChromaDB directory.")
            except Exception as chroma_err:
                logger.critical("ChromaDB rollback failed! %s", chroma_err, exc_info=True)
        if pre_restore_backup.exists():
            try:
                with database.get_db_connection() as live_conn:
                    rollback_src = sqlite3.connect(str(pre_restore_backup))
                    rollback_src.backup(live_conn)
                    rollback_src.close()
                logger.info("Rollback restored previous database state.")
            except Exception as rollback_err:
                logger.critical("Rollback failed! %s", rollback_err, exc_info=True)
        # Connections/schedules may already have been reloaded from the restored data.
        try:
            _reload_subsystems(strict=False)
        except Exception as reload_err:
            logger.critical("Reload after rollback failed; restart MixerBee. %s", reload_err, exc_info=True)
        raise RuntimeError(f"Restore failed and was rolled back: {e}")

    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)
