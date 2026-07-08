from __future__ import annotations

import sqlite3
import uuid
from datetime import date, datetime, time, timedelta, timezone
from typing import Iterable


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def now_iso() -> str:
    return now_utc().isoformat()


def now_local() -> datetime:
    return datetime.now().astimezone()


def parse_dt(value: str) -> datetime:
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def fmt_duration(seconds: float | int) -> str:
    seconds = int(max(0, seconds))
    hours = seconds // 3600
    minutes = (seconds % 3600) // 60
    secs = seconds % 60
    return f"{hours:02d}:{minutes:02d}:{secs:02d}"


def today_bounds_utc() -> tuple[datetime, datetime]:
    current = now_local().date()
    start_local = datetime.combine(current, time.min).astimezone()
    tomorrow_local = datetime.combine(current + timedelta(days=1), time.min).astimezone()
    return start_local.astimezone(timezone.utc), tomorrow_local.astimezone(timezone.utc)


def current_week_dates() -> list[date]:
    current = now_local().date()
    monday = current - timedelta(days=current.weekday())
    days = (current - monday).days + 1
    return [monday + timedelta(days=offset) for offset in range(days)]


def current_month_dates() -> list[date]:
    current = now_local().date()
    first = current.replace(day=1)
    days = current.day
    return [first + timedelta(days=offset) for offset in range(days)]


def local_day_bounds_utc(day: date) -> tuple[datetime, datetime]:
    start_local = datetime.combine(day, time.min).astimezone()
    end_local = datetime.combine(day + timedelta(days=1), time.min).astimezone()
    return start_local.astimezone(timezone.utc), end_local.astimezone(timezone.utc)


def date_range_bounds_utc(days: list[date]) -> tuple[datetime, datetime]:
    if not days:
        raise ValueError("Date range cannot be empty")
    start, _ = local_day_bounds_utc(days[0])
    _, end = local_day_bounds_utc(days[-1])
    return start, end


def ensure_habit(conn: sqlite3.Connection, name: str, category: str = "focus") -> str:
    normalized = name.strip()
    if not normalized:
        raise ValueError("Habit name cannot be empty")

    row = conn.execute("SELECT id FROM habits WHERE name = ?", (normalized,)).fetchone()
    if row:
        return str(row["id"])

    habit_id = str(uuid.uuid4())
    ts = now_iso()
    conn.execute(
        """
        INSERT INTO habits (id, name, category, created_at)
        VALUES (?, ?, ?, ?)
        """,
        (habit_id, normalized, category, ts),
    )
    conn.commit()
    return habit_id


def get_active_session(conn: sqlite3.Connection) -> sqlite3.Row | None:
    return conn.execute(
        """
        SELECT hs.id, hs.habit_id, hs.started_at, h.name AS habit_name
        FROM habit_sessions hs
        JOIN habits h ON h.id = hs.habit_id
        WHERE hs.ended_at IS NULL
        ORDER BY hs.started_at DESC
        LIMIT 1
        """
    ).fetchone()


def stop_active(conn: sqlite3.Connection) -> sqlite3.Row | None:
    active = get_active_session(conn)
    if not active:
        return None

    ts = now_iso()
    conn.execute(
        """
        UPDATE habit_sessions
        SET ended_at = ?, updated_at = ?
        WHERE id = ?
        """,
        (ts, ts, active["id"]),
    )
    conn.commit()
    return active


def stop_habit(conn: sqlite3.Connection, habit_name: str) -> sqlite3.Row | None:
    active = get_active_session(conn)
    if not active or active["habit_name"] != habit_name:
        return None
    return stop_active(conn)


def start_habit(conn: sqlite3.Connection, name: str, category: str = "focus") -> str:
    habit_id = ensure_habit(conn, name, category)

    # Strict mode: only one active session globally.
    stop_active(conn)

    session_id = str(uuid.uuid4())
    ts = now_iso()
    conn.execute(
        """
        INSERT INTO habit_sessions
        (id, habit_id, started_at, source, created_at, updated_at)
        VALUES (?, ?, ?, 'cli', ?, ?)
        """,
        (session_id, habit_id, ts, ts, ts),
    )
    conn.commit()
    return session_id


def add_manual_session(
    conn: sqlite3.Connection,
    name: str,
    hours: float,
    day: date,
    category: str = "focus",
    note: str | None = None,
) -> str:
    if hours <= 0:
        raise ValueError("Hours must be greater than 0")
    if hours > 24:
        raise ValueError("Hours must be 24 or less")

    habit_id = ensure_habit(conn, name, category)
    started_at = datetime.combine(day, time.min).astimezone()
    ended_at = started_at + timedelta(hours=hours)
    session_id = str(uuid.uuid4())
    ts = now_iso()
    conn.execute(
        """
        INSERT INTO habit_sessions
        (id, habit_id, started_at, ended_at, source, note, created_at, updated_at)
        VALUES (?, ?, ?, ?, 'manual', ?, ?, ?)
        """,
        (
            session_id,
            habit_id,
            started_at.astimezone(timezone.utc).isoformat(),
            ended_at.astimezone(timezone.utc).isoformat(),
            note,
            ts,
            ts,
        ),
    )
    conn.commit()
    return session_id


def list_habits(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    return list(
        conn.execute(
            """
            SELECT name, category, is_active
            FROM habits
            ORDER BY name ASC
            """
        ).fetchall()
    )


def sessions_today(conn: sqlite3.Connection, habit_name: str | None = None) -> list[sqlite3.Row]:
    start, end = today_bounds_utc()
    return sessions_between(conn, start, end, habit_name)


def sessions_between(
    conn: sqlite3.Connection,
    start: datetime,
    end: datetime,
    habit_name: str | None = None,
) -> list[sqlite3.Row]:
    params: list[str] = [end.isoformat(), start.isoformat()]
    where_name = ""
    if habit_name:
        where_name = "AND h.name = ?"
        params.append(habit_name)

    return list(
        conn.execute(
            f"""
            SELECT h.name AS habit_name, hs.started_at, hs.ended_at
            FROM habit_sessions hs
            JOIN habits h ON h.id = hs.habit_id
            WHERE hs.started_at < ?
            AND (hs.ended_at IS NULL OR hs.ended_at >= ?)
            {where_name}
            ORDER BY h.name ASC, hs.started_at ASC
            """,
            params,
        ).fetchall()
    )


def daily_totals_for_dates(
    rows: Iterable[sqlite3.Row],
    days: list[date],
) -> dict[str, dict[date, float]]:
    current = now_utc()
    totals: dict[str, dict[date, float]] = {}

    for row in rows:
        habit_name = str(row["habit_name"])
        started = parse_dt(str(row["started_at"]))
        ended_raw = row["ended_at"]
        ended = parse_dt(str(ended_raw)) if ended_raw else current
        if ended <= started:
            continue

        habit_totals = totals.setdefault(habit_name, {})
        for day in days:
            day_start, day_end = local_day_bounds_utc(day)
            segment_start = max(started, day_start)
            segment_end = min(ended, day_end)
            if segment_end > segment_start:
                habit_totals[day] = habit_totals.get(day, 0.0) + (
                    segment_end - segment_start
                ).total_seconds()

    return totals


def duration_for_rows(
    rows: Iterable[sqlite3.Row],
    since: datetime | None = None,
    until: datetime | None = None,
) -> dict[str, float]:
    current = now_utc()
    totals: dict[str, float] = {}

    for row in rows:
        habit_name = str(row["habit_name"])
        started = parse_dt(str(row["started_at"]))
        ended_raw = row["ended_at"]
        ended = parse_dt(str(ended_raw)) if ended_raw else current
        if since and started < since:
            started = since
        if until and ended > until:
            ended = until
        totals[habit_name] = totals.get(habit_name, 0.0) + (ended - started).total_seconds()

    return totals


def active_session_duration(active: sqlite3.Row | None) -> float:
    if not active:
        return 0.0
    started = parse_dt(str(active["started_at"]))
    return (now_utc() - started).total_seconds()


def timer_state(conn: sqlite3.Connection, habit_name: str) -> tuple[float, float, bool]:
    rows = sessions_today(conn, habit_name)
    start, end = today_bounds_utc()
    totals = duration_for_rows(rows, start, end)
    total = totals.get(habit_name, 0.0)

    active = get_active_session(conn)
    is_active = bool(active and active["habit_name"] == habit_name)
    session = active_session_duration(active) if is_active else 0.0

    return total, session, is_active
