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
        """
    )
    conn.commit()
