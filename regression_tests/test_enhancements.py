"""
regression_tests/test_enhancements.py - Comprehensive tests for senior enhancements:
- Pipeline resolution & provenance tracking
- Freshness cooldown & exhaustion policies
- Duplicate suppression & franchise limits
- Whole-mix time budget with overrun tolerance
- Weighted sequencing patterns & round robin
- Non-destructive collection rebuilds
- Automation controls (pause, snooze, trigger sources)
- Reusable block recipes & preset rename
- Configuration backup & restore cycle
- Enrichment manager concurrency guard
- Shared document composer & fingerprinting
"""

import os
import json
import sqlite3
import tempfile
import unittest
from datetime import datetime, timezone, timedelta
from pathlib import Path
from unittest.mock import Mock, patch

_storage = tempfile.TemporaryDirectory(prefix="mixerbee-enhancements-tests-")
os.environ["MIXERBEE_CONFIG_DIR"] = _storage.name
os.environ["ANONYMIZED_TELEMETRY"] = "False"

import database
import app as core
from app import builder, items, build_history
from app.ai import vector_store, enrichment_manager
import scheduler
from preset_manager import preset_manager


class EnhancementTests(unittest.TestCase):
    def setUp(self):
        self.test_dir = tempfile.TemporaryDirectory(dir=_storage.name)
        database.DB_PATH = Path(self.test_dir.name) / "mixerbee.db"
        database.init_db()

        # Seed account and media connections to satisfy foreign keys
        with database.get_db_connection() as conn:
            conn.execute("INSERT OR IGNORE INTO accounts (id, username, username_key, password_hash, is_admin, created_at) VALUES ('acc1', 'admin', 'admin', 'hash', 1, 0.0)")
            for cid in ('conn_1', 'conn_backup_test', 'conn_recipe_test', 'conn_fresh_1', 'conn_enrich_lock_test'):
                conn.execute(
                    "INSERT OR IGNORE INTO media_connections (id, owner_id, base_url, server_type, username, password, user_id, server_id) "
                    "VALUES (?, 'acc1', 'http://localhost', 'emby', 'user', 'pass', 'uid', 'sid')",
                    (cid,)
                )
            conn.commit()

    def tearDown(self):
        self.test_dir.cleanup()

    def test_pipeline_provenance_and_entry_ids(self):
        """Verify resolve_mix creates distinct entry_ids and tracks block provenance."""
        fake_media = Mock()
        fake_media.connection.id = "conn_1"
        fake_media.get.return_value.ok = True
        fake_media.get.return_value.json.return_value = {
            "Items": [
                {"Id": "mov_1", "Name": "Movie One", "Type": "Movie", "RunTimeTicks": 60 * 60 * 10_000_000},
                {"Id": "mov_2", "Name": "Movie Two", "Type": "Movie", "RunTimeTicks": 90 * 60 * 10_000_000}
            ]
        }

        blocks = [
            {
                "type": "curated",
                "block_id": "blk_curated_1",
                "title": "Selected Movies",
                "movies": [{"Id": "mov_1"}, {"Id": "mov_2"}]
            }
        ]

        res = builder.resolve_mix(
            blocks=blocks,
            user_id="user_123",
            media=fake_media,
            mix_options={"sequencing": {"mode": "sequential"}}
        )

        self.assertEqual(len(res.rows), 2)
        self.assertEqual(res.rows[0]["media_id"], "mov_1")
        self.assertEqual(res.rows[0]["source_block_id"], "blk_curated_1")
        self.assertTrue(len(res.rows[0]["entry_id"]) > 0)
        self.assertNotEqual(res.rows[0]["entry_id"], res.rows[1]["entry_id"])
        self.assertEqual(res.total_items, 2)
        self.assertEqual(res.total_duration_minutes, 150)

    def test_freshness_cooldown_and_exhaustion(self):
        """Verify recent build history excludes items and relax_cooldown restores them if pool is exhausted."""
        conn_id = "conn_fresh_1"
        series_k = "series_alpha"

        # Record a past build run with mov_1
        run_id = build_history.record_build_start(
            connection_id=conn_id,
            operation="playlist",
            user_id="user_1",
            series_key=series_k
        )
        build_history.record_build_finish(
            run_id=run_id,
            output_id="out_1",
            outcome="success",
            rows=[{"media_id": "mov_1", "media_type": "Movie", "title": "Movie 1", "runtime_ticks": 0}]
        )

        candidates = [
            {"media_id": "mov_1", "Name": "Movie 1", "Type": "Movie"},
            {"media_id": "mov_2", "Name": "Movie 2", "Type": "Movie"},
        ]

        # 1. Standard shorter policy -> mov_1 excluded
        warnings = []
        filtered = builder.apply_duplicate_and_freshness(
            rows=candidates,
            dup_opt={},
            freshness_opt={"last_successful_builds": 1, "history_scope": "series", "exhaustion_policy": "shorter"},
            connection_id=conn_id,
            warnings=warnings,
            series_key=series_k
        )
        self.assertEqual(len(filtered), 1)
        self.assertEqual(filtered[0]["media_id"], "mov_2")

        # 2. Candidate exhaustion with relax_cooldown -> mov_1 returned with warning
        only_mov1 = [{"media_id": "mov_1", "Name": "Movie 1", "Type": "Movie"}]
        warnings_relax = []
        filtered_relaxed = builder.apply_duplicate_and_freshness(
            rows=only_mov1,
            dup_opt={},
            freshness_opt={"last_successful_builds": 1, "history_scope": "series", "exhaustion_policy": "relax_cooldown"},
            connection_id=conn_id,
            warnings=warnings_relax,
            series_key=series_k
        )
        self.assertEqual(len(filtered_relaxed), 1)
        self.assertTrue(any("relaxed" in w for w in warnings_relax))

    def test_duplicate_suppression_and_franchise_caps(self):
        """Verify cross-block duplicate suppression and max movies per franchise."""
        candidates = [
            {"media_id": "mov_batman_1", "Name": "Batman Begins", "Type": "Movie", "raw_item": {"SeriesName": "Batman"}},
            {"media_id": "mov_batman_2", "Name": "The Dark Knight", "Type": "Movie", "raw_item": {"SeriesName": "Batman"}},
            {"media_id": "mov_batman_1", "Name": "Batman Begins", "Type": "Movie", "raw_item": {"SeriesName": "Batman"}}, # duplicate
            {"media_id": "mov_matrix_1", "Name": "The Matrix", "Type": "Movie", "raw_item": {"SeriesName": "Matrix"}},
        ]

        warnings = []
        filtered = builder.apply_duplicate_and_freshness(
            rows=candidates,
            dup_opt={"mode": "suppress", "max_movies_per_franchise": 1},
            freshness_opt={},
            connection_id="conn_1",
            warnings=warnings,
            series_key=""
        )

        # Should only allow: mov_batman_1 (first of Batman) and mov_matrix_1
        ids = [x["media_id"] for x in filtered]
        self.assertEqual(ids, ["mov_batman_1", "mov_matrix_1"])

    def test_whole_mix_time_budget(self):
        """Verify runtime budget limits total duration and respects allowed overrun."""
        one_min_ticks = 60 * 10_000_000
        rows = [
            {"media_id": "m1", "runtime_ticks": 60 * one_min_ticks, "is_pinned": False},
            {"media_id": "m2", "runtime_ticks": 50 * one_min_ticks, "is_pinned": False},
            {"media_id": "m3", "runtime_ticks": 30 * one_min_ticks, "is_pinned": False},
        ]

        warnings = []
        budgeted = builder.apply_runtime_budget(
            rows=rows,
            budget_opt={"mode": "duration", "target_minutes": 100, "allowed_overrun_minutes": 15},
            warnings=warnings
        )
        self.assertEqual(len(budgeted), 2)
        self.assertEqual([r["media_id"] for r in budgeted], ["m1", "m2"])
        self.assertTrue(any("budget" in w.lower() for w in warnings))

    def test_weighted_sequencing_patterns(self):
        """Verify weighted pattern interleaving between distinct blocks."""
        rows_by_block = {
            "b_tv": [
                {"media_id": "tv_a1", "source_block_id": "b_tv"},
                {"media_id": "tv_a2", "source_block_id": "b_tv"},
                {"media_id": "tv_a3", "source_block_id": "b_tv"},
            ],
            "b_mov": [
                {"media_id": "mov_1", "source_block_id": "b_mov"},
                {"media_id": "mov_2", "source_block_id": "b_mov"},
            ]
        }
        block_order = ["b_tv", "b_mov"]

        sequenced = builder.apply_sequencing(
            rows_by_block=rows_by_block,
            block_order=block_order,
            seq_opt={
                "mode": "pattern",
                "pattern": [
                    {"block_id": "b_tv", "take": 2},
                    {"block_id": "b_mov", "take": 1}
                ],
                "exhaustion_policy": "continue"
            }
        )

        expected_ids = ["tv_a1", "tv_a2", "mov_1", "tv_a3", "mov_2"]
        actual_ids = [r["media_id"] for r in sequenced]
        self.assertEqual(actual_ids, expected_ids)

    def test_collection_rebuild_refuses_empty(self):
        """Verify resolve_collection_selection refuses to clear or recreate when 0 items match."""
        fake_media = Mock()
        fake_media.get.return_value.json.return_value = {"Items": []}
        fake_media.get.return_value.ok = True
        fake_media.can_manage_collections.return_value = True

        res = items.resolve_collection_selection(
            user_id="user_1",
            filters={"genres": ["NonExistentGenre12345"]},
            media=fake_media
        )

        self.assertEqual(res, [])

    def test_schedule_automation_controls(self):
        """Verify pause, snooze, and trigger source filtering."""
        now = datetime(2026, 9, 26, 12, 0, 0, tzinfo=timezone.utc)

        # 1. Paused schedule (enabled=False) -> disallowed for automatic runs
        sched_paused = {"enabled": False, "trigger_sources": ["clock", "watch"]}
        self.assertFalse(scheduler.is_automatic_run_allowed(sched_paused, "clock", now))
        self.assertFalse(scheduler.is_automatic_run_allowed(sched_paused, "watch", now))

        # 2. Snoozed schedule -> disallowed until expiry
        snooze_until = (now + timedelta(hours=2)).isoformat()
        sched_snoozed = {"enabled": True, "snoozed_until": snooze_until, "trigger_sources": ["clock"]}
        self.assertFalse(scheduler.is_automatic_run_allowed(sched_snoozed, "clock", now))
        future_now = now + timedelta(hours=3)
        self.assertTrue(scheduler.is_automatic_run_allowed(sched_snoozed, "clock", future_now))

        # 3. Trigger sources restriction (clock only vs webhook library event)
        sched_clock_only = {"enabled": True, "trigger_sources": ["clock"]}
        self.assertTrue(scheduler.is_automatic_run_allowed(sched_clock_only, "clock", now))
        self.assertFalse(scheduler.is_automatic_run_allowed(sched_clock_only, "library", now))

    def test_recipe_repository_and_preset_rename(self):
        """Verify saving a block recipe, listing recipes, and renaming presets."""
        conn_id = "conn_recipe_test"

        # 1. Save Recipe
        saved_id = preset_manager.save_recipe(
            connection_id=conn_id,
            name="Unwatched Sci-Fi",
            description="Top rated unwatched sci-fi films",
            block_def={"type": "movie", "filters": {"genres": ["Sci-Fi"]}},
            tags=["movies", "sci-fi"],
            is_favorite=True
        )
        self.assertIsNotNone(saved_id)
        self.assertTrue(isinstance(saved_id, str))

        # 2. List Recipes
        recipes = preset_manager.list_recipes(connection_id=conn_id)
        self.assertEqual(len(recipes), 1)
        self.assertEqual(recipes[0]["name"], "Unwatched Sci-Fi")

        # 3. Save and Rename Preset by ID
        pid = preset_manager.save_preset("Original Name", [{"type": "movie"}], conn_id)
        renamed_ok = preset_manager.rename_preset(pid, conn_id, "New Name")
        self.assertTrue(renamed_ok)
        fetched = preset_manager.get_preset_by_id(pid, conn_id)
        self.assertEqual(fetched["name"], "New Name")

    def test_backup_and_restore_cycle(self):
        """Verify SQLite online backup, manifest verification, and staged restore."""
        conn_id = "conn_backup_test"
        preset_manager.save_preset("Preset Before Backup", [{"type": "movie"}], conn_id)

        # Create backup
        backup_zip = core.create_backup_archive()
        self.assertTrue(backup_zip.exists())

        # Inspect backup
        inspection = core.inspect_backup_archive(backup_zip)
        self.assertTrue(inspection["valid"])
        self.assertEqual(inspection["integrity_check"], "ok")
        self.assertGreaterEqual(inspection["manifest"]["database_counts"]["presets"], 1)

        # Modify database state
        preset_manager.save_preset("Preset After Backup", [{"type": "tv"}], conn_id)
        self.assertIsNotNone(preset_manager.get_preset_by_name("Preset After Backup", conn_id))

        # Restore backup
        restore_res = core.restore_backup_archive(backup_zip)
        self.assertEqual(restore_res["status"], "ok")

        self.assertIsNotNone(preset_manager.get_preset_by_name("Preset Before Backup", conn_id))
        self.assertIsNone(preset_manager.get_preset_by_name("Preset After Backup", conn_id))

        backup_zip.unlink(missing_ok=True)

    def test_enrichment_concurrency_guard(self):
        """Verify enrichment concurrency guard prevents overlapping runs."""
        conn_id = "conn_enrich_lock_test"

        acquired = enrichment_manager.acquire_enrichment_guard(conn_id)
        self.assertTrue(acquired)

        second_acquired = enrichment_manager.acquire_enrichment_guard(conn_id)
        self.assertFalse(second_acquired)

        enrichment_manager.release_enrichment_guard(conn_id)

        with enrichment_manager.enrichment_guard(conn_id) as guard_acquired:
            self.assertTrue(guard_acquired)
            self.assertFalse(enrichment_manager.acquire_enrichment_guard(conn_id))

        self.assertTrue(enrichment_manager.acquire_enrichment_guard(conn_id))
        enrichment_manager.release_enrichment_guard(conn_id)

    def test_shared_document_composer_and_fingerprint(self):
        """Verify compose_document and compute_metadata_fingerprint produce consistent signatures."""
        doc1 = vector_store.compose_document(
            title="Inception",
            year="2010",
            media_type="Movie",
            genres="Action, Sci-Fi",
            vibe_tags="mind-bending, dreamlike",
            overview="A thief who steals corporate secrets through dream-sharing technology."
        )

        doc2 = vector_store.compose_document(
            title="Inception",
            year="2010",
            media_type="Movie",
            genres="Action, Sci-Fi",
            vibe_tags="mind-bending, dreamlike",
            overview="A thief who steals corporate secrets through dream-sharing technology."
        )
        self.assertEqual(doc1, doc2)

        fp1 = vector_store.compute_metadata_fingerprint(
            title="Inception",
            year="2010",
            media_type="Movie",
            genres="Action, Sci-Fi",
            overview="A thief who steals corporate secrets through dream-sharing technology."
        )

        fp_modified = vector_store.compute_metadata_fingerprint(
            title="Inception",
            year="2010",
            media_type="Movie",
            genres="Action, Sci-Fi, Thriller",
            overview="A thief who steals corporate secrets through dream-sharing technology."
        )

        self.assertNotEqual(fp1, fp_modified)


if __name__ == "__main__":
    unittest.main()
