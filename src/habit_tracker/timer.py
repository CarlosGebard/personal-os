from __future__ import annotations

import argparse
import os
import time
from pathlib import Path

from .db import connect, get_db_path, init_db
from .queries import fmt_duration, timer_state


def label_for(habit_name: str) -> str:
    return habit_name.replace("_", " ").replace("-", " ").title()


def build_text(habit_name: str, total: float, session: float, active: bool) -> str:
    status = "●" if active else "⏸"
    return f"{label_for(habit_name)} Hoy {fmt_duration(total)} | Session {status} {fmt_duration(session)}"


def atomic_write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)


def render_once(habit_name: str) -> str:
    if not get_db_path().exists():
        return build_text(habit_name, 0, 0, False)

    with connect() as conn:
        init_db(conn)
        total, session, active = timer_state(conn, habit_name)
    return build_text(habit_name, total, session, active)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="habit-timer", description="Render a habit timer to a text file")
    parser.add_argument("habit_name", nargs="?", default="work")
    parser.add_argument("output_file", nargs="?", default=None)
    parser.add_argument("--interval", type=float, default=1.0)
    parser.add_argument("--once", action="store_true", help="Render once and exit")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    output_file = args.output_file or f"/dev/shm/habits/{args.habit_name}.txt"
    output_path = Path(output_file)

    last_text: str | None = None

    while True:
        text = render_once(args.habit_name)
        if text != last_text:
            atomic_write(output_path, text)
            last_text = text

        if args.once:
            print(text)
            return 0

        time.sleep(max(0.2, args.interval))


if __name__ == "__main__":
    raise SystemExit(main())
