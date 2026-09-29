from __future__ import annotations

import tempfile
import unittest
from datetime import date
from pathlib import Path

from habit_tracker.db import connect, init_db
from habit_tracker.google_sheets import (
    WORK_SESSIONS_TAB,
    WORK_TODAY_TAB,
    sync_work_sessions,
    watch_active_work_sync,
)
from habit_tracker.queries import add_manual_session, create_habit, start_habit


class FakeSheetsGateway:
    def __init__(self) -> None:
        self.tabs: list[str] = []
        self.recalculation_enabled = False
        self.writes: dict[str, tuple[list[list[object]], str]] = {}

    def ensure_tabs(self, names: list[str]) -> None:
        self.tabs = names

    def set_minute_recalculation(self) -> None:
        self.recalculation_enabled = True

    def replace_values(self, tab_name: str, values: list[list[object]], value_input: str) -> None:
        self.writes[tab_name] = (values, value_input)


class GoogleSheetsSyncTests(unittest.TestCase):
    def test_sync_replaces_only_managed_work_tabs(self) -> None:
        with tempfile.TemporaryDirectory() as raw_dir:
            db_path = Path(raw_dir) / "tracker.db"
            with connect(db_path) as conn:
                init_db(conn)
                create_habit(conn, "work")
                create_habit(conn, "study")
                add_manual_session(conn, "work", 1.5, date.today(), note="planning")
                add_manual_session(conn, "study", 2, date.today())

                gateway = FakeSheetsGateway()
                count = sync_work_sessions(conn, gateway)

        self.assertEqual(count, 1)
        self.assertEqual(gateway.tabs, [WORK_SESSIONS_TAB, WORK_TODAY_TAB])
        self.assertTrue(gateway.recalculation_enabled)
        session_values, session_mode = gateway.writes[WORK_SESSIONS_TAB]
        self.assertEqual(session_mode, "RAW")
        self.assertEqual(session_values[0][0], "session_id")
        self.assertEqual(len(session_values), 2)
        self.assertEqual(session_values[1][3], 90.0)

        today_values, today_mode = gateway.writes[WORK_TODAY_TAB]
        self.assertEqual(today_mode, "USER_ENTERED")
        self.assertEqual(today_values[1][1], 90.0)
        self.assertIn("NOW()", str(today_values[1][2]))

    def test_active_work_session_is_marked_for_live_today_formula(self) -> None:
        with tempfile.TemporaryDirectory() as raw_dir:
            db_path = Path(raw_dir) / "tracker.db"
            with connect(db_path) as conn:
                init_db(conn)
                create_habit(conn, "work")
                start_habit(conn, "work")
                gateway = FakeSheetsGateway()
                sync_work_sessions(conn, gateway)

        session_values, _ = gateway.writes[WORK_SESSIONS_TAB]
        self.assertEqual(session_values[1][3], "")
        today_values, _ = gateway.writes[WORK_TODAY_TAB]
        self.assertNotEqual(today_values[1][5], "")

    def test_watcher_exits_when_work_is_not_active(self) -> None:
        with tempfile.TemporaryDirectory() as raw_dir:
            db_path = Path(raw_dir) / "tracker.db"
            with connect(db_path) as conn:
                init_db(conn)
                create_habit(conn, "work")

            watch_active_work_sync(db_path, interval_seconds=0)
