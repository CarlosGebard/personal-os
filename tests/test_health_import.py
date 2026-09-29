from __future__ import annotations

import json
import os
import tempfile
import unittest
from datetime import date
from pathlib import Path
from unittest.mock import patch

from habit_tracker.cli import cmd_import_health
from habit_tracker.db import connect, init_db
from habit_tracker.health_import import latest_health_export, load_step_totals
from habit_tracker.queries import daily_metrics_between


class HealthImportTests(unittest.TestCase):
    def test_load_step_totals_aggregates_step_metric_by_local_date(self) -> None:
        with tempfile.TemporaryDirectory() as raw_dir:
            path = Path(raw_dir) / "HealthAutoExport-2026-08-11.json"
            path.write_text(
                json.dumps(
                    {
                        "data": {
                            "metrics": [
                                {
                                    "name": "Step Count",
                                    "units": "count",
                                    "data": [
                                        {"date": "2026-08-10 00:00:00 -0400", "qty": 1200},
                                        {"date": "2026-08-10 12:00:00 -0400", "qty": 800},
                                        {"date": "2026-08-11 00:00:00 -0400", "qty": 5321},
                                    ],
                                },
                                {"name": "Heart Rate", "data": [{"date": "2026-08-10", "qty": 70}]},
                            ]
                        }
                    }
                ),
                encoding="utf-8",
            )

            self.assertEqual(
                load_step_totals(path),
                {date(2026, 8, 10): 2000, date(2026, 8, 11): 5321},
            )

    def test_latest_health_export_uses_modification_time(self) -> None:
        with tempfile.TemporaryDirectory() as raw_dir:
            folder = Path(raw_dir)
            older = folder / "HealthAutoExport-older.json"
            newest = folder / "HealthAutoExport-newest.json"
            older.write_text("{}", encoding="utf-8")
            newest.write_text("{}", encoding="utf-8")
            os.utime(older, (1, 1))
            os.utime(newest, (2, 2))

            self.assertEqual(latest_health_export(folder), newest)

    def test_load_step_totals_rejects_exports_without_steps(self) -> None:
        with tempfile.TemporaryDirectory() as raw_dir:
            path = Path(raw_dir) / "HealthAutoExport-empty.json"
            path.write_text('{"data": {"metrics": []}}', encoding="utf-8")

            with self.assertRaisesRegex(ValueError, "No step records"):
                load_step_totals(path)

    def test_command_imports_newest_cached_export_into_daily_metrics(self) -> None:
        with tempfile.TemporaryDirectory() as raw_dir:
            project = Path(raw_dir) / "project"
            inbox = project / "data/imports/taildrop"
            inbox.mkdir(parents=True)
            source = inbox / "HealthAutoExport-2026-08-11.json"
            source.write_text(
                json.dumps(
                    {
                        "data": {
                            "metrics": [
                                {
                                    "name": "Steps",
                                    "data": [
                                        {"date": "2026-08-11 00:00:00 -0400", "qty": 9876}
                                    ],
                                }
                            ]
                        }
                    }
                ),
                encoding="utf-8",
            )
            db_path = project / "tracker.db"

            with (
                patch.dict(os.environ, {"VICTUS_HABITS_DB": str(db_path)}),
                patch("habit_tracker.cli.PROJECT_ROOT", project),
                patch("habit_tracker.cli.receive_taildrop_files", return_value=None),
            ):
                self.assertEqual(cmd_import_health(), 0)
                self.assertEqual(cmd_import_health(), 0)

            with connect(db_path) as conn:
                init_db(conn)
                metrics = daily_metrics_between(conn, date(2026, 8, 11), date(2026, 8, 11))
            self.assertEqual(metrics[date(2026, 8, 11)]["steps"], 9876)
