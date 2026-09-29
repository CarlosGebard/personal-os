from __future__ import annotations

import os
import sqlite3
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_DB_PATH = PROJECT_ROOT / "data/tracker.db"
ENV_DB_PATH = "VICTUS_HABITS_DB"


def get_db_path() -> Path:
    raw = os.environ.get(ENV_DB_PATH)
    if raw:
        return Path(raw).expanduser()
    return DEFAULT_DB_PATH


def connect(db_path: Path | None = None) -> sqlite3.Connection:
    path = db_path or get_db_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS habits (
          id TEXT PRIMARY KEY,
          name TEXT NOT NULL UNIQUE,
          category TEXT NOT NULL,
          color TEXT,
          icon TEXT,
          is_active INTEGER NOT NULL DEFAULT 1,
          created_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS habit_sessions (
          id TEXT PRIMARY KEY,
          habit_id TEXT NOT NULL,
          started_at TEXT NOT NULL,
          ended_at TEXT,
          source TEXT NOT NULL DEFAULT 'cli',
          note TEXT,
          metadata_json TEXT,
          created_at TEXT NOT NULL,
          updated_at TEXT NOT NULL,
          FOREIGN KEY (habit_id) REFERENCES habits(id)
        );

        CREATE INDEX IF NOT EXISTS idx_habit_sessions_habit_time
        ON habit_sessions(habit_id, started_at, ended_at);

        CREATE INDEX IF NOT EXISTS idx_habit_sessions_active
        ON habit_sessions(ended_at)
        WHERE ended_at IS NULL;

        CREATE TABLE IF NOT EXISTS daily_metrics (
          day TEXT PRIMARY KEY,
          workout INTEGER,
          daily_note TEXT,
          steps INTEGER,
          streamed INTEGER,
          created_at TEXT NOT NULL,
          updated_at TEXT NOT NULL
        );
        """
    )
    daily_metric_columns = {
        row["name"] for row in conn.execute("PRAGMA table_info(daily_metrics)")
    }
    if "daily_note" not in daily_metric_columns:
        conn.execute("ALTER TABLE daily_metrics ADD COLUMN daily_note TEXT")
    if "workout_note" in daily_metric_columns:
        conn.execute(
            """
            UPDATE daily_metrics
            SET daily_note = workout_note
            WHERE daily_note IS NULL AND workout_note IS NOT NULL
            """
        )
        conn.executescript(
            """
            CREATE TABLE daily_metrics_new (
              day TEXT PRIMARY KEY,
              workout INTEGER,
              daily_note TEXT,
              steps INTEGER,
              streamed INTEGER,
              created_at TEXT NOT NULL,
              updated_at TEXT NOT NULL
            );
            INSERT INTO daily_metrics_new
              (day, workout, daily_note, steps, streamed, created_at, updated_at)
            SELECT day, workout, daily_note, steps, streamed, created_at, updated_at
            FROM daily_metrics;
            DROP TABLE daily_metrics;
            ALTER TABLE daily_metrics_new RENAME TO daily_metrics;
            """
        )
    conn.commit()
