"""
app/build_history.py - Exact-row build history repository and recording boundaries.
"""

import json
import logging
import sqlite3
import time
import uuid
from collections import Counter
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Set, Tuple

import database

logger = logging.getLogger("MixerBee.BuildHistory")


def init_db():
    """Initializes build history database schema using the active database connection."""
    with database.get_db_connection() as conn:
        init_history_schema(conn)
        conn.commit()


def init_history_schema(conn: sqlite3.Connection):
    """Initializes tables for tracking build runs and occurrences."""
    conn.execute("""
        CREATE TABLE IF NOT EXISTS build_runs (
            id TEXT PRIMARY KEY,
            connection_id TEXT NOT NULL,
            stable_series_key TEXT,
            trigger_source TEXT NOT NULL DEFAULT 'manual',
            schedule_id TEXT,
            preset_id TEXT,
            output_id TEXT,
            operation TEXT NOT NULL DEFAULT 'playlist',
            started_at TEXT NOT NULL,
            finished_at TEXT,
            outcome TEXT NOT NULL DEFAULT 'running',
            definition_snapshot TEXT,
            summary TEXT,
            replay_origin_id TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_build_runs_conn_series
        ON build_runs(connection_id, stable_series_key, created_at)
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS build_run_items (
            id TEXT PRIMARY KEY,
            run_id TEXT NOT NULL REFERENCES build_runs(id) ON DELETE CASCADE,
            occurrence_id TEXT NOT NULL,
            position INTEGER NOT NULL,
            media_id TEXT NOT NULL,
            media_type TEXT NOT NULL,
            source_block_id TEXT,
            source_series_id TEXT,
            title_snapshot TEXT,
            context_snapshot TEXT,
            runtime_ticks INTEGER DEFAULT 0,
            is_new INTEGER DEFAULT 1
        )
    """)
    conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_build_run_items_run_pos
        ON build_run_items(run_id, position)
    """)
    conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_build_run_items_media
        ON build_run_items(media_id)
    """)


def record_build_start(
    connection_id: str,
    operation: str,
    user_id: str,
    trigger_source: str = "manual",
    schedule_id: Optional[str] = None,
    preset_id: Optional[str] = None,
    series_key: Optional[str] = None,
    definition_snapshot: Optional[Any] = None,
    replay_origin_id: Optional[str] = None
) -> str:
    """Records the beginning of a build operation, returning a run_id."""
    run_id = uuid.uuid4().hex
    started_at = datetime.now(timezone.utc).isoformat()
    def_json = json.dumps(definition_snapshot) if definition_snapshot else "{}"

    # Default series key is preset_id or schedule_id or series_key
    series = series_key or preset_id or schedule_id or "default"

    try:
        with database.get_db_connection() as conn:
            init_history_schema(conn)
            conn.execute(
                """
                INSERT INTO build_runs (
                    id, connection_id, stable_series_key, trigger_source,
                    schedule_id, preset_id, operation, started_at, outcome,
                    definition_snapshot, replay_origin_id
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'running', ?, ?)
                """,
                (
                    run_id, connection_id, series, trigger_source,
                    schedule_id, preset_id, operation, started_at,
                    def_json, replay_origin_id
                )
            )
            conn.commit()
    except Exception as e:
        logger.error(f"Failed to record build start: {e}", exc_info=True)

    return run_id


def record_build_finish(
    run_id: str,
    output_id: Optional[str],
    outcome: str,
    summary: Optional[str] = None,
    rows: Optional[List[Dict[str, Any]]] = None
):
    """Finalizes a build run record with accepted rows and outcome status."""
    finished_at = datetime.now(timezone.utc).isoformat()
    try:
        with database.get_db_connection() as conn:
            init_history_schema(conn)
            conn.execute(
                """
                UPDATE build_runs
                SET output_id = ?, outcome = ?, summary = ?, finished_at = ?
                WHERE id = ?
                """,
                (output_id, outcome, summary or "", finished_at, run_id)
            )

            if rows and outcome in ("ok", "replaced", "success"):
                item_rows = []
                for idx, row in enumerate(rows):
                    item_id = uuid.uuid4().hex
                    occurrence_id = row.get("entry_id") or uuid.uuid4().hex
                    media_id = str(row.get("Id") or row.get("media_id") or "")
                    media_type = str(row.get("Type") or row.get("media_type") or "Unknown")
                    source_block_id = row.get("source_block_id") or ""
                    source_series_id = row.get("source_series_id") or ""
                    title = row.get("Name") or row.get("name") or "Unknown"
                    context = row.get("context") or ""
                    runtime_ticks = int(row.get("RunTimeTicks") or row.get("runtime_ticks") or 0)
                    is_new = 1 if row.get("is_new", True) else 0

                    item_rows.append((
                        item_id, run_id, occurrence_id, idx, media_id,
                        media_type, source_block_id, source_series_id,
                        title, context, runtime_ticks, is_new
                    ))

                conn.executemany(
                    """
                    INSERT INTO build_run_items (
                        id, run_id, occurrence_id, position, media_id,
                        media_type, source_block_id, source_series_id,
                        title_snapshot, context_snapshot, runtime_ticks, is_new
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    item_rows
                )
            conn.commit()
    except Exception as e:
        logger.error(f"Failed to record build finish for {run_id}: {e}", exc_info=True)


def get_recent_build_runs(connection_id: str, limit: int = 50) -> List[Dict[str, Any]]:
    """Fetches recent build runs for a connection."""
    try:
        with database.get_db_connection() as conn:
            init_history_schema(conn)
            rows = conn.execute(
                """
                SELECT id, connection_id, stable_series_key, trigger_source,
                       schedule_id, preset_id, output_id, operation, started_at,
                       finished_at, outcome, summary, replay_origin_id
                FROM build_runs
                WHERE connection_id = ?
                ORDER BY started_at DESC
                LIMIT ?
                """,
                (connection_id, limit)
            ).fetchall()
            return [dict(r) for r in rows]
    except Exception as e:
        logger.error(f"Failed to fetch recent build runs: {e}", exc_info=True)
        return []


def get_build_run_detail(run_id: str, connection_id: str) -> Optional[Dict[str, Any]]:
    """Fetches full build run details including items and occurrence metadata."""
    try:
        with database.get_db_connection() as conn:
            init_history_schema(conn)
            run = conn.execute(
                """
                SELECT * FROM build_runs WHERE id = ? AND connection_id = ?
                """,
                (run_id, connection_id)
            ).fetchone()
            if not run:
                return None

            result = dict(run)
            items = conn.execute(
                """
                SELECT occurrence_id, position, media_id, media_type,
                       source_block_id, source_series_id, title_snapshot,
                       context_snapshot, runtime_ticks, is_new
                FROM build_run_items
                WHERE run_id = ?
                ORDER BY position ASC
                """,
                (run_id,)
            ).fetchall()
            result["items"] = [dict(it) for it in items]
            return result
    except Exception as e:
        logger.error(f"Failed to fetch build run detail for {run_id}: {e}", exc_info=True)
        return None


def get_history_media_ids(
    connection_id: str,
    scope: str = "series",
    last_n_builds: int = 3,
    series_key: Optional[str] = None
) -> Set[str]:
    """Returns media IDs appearing in recent successful builds for freshness cooldown."""
    if last_n_builds <= 0:
        return set()
    try:
        with database.get_db_connection() as conn:
            init_history_schema(conn)
            if scope == "series" and series_key:
                runs = conn.execute(
                    """
                    SELECT id FROM build_runs
                    WHERE connection_id = ? AND stable_series_key = ?
                      AND outcome IN ('ok', 'replaced', 'success')
                    ORDER BY started_at DESC
                    LIMIT ?
                    """,
                    (connection_id, series_key, last_n_builds)
                ).fetchall()
            else:
                runs = conn.execute(
                    """
                    SELECT id FROM build_runs
                    WHERE connection_id = ?
                      AND outcome IN ('ok', 'replaced', 'success')
                    ORDER BY started_at DESC
                    LIMIT ?
                    """,
                    (connection_id, last_n_builds)
                ).fetchall()

            if not runs:
                return set()

            run_ids = [r["id"] for r in runs]
            placeholders = ",".join("?" for _ in run_ids)
            items = conn.execute(
                f"""
                SELECT DISTINCT media_id FROM build_run_items
                WHERE run_id IN ({placeholders})
                """,
                run_ids
            ).fetchall()
            return {r["media_id"] for r in items}
    except Exception as e:
        logger.error(f"Failed to fetch history media ids: {e}", exc_info=True)
        return set()


def compute_run_diff(old_items: List[Dict[str, Any]], new_items: List[Dict[str, Any]]) -> Dict[str, Any]:
    """
    Computes occurrence-aware diff between two lineups:
    Count additions, removals, and retained items with occurrence preservation.
    """
    old_ids = [str(x.get("media_id") or x.get("Id")) for x in old_items if x.get("media_id") or x.get("Id")]
    new_ids = [str(x.get("media_id") or x.get("Id")) for x in new_items if x.get("media_id") or x.get("Id")]

    old_counts = Counter(old_ids)
    new_counts = Counter(new_ids)

    retained_counts = old_counts & new_counts
    added_counts = new_counts - old_counts
    removed_counts = old_counts - new_counts

    retained_count = sum(retained_counts.values())
    added_count = sum(added_counts.values())
    removed_count = sum(removed_counts.values())

    order_changed = False
    common_old = [x for x in old_ids if x in retained_counts]
    common_new = [x for x in new_ids if x in retained_counts]
    if common_old != common_new:
        order_changed = True

    return {
        "added_count": added_count,
        "removed_count": removed_count,
        "retained_count": retained_count,
        "order_changed": order_changed
    }
