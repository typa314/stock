# -*- coding: utf-8 -*-
"""
Isolated Unit Tests for bot_db.py:
Tests all database operations in a dedicated temporary SQLite database:
  1. Table initialization & Schema Integrity
  2. User creation & display_name updates
  3. Position management: add, update on conflict, close position, get active
  4. Alert deduplication & cooldown log recording
  5. Watchlist management: add, max_limit enforcement, remove, active query
  6. Dual-node snapshot export & import (ID remapping, conflict resolution, timestamp safety)
  7. Transaction rollback on unhandled error
"""

import os
import tempfile
import unittest
from datetime import datetime

from bot_db import (
    TW_TZ, init_db, get_connection, get_or_create_user,
    add_or_update_position, close_position, get_user_positions,
    get_all_active_positions, should_send_alert, record_alert_log,
    add_to_watchlist, remove_from_watchlist, get_user_watchlist,
    export_db_snapshot, import_db_snapshot
)


class TestBotDbIsolated(unittest.TestCase):
    def setUp(self):
        # Create a unique temporary database file for each test
        self.temp_file = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self.temp_file.close()
        self.db_path = self.temp_file.name
        init_db(self.db_path)

    def tearDown(self):
        # Clean up temporary database
        try:
            if os.path.exists(self.db_path):
                os.remove(self.db_path)
        except Exception:
            pass

    def test_init_db_creates_required_tables(self):
        """Verify all 4 core tables exist after init_db."""
        with get_connection(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
            tables = {row["name"] for row in cursor.fetchall()}

            for req in ["users", "positions", "alert_logs", "watchlist"]:
                self.assertIn(req, tables, f"Table {req} must exist")

    def test_get_or_create_user(self):
        """User creation and display_name update."""
        user1 = get_or_create_user("U12345", display_name="Alice", db_path=self.db_path)
        self.assertEqual(user1["line_user_id"], "U12345")
        self.assertEqual(user1["display_name"], "Alice")
        self.assertEqual(user1["alert_enabled"], 1)

        # Call again with updated name
        user1_updated = get_or_create_user("U12345", display_name="Alice Wang", db_path=self.db_path)
        self.assertEqual(user1_updated["id"], user1["id"])
        self.assertEqual(user1_updated["display_name"], "Alice Wang")

    def test_position_lifecycle(self):
        """Add position, update on conflict, get active, close position."""
        uid = "U_TRADER_1"

        # 1. Add position
        pos = add_or_update_position(uid, "2330", cost_price=900.0, shares=2000, stock_name="台積電", db_path=self.db_path)
        self.assertEqual(pos["ticker"], "2330")
        self.assertAlmostEqual(pos["cost_price"], 900.0)
        self.assertEqual(pos["shares"], 2000)
        self.assertEqual(pos["status"], "OPEN")

        # 2. Update same ticker (adjust cost)
        pos2 = add_or_update_position(uid, "2330", cost_price=920.0, shares=3000, db_path=self.db_path)
        self.assertEqual(pos2["shares"], 3000)
        self.assertAlmostEqual(pos2["cost_price"], 920.0)

        # 3. Add second ticker
        add_or_update_position(uid, "2454", cost_price=1200.0, shares=1000, stock_name="聯發科", db_path=self.db_path)

        # 4. Get active positions
        active = get_user_positions(uid, db_path=self.db_path)
        self.assertEqual(len(active), 2)

        # 5. Close one position
        closed = close_position(uid, "2330", db_path=self.db_path)
        self.assertTrue(closed)

        # 6. Verify closed position is not in active positions
        active_after = get_user_positions(uid, db_path=self.db_path)
        self.assertEqual(len(active_after), 1)
        self.assertEqual(active_after[0]["ticker"], "2454")

    def test_get_all_active_positions_for_worker(self):
        """Worker query joins user details and filters alert_enabled=1."""
        add_or_update_position("U_USER_A", "2330", 900.0, 1000, db_path=self.db_path)
        add_or_update_position("U_USER_B", "2454", 1200.0, 1000, db_path=self.db_path)

        # Disable alert for User B
        with get_connection(self.db_path) as conn:
            conn.execute("UPDATE users SET alert_enabled = 0 WHERE line_user_id = 'U_USER_B'")

        worker_positions = get_all_active_positions(db_path=self.db_path)
        self.assertEqual(len(worker_positions), 1)
        self.assertEqual(worker_positions[0]["line_user_id"], "U_USER_A")
        self.assertEqual(worker_positions[0]["ticker"], "2330")

    def test_alert_cooldown_and_deduplication(self):
        """Verify alert is allowed once per day or within cooldown."""
        user = get_or_create_user("U_ALERT_TEST", db_path=self.db_path)
        uid = user["id"]
        ticker = "2330"
        today_str = datetime.now(TW_TZ).strftime("%Y-%m-%d")

        # First time: should send
        self.assertTrue(should_send_alert(uid, ticker, "STOP_LOSS", alert_date=today_str, db_path=self.db_path))

        # Record alert
        record_alert_log(uid, ticker, "STOP_LOSS", trigger_price=850.0, alert_date=today_str, db_path=self.db_path)

        # Second time on same day: should NOT send
        self.assertFalse(should_send_alert(uid, ticker, "STOP_LOSS", alert_date=today_str, db_path=self.db_path))

        # Different alert type on same day: should send
        self.assertTrue(should_send_alert(uid, ticker, "PROFIT_TAKE", alert_date=today_str, db_path=self.db_path))

    def test_watchlist_lifecycle_and_limit(self):
        """Test watchlist add, limit enforcement, and removal."""
        uid = "U_WATCH_1"

        # Add item 1
        ok, msg = add_to_watchlist(uid, "2330", stock_name="台積電", db_path=self.db_path)
        self.assertTrue(ok)

        # Add item 2 with max_limit=2
        ok, msg = add_to_watchlist(uid, "2454", stock_name="聯發科", max_limit=2, db_path=self.db_path)
        self.assertTrue(ok)

        # Add item 3 with max_limit=2 -> must fail
        ok, msg = add_to_watchlist(uid, "2317", stock_name="鴻海", max_limit=2, db_path=self.db_path)
        self.assertFalse(ok)
        self.assertIn("已達上限", msg)

        # Query watchlist
        w_list = get_user_watchlist(uid, db_path=self.db_path)
        self.assertEqual(len(w_list), 2)

        # Remove item 1
        removed = remove_from_watchlist(uid, "2330", db_path=self.db_path)
        self.assertTrue(removed)

        # Query after remove
        w_list_after = get_user_watchlist(uid, db_path=self.db_path)
        self.assertEqual(len(w_list_after), 1)
        self.assertEqual(w_list_after[0]["ticker"], "2454")

    def test_snapshot_export_and_import_with_id_remapping(self):
        """Dual-node snapshot export & import safely remaps user IDs and resolves conflicts."""
        # Setup source database
        src_temp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        src_temp.close()
        src_path = src_temp.name
        try:
            init_db(src_path)
            add_or_update_position("U_SYNC_1", "2330", 900.0, 1000, stock_name="台積電", db_path=src_path)
            add_to_watchlist("U_SYNC_1", "2454", stock_name="聯發科", db_path=src_path)

            snapshot = export_db_snapshot(db_path=src_path)
            self.assertEqual(len(snapshot["users"]), 1)
            self.assertEqual(len(snapshot["positions"]), 1)
            self.assertEqual(len(snapshot["watchlist"]), 1)

            # Import snapshot into destination DB
            stats = import_db_snapshot(snapshot, db_path=self.db_path)
            self.assertEqual(stats["users"], 1)
            self.assertEqual(stats["positions"], 1)
            self.assertEqual(stats["watchlist"], 1)

            # Verify data exists in destination
            pos = get_user_positions("U_SYNC_1", db_path=self.db_path)
            self.assertEqual(len(pos), 1)
            self.assertEqual(pos[0]["ticker"], "2330")

            w = get_user_watchlist("U_SYNC_1", db_path=self.db_path)
            self.assertEqual(len(w), 1)
            self.assertEqual(w[0]["ticker"], "2454")
        finally:
            if os.path.exists(src_path):
                os.remove(src_path)

    def test_transaction_rollback_on_error(self):
        """Verify get_connection rolls back transaction if an unhandled exception occurs."""
        try:
            with get_connection(self.db_path) as conn:
                conn.execute("INSERT INTO users (line_user_id, display_name) VALUES ('U_FAIL', 'FailUser')")
                # Intentionally trigger an error
                raise ValueError("Simulated unexpected failure")
        except ValueError:
            pass

        # User must NOT exist due to rollback
        with get_connection(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM users WHERE line_user_id = 'U_FAIL'")
            self.assertIsNone(cursor.fetchone(), "Uncommitted transaction must be rolled back")


if __name__ == "__main__":
    unittest.main()
