from __future__ import annotations

import argparse
import json
import os
import signal
import subprocess
import sys
import time
from calendar import monthrange
from datetime import date, timedelta
from pathlib import Path
from textwrap import dedent

from .db import PROJECT_ROOT, connect, get_db_path, init_db
from .health_import import latest_health_export, load_step_totals, receive_taildrop_files
from .google_sheets import configured as google_sheets_configured
from .google_sheets import sync_from_config, sync_if_configured
from .obsidian_import import import_days, load_days
from .queries import (
    active_session_duration,
    add_manual_session,
    create_habit,
    current_month_dates,
    current_week_dates,
    daily_totals_for_dates,
    daily_metrics_between,
    date_range_bounds_utc,
    delete_habit,
    duration_for_rows,
    fmt_duration,
    get_active_session,
    list_habits,
    set_steps_metric,
    set_stream_metric,
    set_workout_metric,
    sessions_between,
    sessions_today,
    start_habit,
    stop_active,
    stop_habit,
    today_bounds_utc,
)
from .timer import atomic_write, render_once


DEFAULT_OBSIDIAN_HABITS_DATA = Path(
    "/home/carlos/Documents/03-Obsidian/01-Proyects/Vida/data"
)


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
              habit create work
              habit start work
              habit work stop
              habit switch reading
              habit add work 1.5 --date 2026-07-08
              habit workout --yes --note "upper body"
              habit steps 8500
              habit stream --yes
              habit fill week
              habit export json ~/Vault/01-Proyects/Vida/data
              habit update obsidian
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
        metavar="{init,create,start,stop,switch,add,delete,workout,steps,stream,fill,import,export,update,sync,status,today,week,month,list}",
        title="commands",
        required=True,
    )

    sub.add_parser(
        "init",
        help="create the local SQLite database",
        description="Create the local SQLite database and schema if they do not exist.",
        formatter_class=HabitHelpFormatter,
    )

    create = sub.add_parser(
        "create",
        help="create a habit",
        description="Create a habit definition. Tracking commands only work with created habits.",
        epilog=dedent(
            """
            Examples:
              habit create work
              habit create reading --category learning
            """
        ).strip(),
        formatter_class=HabitHelpFormatter,
    )
    create.add_argument("habit_name", help="habit name, for example: work")
    create.add_argument("--category", default="focus", help="habit category, default: focus")

    start = sub.add_parser(
        "start",
        help="start a habit session",
        description="Start a session for an existing habit. Fails if another habit is active.",
        epilog=dedent(
            """
            Examples:
              habit create work
              habit start work
              habit start work --obs
            """
        ).strip(),
        formatter_class=HabitHelpFormatter,
    )
    start.add_argument("habit_name", help="habit name, for example: work")
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
        description="Stop the active session and immediately start another existing habit.",
        epilog=dedent(
            """
            Examples:
              habit switch reading
              habit switch work --obs
            """
        ).strip(),
        formatter_class=HabitHelpFormatter,
    )
    switch.add_argument("habit_name", help="habit name to start")
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
              habit add reading 1.5 --date 2026-07-08
              habit add exercise 0.75 --date 2026-07-08 --note "gym"
            """
        ).strip(),
        formatter_class=HabitHelpFormatter,
    )
    add.add_argument("habit_name", help="habit name, for example: work")
    add.add_argument("hours", type=float, help="hours to add, for example: 1.5")
    add.add_argument("--date", required=True, help="local date in YYYY-MM-DD format")
    add.add_argument("--note", help="optional note for the manual entry")

    delete = sub.add_parser(
        "delete",
        help="delete a habit and all its sessions",
        description="Delete a habit definition and all tracked sessions for it.",
        epilog=dedent(
            """
            Examples:
              habit delete work
              habit delete woek
            """
        ).strip(),
        formatter_class=HabitHelpFormatter,
    )
    delete.add_argument("habit_name", help="habit name to delete")

    workout = sub.add_parser(
        "workout",
        help="record whether you worked out on a day",
        description="Record the daily workout boolean and optional daily note.",
        epilog=dedent(
            """
            Examples:
              habit workout --yes
              habit workout --no --date 2026-07-08
              habit workout --yes --note "legs"
            """
        ).strip(),
        formatter_class=HabitHelpFormatter,
    )
    workout_done = workout.add_mutually_exclusive_group(required=True)
    workout_done.add_argument("--yes", action="store_true", help="mark workout as done")
    workout_done.add_argument("--no", action="store_true", help="mark workout as not done")
    workout.add_argument("--date", help="local date in YYYY-MM-DD format, default: today")
    workout.add_argument("--note", help="optional daily note")

    steps = sub.add_parser(
        "steps",
        help="record daily step count",
        description="Record the number of steps for a local calendar day.",
        epilog=dedent(
            """
            Examples:
              habit steps 8500
              habit steps 12000 --date 2026-07-08
            """
        ).strip(),
        formatter_class=HabitHelpFormatter,
    )
    steps.add_argument("count", type=int, help="step count, for example: 8500")
    steps.add_argument("--date", help="local date in YYYY-MM-DD format, default: today")

    stream = sub.add_parser(
        "stream",
        help="record whether you streamed on a day",
        description="Record the daily streamed boolean.",
        epilog=dedent(
            """
            Examples:
              habit stream --yes
              habit stream --no --date 2026-07-08
            """
        ).strip(),
        formatter_class=HabitHelpFormatter,
    )
    stream_done = stream.add_mutually_exclusive_group(required=True)
    stream_done.add_argument("--yes", action="store_true", help="mark stream as done")
    stream_done.add_argument("--no", action="store_true", help="mark stream as not done")
    stream.add_argument("--date", help="local date in YYYY-MM-DD format, default: today")

    fill = sub.add_parser(
        "fill",
        help="sequentially fill missing daily metrics",
        description="Walk through current week or month and fill missing work hours, workout, steps, and stream data.",
        epilog=dedent(
            """
            Examples:
              habit fill week
              habit fill month
              habit fill week --work-habit "deep work"
              habit fill month --all
            """
        ).strip(),
        formatter_class=HabitHelpFormatter,
    )
    fill.add_argument("range", choices=["week", "month"], help="date range to fill")
    fill.add_argument("--all", action="store_true", help="ask for every field even when data exists")
    fill.add_argument(
        "--work-habit",
        default="work",
        help="timed habit to fill in hours, default: work",
    )

    import_data = sub.add_parser(
        "import",
        help="import historical data",
        description="Import historical daily data from external sources.",
        formatter_class=HabitHelpFormatter,
    )
    import_sub = import_data.add_subparsers(dest="import_command", metavar="{health,obsidian}", required=True)
    health_import = import_sub.add_parser(
        "health",
        help="receive and import daily steps from Health Auto Export",
        description=(
            "Receive pending Taildrop files, then import steps from the newest "
            "HealthAutoExport JSON file. Received files are retained locally."
        ),
        epilog="Example:\n  habit import health",
        formatter_class=HabitHelpFormatter,
    )
    health_import.set_defaults(import_command="health")
    obsidian_import = import_sub.add_parser(
        "obsidian",
        help="import daily Markdown notes from Obsidian",
        description="Use each YYYY-MM-DD.md filename as the day and map deep_work to a habit session.",
        epilog=dedent(
            """
            Example:
              habit import obsidian ~/Vault/01-Proyects/Vida \\
                --from 2026-03-01 --to 2026-06-30 --work-habit work
            """
        ).strip(),
        formatter_class=HabitHelpFormatter,
    )
    obsidian_import.add_argument("folder", help="Obsidian Habits root folder")
    obsidian_import.add_argument("--from", dest="date_from", required=True, help="first date in YYYY-MM-DD")
    obsidian_import.add_argument("--to", dest="date_to", required=True, help="last date in YYYY-MM-DD")
    obsidian_import.add_argument("--work-habit", default="work", help="habit for deep_work, default: work")
    obsidian_import.add_argument("--dry-run", action="store_true", help="validate and show counts without writing")

    export = sub.add_parser(
        "export",
        help="export habit data",
        description="Export habit data to external formats.",
        formatter_class=HabitHelpFormatter,
    )
    export_sub = export.add_subparsers(dest="export_command", metavar="{json,obsidian}", required=True)
    json_export = export_sub.add_parser(
        "json",
        help="export one JSON data file for dashboards",
        description="Write one structured JSON file for Obsidian DataviewJS or other dashboards.",
        epilog=dedent(
            """
            Examples:
              habit export json ~/Vault/01-Proyects/Vida/data
              habit export json ~/Vault/01-Proyects/Vida/data --month 2026-07
              habit export json ~/Vault/01-Proyects/Vida/data --from 2026-07-01 --to 2026-07-12
            """
        ).strip(),
        formatter_class=HabitHelpFormatter,
    )
    json_export.add_argument("folder", help="folder where the JSON data file will be written")
    json_export.add_argument("--month", help="month to export in YYYY-MM, default: current month")
    json_export.add_argument("--from", dest="date_from", help="first local date in YYYY-MM-DD")
    json_export.add_argument("--to", dest="date_to", help="last local date in YYYY-MM-DD")
    json_export.add_argument("--output", help="custom output file path")

    obsidian = export_sub.add_parser(
        "obsidian",
        help="export daily Markdown files for Obsidian Dataview",
        description="Write one Markdown file per day with frontmatter fields for DataviewJS.",
        epilog=dedent(
            """
            Examples:
              habit export obsidian ~/Vault/01-Proyects/Vida
              habit export obsidian ~/Vault/01-Proyects/Vida --month 2026-07
            """
        ).strip(),
        formatter_class=HabitHelpFormatter,
    )
    obsidian.add_argument("folder", help="Habits root folder inside your Obsidian vault")
    obsidian.add_argument("--month", help="month to export in YYYY-MM, default: current month")
    obsidian.add_argument("--from", dest="date_from", help="first local date in YYYY-MM-DD")
    obsidian.add_argument("--to", dest="date_to", help="last local date in YYYY-MM-DD")

    update = sub.add_parser(
        "update",
        help="update generated integrations",
        description="Update generated outputs such as Obsidian dashboard data.",
        formatter_class=HabitHelpFormatter,
    )
    update_sub = update.add_subparsers(dest="update_command", metavar="{obsidian}", required=True)
    update_obsidian = update_sub.add_parser(
        "obsidian",
        help="export current completed month data to the configured Obsidian vault",
        description="Export the current month through yesterday to the configured Obsidian habits data folder.",
        epilog=dedent(
            """
            Examples:
              habit update obsidian
              habit update obsidian --month 2026-07
            """
        ).strip(),
        formatter_class=HabitHelpFormatter,
    )
    update_obsidian.add_argument("--month", help="month to export in YYYY-MM, default: current month")

    sync = sub.add_parser(
        "sync",
        help="synchronize generated external views",
        description="Synchronize read-only external replicas from the local SQLite database.",
        formatter_class=HabitHelpFormatter,
    )
    sync_sub = sync.add_subparsers(dest="sync_command", metavar="{google-sheets}", required=True)
    google_sheets = sync_sub.add_parser(
        "google-sheets",
        help="sync the global work history and today's summary to Google Sheets",
        formatter_class=HabitHelpFormatter,
    )
    google_sheets.add_argument(
        "--authorize",
        action="store_true",
        help="open a browser to authorize Google Sheets access and save a local refresh token",
    )

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


def google_sheets_work_sync_pid_file() -> Path:
    return PROJECT_ROOT / "data/google/work-sync.pid"


def google_sheets_work_sync_log_file() -> Path:
    return PROJECT_ROOT / "data/google/work-sync.log"


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


def start_google_sheets_work_sync() -> None:
    if not google_sheets_configured():
        return
    pid_path = google_sheets_work_sync_pid_file()
    existing_pid = read_pid(pid_path)
    if existing_pid and process_is_running(existing_pid):
        return
    pid_path.unlink(missing_ok=True)
    pid_path.parent.mkdir(parents=True, exist_ok=True)
    log_file = google_sheets_work_sync_log_file().open("ab")
    proc = subprocess.Popen(
        [sys.executable, "-m", "habit_tracker.google_sheets", "--watch", str(get_db_path())],
        stdin=subprocess.DEVNULL,
        stdout=log_file,
        stderr=log_file,
        start_new_session=True,
    )
    log_file.close()
    time.sleep(0.05)
    if proc.poll() is not None:
        pid_path.unlink(missing_ok=True)
        raise RuntimeError(f"Google Sheets work sync watcher failed; see {google_sheets_work_sync_log_file()}")
    pid_path.write_text(f"{proc.pid}\n", encoding="utf-8")


def stop_google_sheets_work_sync() -> None:
    pid_path = google_sheets_work_sync_pid_file()
    pid = read_pid(pid_path)
    if pid and process_is_running(pid):
        os.kill(pid, signal.SIGTERM)
    pid_path.unlink(missing_ok=True)


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
    obs: bool = False,
    obs_file: str | None = None,
) -> int:
    with connect() as conn:
        init_db(conn)
        start_habit(conn, habit_name)
        if habit_name == "work":
            sync_if_configured(conn)
    if habit_name == "work":
        start_google_sheets_work_sync()
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
        if active and active["habit_name"] == "work":
            sync_if_configured(conn)
    if active and active["habit_name"] == "work":
        stop_google_sheets_work_sync()
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
    obs: bool = False,
    obs_file: str | None = None,
) -> int:
    with connect() as conn:
        init_db(conn)
        active_before = get_active_session(conn)
        start_habit(conn, habit_name, stop_existing=True)
        if habit_name == "work" or (active_before and active_before["habit_name"] == "work"):
            sync_if_configured(conn)
    if active_before and active_before["habit_name"] == "work" and habit_name != "work":
        stop_google_sheets_work_sync()
    if habit_name == "work":
        start_google_sheets_work_sync()
    print(f"Switched to: {habit_name}")
    if obs:
        path = start_obs_live(habit_name, obs_file)
        print(f"OBS live: {path}")
    return 0


def cmd_add(
    habit_name: str,
    hours: float,
    raw_date: str,
    note: str | None,
) -> int:
    day = date.fromisoformat(raw_date)
    with connect() as conn:
        init_db(conn)
        add_manual_session(conn, habit_name, hours, day, note=note)
        if habit_name == "work":
            sync_if_configured(conn)
    print(f"Added: {habit_name} {fmt_duration(hours * 3600)} on {day.isoformat()}")
    return 0


def parse_local_date(raw_date: str | None) -> date:
    if raw_date:
        return date.fromisoformat(raw_date)
    return date.today()


def bool_label(value: bool) -> str:
    return "yes" if value else "no"


def prompt_bool(prompt: str) -> bool | None:
    while True:
        value = input(f"{prompt} [y/n/skip]: ").strip().lower()
        if value in {"", "s", "skip"}:
            return None
        if value in {"y", "yes", "si", "s"}:
            return True
        if value in {"n", "no"}:
            return False
        print("Use y, n, or skip.")


def prompt_int(prompt: str) -> int | None:
    while True:
        value = input(f"{prompt} [number/skip]: ").strip().lower()
        if value in {"", "s", "skip"}:
            return None
        try:
            parsed = int(value)
        except ValueError:
            print("Use a whole number or skip.")
            continue
        if parsed < 0:
            print("Steps must be 0 or greater.")
            continue
        return parsed


def prompt_float(prompt: str) -> float | None:
    while True:
        value = input(f"{prompt} [hours/skip]: ").strip().lower()
        if value in {"", "s", "skip"}:
            return None
        try:
            parsed = float(value)
        except ValueError:
            print("Use decimal hours or skip.")
            continue
        if parsed < 0:
            print("Hours must be 0 or greater.")
            continue
        if parsed > 24:
            print("Hours must be 24 or less.")
            continue
        return parsed


def metric_missing(row: object | None, field: str) -> bool:
    if row is None:
        return True
    return row[field] is None


def days_for_fill(range_name: str) -> list[date]:
    if range_name == "week":
        return current_week_dates()
    return current_month_dates()


def cmd_workout(raw_date: str | None, done: bool, note: str | None) -> int:
    day = parse_local_date(raw_date)
    with connect() as conn:
        init_db(conn)
        set_workout_metric(conn, day, done, note)
    print(f"Workout {bool_label(done)} on {day.isoformat()}")
    return 0


def cmd_steps(raw_date: str | None, count: int) -> int:
    day = parse_local_date(raw_date)
    with connect() as conn:
        init_db(conn)
        set_steps_metric(conn, day, count)
    print(f"Steps {count} on {day.isoformat()}")
    return 0


def cmd_stream(raw_date: str | None, streamed: bool) -> int:
    day = parse_local_date(raw_date)
    with connect() as conn:
        init_db(conn)
        set_stream_metric(conn, day, streamed)
    print(f"Stream {bool_label(streamed)} on {day.isoformat()}")
    return 0


def cmd_fill(range_name: str, include_all: bool, work_habit: str) -> int:
    days = days_for_fill(range_name)
    start, end = date_range_bounds_utc(days)
    with connect() as conn:
        init_db(conn)
        existing = daily_metrics_between(conn, days[0], days[-1])
        work_rows = sessions_between(conn, start, end, work_habit)
        work_totals = daily_totals_for_dates(work_rows, days).get(work_habit, {})

        for day in days:
            row = existing.get(day)
            print(day.isoformat())
            if include_all or work_totals.get(day, 0) == 0:
                work_hours = prompt_float(f"  {work_habit} hours")
                if work_hours:
                    add_manual_session(conn, work_habit, work_hours, day, note="fill")
            if include_all or metric_missing(row, "workout"):
                workout = prompt_bool("  workout")
                if workout is not None:
                    note = input("  workout note [optional]: ").strip() or None
                    set_workout_metric(conn, day, workout, note)
            if include_all or metric_missing(row, "steps"):
                steps = prompt_int("  steps")
                if steps is not None:
                    set_steps_metric(conn, day, steps)
            if include_all or metric_missing(row, "streamed"):
                streamed = prompt_bool("  stream")
                if streamed is not None:
                    set_stream_metric(conn, day, streamed)

    print(f"Filled {range_name}")
    return 0


def cmd_import_obsidian(
    folder: str,
    raw_from: str,
    raw_to: str,
    work_habit: str,
    dry_run: bool,
) -> int:
    start = date.fromisoformat(raw_from)
    end = date.fromisoformat(raw_to)
    if end < start:
        raise ValueError("Import end date cannot be before start date")
    days = load_days(Path(folder).expanduser(), start, end)
    sessions = sum(1 for item in days if item.work_minutes)
    minutes = sum(item.work_minutes for item in days)
    if dry_run:
        print(
            f"Validated {len(days)} daily notes: {sessions} {work_habit} sessions "
            f"({fmt_duration(minutes * 60)}). No data written."
        )
        return 0
    with connect() as conn:
        init_db(conn)
        imported_days, imported_sessions = import_days(conn, work_habit, days)
    print(
        f"Imported {imported_days} daily notes and {imported_sessions} {work_habit} sessions "
        f"({fmt_duration(minutes * 60)})."
    )
    return 0


def cmd_import_health() -> int:
    inbox = PROJECT_ROOT / "data/imports/taildrop"
    receive_error = receive_taildrop_files(inbox)
    source = latest_health_export(inbox)
    if not source:
        if receive_error:
            raise RuntimeError(
                "Could not receive Taildrop files and no cached Health Auto Export file exists: "
                f"{receive_error}"
            )
        raise RuntimeError(f"No {inbox / 'HealthAutoExport-*.json'} file found")

    totals = load_step_totals(source)
    created = updated = unchanged = 0
    with connect() as conn:
        init_db(conn)
        existing = daily_metrics_between(conn, min(totals), max(totals))
        for day, steps in sorted(totals.items()):
            row = existing.get(day)
            previous = int(row["steps"]) if row and row["steps"] is not None else None
            if previous == steps:
                unchanged += 1
                continue
            set_steps_metric(conn, day, steps)
            if previous is None:
                created += 1
            else:
                updated += 1

    if receive_error:
        print(f"Taildrop receive skipped: {receive_error}")
    print(
        f"Imported steps from {source.name}: {created} created, {updated} updated, "
        f"{unchanged} unchanged."
    )
    return 0


def cmd_sync_google_sheets(authorize: bool) -> int:
    with connect() as conn:
        init_db(conn)
        count = sync_from_config(conn, authorize=authorize)
    print(f"Google Sheets synced: {count} work sessions")
    return 0


def cmd_create(habit_name: str, category: str) -> int:
    with connect() as conn:
        init_db(conn)
        create_habit(conn, habit_name, category)
    print(f"Created: {habit_name}")
    return 0


def cmd_delete(habit_name: str) -> int:
    with connect() as conn:
        init_db(conn)
        deleted_sessions = delete_habit(conn, habit_name)
    print(f"Deleted: {habit_name} ({deleted_sessions} sessions)")
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


def parse_export_days(
    raw_month: str | None,
    raw_from: str | None,
    raw_to: str | None,
) -> list[date]:
    today = date.today()
    yesterday = today - timedelta(days=1)
    if raw_from or raw_to:
        if not raw_from or not raw_to:
            raise ValueError("Use --from and --to together")
        start = date.fromisoformat(raw_from)
        end = date.fromisoformat(raw_to)
    else:
        if raw_month:
            year, month = raw_month.split("-", maxsplit=1)
            start = date(int(year), int(month), 1)
            end = date(int(year), int(month), monthrange(int(year), int(month))[1])
            if start <= today <= end:
                end = yesterday
        else:
            start = today.replace(day=1)
            end = yesterday

    if end < start:
        raise ValueError("Export end date cannot be before start date")

    days = []
    current = start
    while current <= end:
        days.append(current)
        current += timedelta(days=1)
    return days


def month_folder_name(day: date) -> str:
    names = {
        1: "Enero",
        2: "Febrero",
        3: "Marzo",
        4: "Abril",
        5: "Mayo",
        6: "Junio",
        7: "Julio",
        8: "Agosto",
        9: "Septiembre",
        10: "Octubre",
        11: "Noviembre",
        12: "Diciembre",
    }
    return f"{names[day.month]}-{day.year}"


def frontmatter_value(value: object) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int):
        return str(value)
    text = str(value).replace('"', '\\"')
    return f'"{text}"'


def field_name(name: str) -> str:
    cleaned = []
    for char in name.strip().lower():
        if char.isalnum():
            cleaned.append(char)
        elif cleaned and cleaned[-1] != "_":
            cleaned.append("_")
    return "".join(cleaned).strip("_") or "habit"


def seconds_to_h_mm(seconds: float) -> str:
    total_minutes = round(seconds / 60)
    hours = total_minutes // 60
    minutes = total_minutes % 60
    return f"{hours}.{minutes:02d}"


def seconds_to_hours(seconds: float) -> float:
    return round(seconds / 3600, 4)


def export_month_slug(days: list[date]) -> str:
    first = days[0]
    last = days[-1]
    if first.year == last.year and first.month == last.month:
        return first.strftime("%Y-%m")
    return f"{first.isoformat()}_{last.isoformat()}"


def build_json_export_rows(
    days: list[date],
    metrics: dict[date, object],
    totals: dict[str, dict[date, float]],
) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for day in days:
        metric = metrics.get(day)
        row: dict[str, object] = {
            "date": day.isoformat(),
            "gym": bool(metric["workout"]) if metric and metric["workout"] is not None else None,
            "daily_note": metric["daily_note"] if metric else None,
            "steps": int(metric["steps"]) if metric and metric["steps"] is not None else None,
            "streamed": bool(metric["streamed"]) if metric and metric["streamed"] is not None else None,
        }
        for habit_name, habit_totals in sorted(totals.items()):
            row[field_name(habit_name)] = seconds_to_hours(habit_totals.get(day, 0))
        rows.append(row)
    return rows


def cmd_export_json(
    folder: str,
    raw_month: str | None,
    raw_from: str | None,
    raw_to: str | None,
    raw_output: str | None,
) -> int:
    days = parse_export_days(raw_month, raw_from, raw_to)
    start, end = date_range_bounds_utc(days)
    with connect() as conn:
        init_db(conn)
        session_rows = sessions_between(conn, start, end)
        totals = daily_totals_for_dates(session_rows, days)
        metrics = daily_metrics_between(conn, days[0], days[-1])

    rows = build_json_export_rows(days, metrics, totals)
    target = Path(raw_output).expanduser() if raw_output else (
        Path(folder).expanduser() / f"habits-{export_month_slug(days)}.json"
    )
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(rows, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"Exported {len(rows)} rows to {target}")
    return 0


def cmd_update_obsidian(raw_month: str | None) -> int:
    return cmd_export_json(
        str(DEFAULT_OBSIDIAN_HABITS_DATA),
        raw_month,
        None,
        None,
        None,
    )


def write_obsidian_day(
    root: Path,
    day: date,
    metric: object | None,
    totals: dict[str, dict[date, float]],
) -> Path:
    target = root / month_folder_name(day) / f"{day.isoformat()}.md"
    target.parent.mkdir(parents=True, exist_ok=True)

    fields: dict[str, object] = {
        "date": day.isoformat(),
        "gym": bool(metric["workout"]) if metric and metric["workout"] is not None else None,
        "daily_note": metric["daily_note"] if metric else None,
        "steps": int(metric["steps"]) if metric and metric["steps"] is not None else None,
        "streamed": bool(metric["streamed"]) if metric and metric["streamed"] is not None else None,
    }
    for habit_name, habit_totals in sorted(totals.items()):
        seconds = habit_totals.get(day)
        if seconds:
            fields[field_name(habit_name)] = seconds_to_h_mm(seconds)

    lines = ["---"]
    lines.extend(f"{key}: {frontmatter_value(value)}" for key, value in fields.items())
    lines.extend(["---", "", f"# {day.isoformat()}", ""])
    target.write_text("\n".join(lines), encoding="utf-8")
    return target


def cmd_export_obsidian(
    folder: str,
    raw_month: str | None,
    raw_from: str | None,
    raw_to: str | None,
) -> int:
    days = parse_export_days(raw_month, raw_from, raw_to)
    start, end = date_range_bounds_utc(days)
    root = Path(folder).expanduser()
    with connect() as conn:
        init_db(conn)
        session_rows = sessions_between(conn, start, end)
        totals = daily_totals_for_dates(session_rows, days)
        metrics = daily_metrics_between(conn, days[0], days[-1])

    written = [
        write_obsidian_day(root, day, metrics.get(day), totals)
        for day in days
    ]
    print(f"Exported {len(written)} files to {root}")
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
        if args.command == "create":
            return cmd_create(args.habit_name, args.category)
        if args.command == "start":
            return cmd_start(args.habit_name, args.obs, args.obs_file)
        if args.command == "stop":
            return cmd_stop(args.habit_name, args.obs, args.obs_file)
        if args.command == "switch":
            return cmd_switch(args.habit_name, args.obs, args.obs_file)
        if args.command == "add":
            return cmd_add(args.habit_name, args.hours, args.date, args.note)
        if args.command == "delete":
            return cmd_delete(args.habit_name)
        if args.command == "workout":
            return cmd_workout(args.date, args.yes, args.note)
        if args.command == "steps":
            return cmd_steps(args.date, args.count)
        if args.command == "stream":
            return cmd_stream(args.date, args.yes)
        if args.command == "fill":
            return cmd_fill(args.range, args.all, args.work_habit)
        if args.command == "import" and args.import_command == "obsidian":
            return cmd_import_obsidian(
                args.folder,
                args.date_from,
                args.date_to,
                args.work_habit,
                args.dry_run,
            )
        if args.command == "import" and args.import_command == "health":
            return cmd_import_health()
        if args.command == "export" and args.export_command == "json":
            return cmd_export_json(
                args.folder,
                args.month,
                args.date_from,
                args.date_to,
                args.output,
            )
        if args.command == "export" and args.export_command == "obsidian":
            return cmd_export_obsidian(args.folder, args.month, args.date_from, args.date_to)
        if args.command == "update" and args.update_command == "obsidian":
            return cmd_update_obsidian(args.month)
        if args.command == "sync" and args.sync_command == "google-sheets":
            return cmd_sync_google_sheets(args.authorize)
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
