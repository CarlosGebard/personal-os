from __future__ import annotations

import argparse
import os
import signal
import subprocess
import sys
import time
from datetime import date
from pathlib import Path
from textwrap import dedent

from .db import PROJECT_ROOT, connect, get_db_path, init_db
from .queries import (
    active_session_duration,
    add_manual_session,
    current_month_dates,
    current_week_dates,
    daily_totals_for_dates,
    date_range_bounds_utc,
    duration_for_rows,
    fmt_duration,
    get_active_session,
    list_habits,
    sessions_between,
    sessions_today,
    start_habit,
    stop_active,
    stop_habit,
    today_bounds_utc,
)
from .timer import atomic_write, render_once


class HabitHelpFormatter(argparse.RawDescriptionHelpFormatter):
    def __init__(self, prog: str) -> None:
        super().__init__(prog, max_help_position=28, width=88)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="habit",
        description="Track local habit sessions from the terminal.",
        epilog=dedent(
            """
            Common flows:
              habit init
              habit start work
              habit work stop
              habit switch reading --category learning
              habit add work 1.5 --date 2026-07-08
              habit today
              habit week
              habit month
              habit stop

            Data:
              The SQLite database defaults to ./data/tracker.db.
              Override it with VICTUS_HABITS_DB when needed.

            OBS / Waybar:
              Use `--obs` with start/switch/stop to keep ./data/obs/<habit>.txt live.
            """
        ).strip(),
        formatter_class=HabitHelpFormatter,
    )
    sub = parser.add_subparsers(
        dest="command",
        metavar="{init,start,stop,switch,add,status,today,week,month,list}",
        title="commands",
        required=True,
    )

    sub.add_parser(
        "init",
        help="create the local SQLite database",
        description="Create the local SQLite database and schema if they do not exist.",
        formatter_class=HabitHelpFormatter,
    )

    start = sub.add_parser(
        "start",
        help="start a habit session",
        description="Start a new habit session. Any currently active session is stopped first.",
        epilog=dedent(
            """
            Examples:
              habit start work
              habit start work --obs
              habit start work --category focus --obs
            """
        ).strip(),
        formatter_class=HabitHelpFormatter,
    )
    start.add_argument("habit_name", help="habit name, for example: work")
    start.add_argument("--category", default="focus", help="habit category, default: focus")
    start.add_argument("--obs", action="store_true", help="keep ./data/obs/<habit>.txt live")
    start.add_argument("--obs-file", help="custom OBS text file path")

    stop = sub.add_parser(
        "stop",
        help="stop the active habit session",
        description="Stop the currently active habit session, if one exists.",
        epilog=dedent(
            """
            Examples:
              habit stop
              habit stop work
              habit work stop
              habit stop work --obs
            """
        ).strip(),
        formatter_class=HabitHelpFormatter,
    )
    stop.add_argument("habit_name", nargs="?", help="optional active habit name to stop")
    stop.add_argument("--obs", action="store_true", help="stop live OBS updates and write final text")
    stop.add_argument("--obs-file", help="custom OBS text file path")
    stop.set_defaults(command="stop")

    switch = sub.add_parser(
        "switch",
        help="switch to another habit",
        description="Stop the active session and immediately start another habit.",
        epilog=dedent(
            """
            Examples:
              habit switch reading --category learning
              habit switch work --obs
            """
        ).strip(),
        formatter_class=HabitHelpFormatter,
    )
    switch.add_argument("habit_name", help="habit name to start")
    switch.add_argument("--category", default="focus", help="habit category, default: focus")
    switch.add_argument("--obs", action="store_true", help="keep ./data/obs/<habit>.txt live")
    switch.add_argument("--obs-file", help="custom OBS text file path")

    add = sub.add_parser(
        "add",
        help="add manual hours to a habit day",
        description="Add manual tracked time to a habit on a local calendar day.",
        epilog=dedent(
            """
            Examples:
              habit add work 1 --date 2026-07-08
              habit add reading 1.5 --date 2026-07-08 --category learning
              habit add exercise 0.75 --date 2026-07-08 --note "gym"
            """
        ).strip(),
        formatter_class=HabitHelpFormatter,
    )
    add.add_argument("habit_name", help="habit name, for example: work")
    add.add_argument("hours", type=float, help="hours to add, for example: 1.5")
    add.add_argument("--date", required=True, help="local date in YYYY-MM-DD format")
    add.add_argument("--category", default="focus", help="habit category, default: focus")
    add.add_argument("--note", help="optional note for the manual entry")

    sub.add_parser(
        "status",
        help="show the active session",
        description="Show the active habit and current session duration.",
        formatter_class=HabitHelpFormatter,
    )

    today = sub.add_parser(
        "today",
        help="show today's totals",
        description="Show total tracked time for today using the system local timezone.",
        epilog=dedent(
            """
            Examples:
              habit today
              habit today work
            """
        ).strip(),
        formatter_class=HabitHelpFormatter,
    )
    today.add_argument("habit_name", nargs="?", help="optional habit name to filter")

    week = sub.add_parser(
        "week",
        aliases=["semana"],
        help="show current week totals by day",
        description="Show tracked time for each habit on each day of the current local week.",
        epilog=dedent(
            """
            Examples:
              habit week
              habit week work
            """
        ).strip(),
        formatter_class=HabitHelpFormatter,
    )
    week.add_argument("habit_name", nargs="?", help="optional habit name to filter")
    week.set_defaults(command="week")

    month = sub.add_parser(
        "month",
        aliases=["mes"],
        help="show current month totals by day",
        description="Show tracked time for each habit on each day of the current local month.",
        epilog=dedent(
            """
            Examples:
              habit month
              habit month work
            """
        ).strip(),
        formatter_class=HabitHelpFormatter,
    )
    month.add_argument("habit_name", nargs="?", help="optional habit name to filter")
    month.set_defaults(command="month")

    sub.add_parser(
        "list",
        help="list known habits",
        description="List all habits that have been created through tracked sessions.",
        formatter_class=HabitHelpFormatter,
    )

    return parser


def obs_file_for(habit_name: str, obs_file: str | None = None) -> Path:
    if obs_file:
        return Path(obs_file).expanduser()
    safe_name = habit_name.replace("/", "-").replace("\\", "-")
    return PROJECT_ROOT / "data/obs" / f"{safe_name}.txt"


def obs_pid_file_for(habit_name: str, obs_file: str | None = None) -> Path:
    return obs_file_for(habit_name, obs_file).with_suffix(".pid")


def obs_log_file_for(habit_name: str, obs_file: str | None = None) -> Path:
    return obs_file_for(habit_name, obs_file).with_suffix(".log")


def process_is_running(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def read_pid(path: Path) -> int | None:
    try:
        return int(path.read_text(encoding="utf-8").strip())
    except (FileNotFoundError, ValueError):
        return None


def update_obs_text(habit_name: str, obs_file: str | None = None) -> Path:
    path = obs_file_for(habit_name, obs_file)
    atomic_write(path, render_once(habit_name))
    return path


def start_obs_live(habit_name: str, obs_file: str | None = None) -> Path:
    output_path = obs_file_for(habit_name, obs_file)
    pid_path = obs_pid_file_for(habit_name, obs_file)
    log_path = obs_log_file_for(habit_name, obs_file)
    pid = read_pid(pid_path)
    if pid and process_is_running(pid):
        return output_path
    pid_path.unlink(missing_ok=True)

    update_obs_text(habit_name, obs_file)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    timer_bin = Path(sys.argv[0]).with_name("habit-timer")
    command = [str(timer_bin), habit_name, str(output_path)]
    if not timer_bin.exists():
        command = [sys.executable, "-m", "habit_tracker.timer", habit_name, str(output_path)]
    log_file = log_path.open("ab")
    proc = subprocess.Popen(
        command,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=log_file,
        start_new_session=True,
    )
    log_file.close()
    time.sleep(0.05)
    if proc.poll() is not None:
        pid_path.unlink(missing_ok=True)
        raise RuntimeError(f"OBS live renderer failed; see {log_path}")
    pid_path.write_text(f"{proc.pid}\n", encoding="utf-8")
    return output_path


def stop_obs_live(habit_name: str, obs_file: str | None = None) -> Path:
    output_path = obs_file_for(habit_name, obs_file)
    pid_path = obs_pid_file_for(habit_name, obs_file)
    pid = read_pid(pid_path)
    if pid and process_is_running(pid):
        os.kill(pid, signal.SIGTERM)
        for _ in range(10):
            if not process_is_running(pid):
                break
            time.sleep(0.05)
    pid_path.unlink(missing_ok=True)
    update_obs_text(habit_name, obs_file)
    return output_path


def cmd_init() -> int:
    with connect() as conn:
        init_db(conn)
    print(f"Initialized: {get_db_path()}")
    return 0


def cmd_start(
    habit_name: str,
    category: str,
    obs: bool = False,
    obs_file: str | None = None,
) -> int:
    with connect() as conn:
        init_db(conn)
        start_habit(conn, habit_name, category)
    print(f"Started: {habit_name}")
    if obs:
        path = start_obs_live(habit_name, obs_file)
        print(f"OBS live: {path}")
    return 0


def cmd_stop(
    habit_name: str | None = None,
    obs: bool = False,
    obs_file: str | None = None,
) -> int:
    with connect() as conn:
        init_db(conn)
        active = stop_habit(conn, habit_name) if habit_name else stop_active(conn)
    if not active:
        if habit_name:
            print(f"No active habit named: {habit_name}")
        else:
            print("No active habit")
    else:
        print(f"Stopped: {active['habit_name']}")
        if obs:
            path = stop_obs_live(str(active["habit_name"]), obs_file)
            print(f"OBS final: {path}")
    return 0


def normalize_args(args: list[str]) -> list[str]:
    if len(args) >= 2 and args[1] == "stop":
        return ["stop", args[0], *args[2:]]
    return args


def cmd_switch(
    habit_name: str,
    category: str,
    obs: bool = False,
    obs_file: str | None = None,
) -> int:
    with connect() as conn:
        init_db(conn)
        start_habit(conn, habit_name, category)
    print(f"Switched to: {habit_name}")
    if obs:
        path = start_obs_live(habit_name, obs_file)
        print(f"OBS live: {path}")
    return 0


def cmd_add(
    habit_name: str,
    hours: float,
    raw_date: str,
    category: str,
    note: str | None,
) -> int:
    day = date.fromisoformat(raw_date)
    with connect() as conn:
        init_db(conn)
        add_manual_session(conn, habit_name, hours, day, category, note)
    print(f"Added: {habit_name} {fmt_duration(hours * 3600)} on {day.isoformat()}")
    return 0


def cmd_status() -> int:
    with connect() as conn:
        init_db(conn)
        active = get_active_session(conn)
        if not active:
            print("No active habit")
            return 0
        session_seconds = active_session_duration(active)
        print(f"Active: {active['habit_name']} since {active['started_at']}")
        print(f"Session: {fmt_duration(session_seconds)}")
    return 0


def cmd_today(habit_name: str | None) -> int:
    with connect() as conn:
        init_db(conn)
        rows = sessions_today(conn, habit_name)
        start, end = today_bounds_utc()
        totals = duration_for_rows(rows, start, end)

    if habit_name:
        print(f"{habit_name} {fmt_duration(totals.get(habit_name, 0))}")
        return 0

    print("Today")
    if not totals:
        print("No sessions today")
        return 0

    width = max(len(name) for name in totals.keys())
    for name in sorted(totals):
        print(f"{name.ljust(width)} {fmt_duration(totals[name])}")
    return 0


def render_daily_table(
    title: str,
    days: list[date],
    totals: dict[str, dict[date, float]],
    empty_message: str,
) -> None:
    print(title)
    if not totals:
        print(empty_message)
        return

    habits = sorted(totals)
    day_width = 10
    habit_widths = {
        habit: max(8, len(habit))
        for habit in habits
    }
    header = f"{'Day'.ljust(day_width)} " + " ".join(
        habit.rjust(habit_widths[habit]) for habit in habits
    )
    print(header)
    for day in days:
        cells = [
            fmt_duration(totals[habit].get(day, 0)).rjust(habit_widths[habit])
            for habit in habits
        ]
        print(f"{day.strftime('%a %d').ljust(day_width)} " + " ".join(cells))


def cmd_week(habit_name: str | None) -> int:
    days = current_week_dates()
    start, end = date_range_bounds_utc(days)
    with connect() as conn:
        init_db(conn)
        rows = sessions_between(conn, start, end, habit_name)
        totals = daily_totals_for_dates(rows, days)

    title = f"Week {days[0].isoformat()} to {days[-1].isoformat()}"
    render_daily_table(title, days, totals, "No sessions this week")
    return 0


def cmd_month(habit_name: str | None) -> int:
    days = current_month_dates()
    start, end = date_range_bounds_utc(days)
    with connect() as conn:
        init_db(conn)
        rows = sessions_between(conn, start, end, habit_name)
        totals = daily_totals_for_dates(rows, days)

    title = f"Month {days[0].strftime('%Y-%m')}"
    render_daily_table(title, days, totals, "No sessions this month")
    return 0


def cmd_list() -> int:
    with connect() as conn:
        init_db(conn)
        rows = list_habits(conn)

    if not rows:
        print("No habits yet")
        return 0

    width = max(len(str(row["name"])) for row in rows)
    for row in rows:
        print(f"{str(row['name']).ljust(width)} {row['category']}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    raw_args = sys.argv[1:] if argv is None else argv
    if not raw_args:
        parser.print_help()
        return 0

    args = parser.parse_args(normalize_args(raw_args))

    try:
        if args.command == "init":
            return cmd_init()
        if args.command == "start":
            return cmd_start(args.habit_name, args.category, args.obs, args.obs_file)
        if args.command == "stop":
            return cmd_stop(args.habit_name, args.obs, args.obs_file)
        if args.command == "switch":
            return cmd_switch(args.habit_name, args.category, args.obs, args.obs_file)
        if args.command == "add":
            return cmd_add(args.habit_name, args.hours, args.date, args.category, args.note)
        if args.command == "status":
            return cmd_status()
        if args.command == "today":
            return cmd_today(args.habit_name)
        if args.command == "week":
            return cmd_week(args.habit_name)
        if args.command == "month":
            return cmd_month(args.habit_name)
        if args.command == "list":
            return cmd_list()
    except KeyboardInterrupt:
        print("Interrupted", file=sys.stderr)
        return 130
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    parser.print_help()
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
