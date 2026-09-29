from __future__ import annotations

import re
import sqlite3
import uuid
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path

from .queries import now_iso, require_habit_id


DAILY_NOTE_NAME = re.compile(r"^\d{4}-\d{2}-\d{2}\.md$")
IMPORT_SOURCE = "obsidian_import"


@dataclass(frozen=True)
class ObsidianDay:
    day: date
    gym: bool | None
    steps: int | None
    streamed: bool | None
    work_minutes: int
    daily_note: str | None
    path: Path


def parse_scalar(value: str) -> bool | int | str:
    raw = value.strip()
    if raw.lower() == "true":
        return True
    if raw.lower() == "false":
        return False
    try:
        return int(raw)
    except ValueError:
        return raw.strip('"')


def parse_work_minutes(value: str | int | None) -> int:
    if value is None:
        return 0
    raw = str(value).strip()
    if not raw:
        return 0
    if not re.fullmatch(r"\d+(?:\.\d{1,2})?", raw):
        raise ValueError(f"Invalid deep_work value: {value!r}")
    hours_text, separator, minutes_text = raw.partition(".")
    hours = int(hours_text)
    minutes = int(minutes_text) if separator else 0
    if minutes >= 60:
        raise ValueError(f"deep_work minutes must be less than 60: {value!r}")
    return hours * 60 + minutes


def parse_note(path: Path) -> ObsidianDay:
    if not DAILY_NOTE_NAME.fullmatch(path.name):
        raise ValueError(f"Not a daily note filename: {path.name}")
    day = date.fromisoformat(path.stem)
    lines = path.read_text(encoding="utf-8").splitlines()
    if not lines or lines[0] != "---":
        raise ValueError(f"Missing frontmatter in {path}")
    try:
        end = lines.index("---", 1)
    except ValueError as exc:
        raise ValueError(f"Unclosed frontmatter in {path}") from exc

    fields: dict[str, bool | int | str] = {}
    for line in lines[1:end]:
        if not line.strip():
            continue
        key, separator, raw_value = line.partition(":")
        if not separator:
            raise ValueError(f"Invalid frontmatter line in {path}: {line!r}")
        fields[key.strip()] = parse_scalar(raw_value)

    body = "\n".join(lines[end + 1 :]).strip() or None
    gym = fields.get("gym")
    streamed = fields.get("TalkCamera")
    steps = fields.get("steps")
    if gym is not None and not isinstance(gym, bool):
        raise ValueError(f"gym must be boolean in {path}")
    if streamed is not None and not isinstance(streamed, bool):
        raise ValueError(f"TalkCamera must be boolean in {path}")
    if steps is not None and (not isinstance(steps, int) or steps < 0):
        raise ValueError(f"steps must be a non-negative integer in {path}")
    return ObsidianDay(
        day=day,
        gym=gym,
        steps=steps,
        streamed=streamed,
        work_minutes=parse_work_minutes(fields.get("deep_work")),
        daily_note=body,
        path=path,
    )


def load_days(root: Path, start: date, end: date) -> list[ObsidianDay]:
    notes = [
        parse_note(path)
        for path in sorted(root.glob("*/????-??-??.md"))
        if start <= date.fromisoformat(path.stem) <= end
    ]
    if not notes:
        raise ValueError(f"No daily notes found in {root} for {start} through {end}")
    return notes


def import_days(conn: sqlite3.Connection, habit_name: str, days: list[ObsidianDay]) -> tuple[int, int]:
    habit_id = require_habit_id(conn, habit_name)
    first_day = min(item.day for item in days)
    last_day = max(item.day for item in days)
    first_start = datetime.combine(first_day, time.min).astimezone().astimezone(timezone.utc)
    final_start = datetime.combine(last_day + timedelta(days=1), time.min).astimezone().astimezone(timezone.utc)
    conn.execute(
        """
        DELETE FROM habit_sessions
        WHERE habit_id = ? AND source = ? AND started_at >= ? AND started_at < ?
        """,
        (habit_id, IMPORT_SOURCE, first_start.isoformat(), final_start.isoformat()),
    )

    ts = now_iso()
    sessions = 0
    for item in days:
        conn.execute(
            """
            INSERT INTO daily_metrics (day, workout, daily_note, steps, streamed, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(day) DO UPDATE SET
              workout = excluded.workout,
              daily_note = excluded.daily_note,
              steps = excluded.steps,
              streamed = excluded.streamed,
              updated_at = excluded.updated_at
            """,
            (
                item.day.isoformat(),
                int(item.gym) if item.gym is not None else None,
                item.daily_note,
                item.steps,
                int(item.streamed) if item.streamed is not None else None,
                ts,
                ts,
            ),
        )
        if not item.work_minutes:
            continue
        started_at = datetime.combine(item.day, time.min).astimezone()
        ended_at = started_at + timedelta(minutes=item.work_minutes)
        conn.execute(
            """
            INSERT INTO habit_sessions
            (id, habit_id, started_at, ended_at, source, note, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                str(uuid.uuid4()),
                habit_id,
                started_at.astimezone(timezone.utc).isoformat(),
                ended_at.astimezone(timezone.utc).isoformat(),
                IMPORT_SOURCE,
                f"Imported from {item.path}",
                ts,
                ts,
            ),
        )
        sessions += 1
    conn.commit()
    return len(days), sessions
