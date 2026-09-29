from __future__ import annotations

import os
import sqlite3
import sys
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Protocol

from .db import PROJECT_ROOT, connect, init_db
from .queries import (
    duration_for_rows,
    get_active_session,
    parse_dt,
    sessions_today,
    today_bounds_utc,
)

ENV_SPREADSHEET_ID = "VICTUS_GOOGLE_SHEETS_ID"
ENV_CLIENT_SECRET_FILE = "VICTUS_GOOGLE_OAUTH_CLIENT_FILE"
ENV_TOKEN_FILE = "VICTUS_GOOGLE_OAUTH_TOKEN_FILE"
WORK_SESSIONS_TAB = "work_sessions"
WORK_TODAY_TAB = "work_today"
SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]
WORK_SYNC_INTERVAL_SECONDS = 10 * 60


@dataclass(frozen=True)
class GoogleSheetsConfig:
    spreadsheet_id: str
    client_secret_file: Path
    token_file: Path


class SheetsGateway(Protocol):
    def ensure_tabs(self, names: list[str]) -> None: ...

    def set_minute_recalculation(self) -> None: ...

    def replace_values(self, tab_name: str, values: list[list[object]], value_input: str) -> None: ...


def configured() -> bool:
    return bool(os.environ.get(ENV_SPREADSHEET_ID))


def get_config() -> GoogleSheetsConfig:
    spreadsheet_id = os.environ.get(ENV_SPREADSHEET_ID, "").strip()
    if not spreadsheet_id:
        raise ValueError(f"Set {ENV_SPREADSHEET_ID} to the target Google Spreadsheet ID")

    client_secret = os.environ.get(ENV_CLIENT_SECRET_FILE, "").strip()
    client_secret_path = (
        Path(client_secret).expanduser()
        if client_secret
        else PROJECT_ROOT / "data/google/client.google-oauth.json"
    )

    token_file = os.environ.get(ENV_TOKEN_FILE, "").strip()
    if not token_file:
        token_file = str(PROJECT_ROOT / "data/google/google-sheets-token.json")

    if not client_secret_path.is_file():
        raise ValueError(
            "Google OAuth client file not found: "
            f"{client_secret_path}. Place it there or set {ENV_CLIENT_SECRET_FILE}."
        )
    return GoogleSheetsConfig(
        spreadsheet_id=spreadsheet_id,
        client_secret_file=client_secret_path,
        token_file=Path(token_file).expanduser(),
    )


def local_timestamp(value: str | None) -> str:
    if not value:
        return ""
    return parse_dt(value).astimezone().strftime("%Y-%m-%d %H:%M:%S")


def work_session_values(conn: sqlite3.Connection) -> list[list[object]]:
    rows = conn.execute(
        """
        SELECT hs.id, hs.started_at, hs.ended_at, hs.source, hs.note, hs.updated_at
        FROM habit_sessions hs
        JOIN habits h ON h.id = hs.habit_id
        WHERE h.name = 'work'
        ORDER BY hs.started_at ASC, hs.id ASC
        """
    ).fetchall()
    values: list[list[object]] = [
        [
            "session_id",
            "started_at_local",
            "ended_at_local",
            "duration_minutes",
            "source",
            "note",
            "updated_at_local",
        ]
    ]
    for row in rows:
        started = parse_dt(str(row["started_at"]))
        ended_raw = row["ended_at"]
        ended = parse_dt(str(ended_raw)) if ended_raw else None
        minutes = round((ended - started).total_seconds() / 60, 2) if ended else ""
        values.append(
            [
                str(row["id"]),
                local_timestamp(str(row["started_at"])),
                local_timestamp(str(ended_raw)) if ended_raw else "",
                minutes,
                str(row["source"]),
                str(row["note"] or ""),
                local_timestamp(str(row["updated_at"])),
            ]
        )
    return values


def work_today_values(conn: sqlite3.Connection, synced_at: datetime | None = None) -> list[list[object]]:
    synced_at = synced_at or datetime.now().astimezone()
    start, end = today_bounds_utc()
    rows = sessions_today(conn, "work")
    completed_rows = [row for row in rows if row["ended_at"] is not None]
    completed_seconds = duration_for_rows(completed_rows, start, end).get("work", 0.0)
    active = next((row for row in rows if row["ended_at"] is None), None)
    active_started = ""
    if active:
        active_started = max(parse_dt(str(active["started_at"])), start).astimezone().strftime(
            "%Y-%m-%d %H:%M:%S"
        )

    return [
        [
            "day",
            "completed_minutes",
            "worked_minutes",
            "worked_hours",
            "completed_sessions",
            "active_started_at_local",
            "last_synced_at_local",
        ],
        [
            synced_at.date().isoformat(),
            round(completed_seconds / 60, 2),
            '=B2+IF(F2="",0,MAX(0,(NOW()-VALUE(F2))*1440))',
            "=C2/60",
            len(completed_rows),
            active_started,
            synced_at.strftime("%Y-%m-%d %H:%M:%S"),
        ],
    ]


class GoogleApiGateway:
    def __init__(self, config: GoogleSheetsConfig, authorize: bool = False) -> None:
        self.config = config
        self.service = self._build_service(authorize)
        self._tabs: set[str] | None = None

    def _build_service(self, authorize: bool):
        try:
            from google.auth.transport.requests import Request
            from google.oauth2.credentials import Credentials
            from google_auth_oauthlib.flow import InstalledAppFlow
            from googleapiclient.discovery import build
        except ImportError as exc:
            raise RuntimeError(
                "Google Sheets support is not installed. Run `uv sync` or reinstall the project."
            ) from exc

        credentials = None
        if self.config.token_file.is_file():
            credentials = Credentials.from_authorized_user_file(self.config.token_file, SCOPES)
        if credentials and credentials.expired and credentials.refresh_token:
            credentials.refresh(Request())
        if not credentials or not credentials.valid:
            if not authorize:
                raise RuntimeError(
                    "Google authorization is required. Run `habit sync google-sheets --authorize` once."
                )
            flow = InstalledAppFlow.from_client_secrets_file(
                self.config.client_secret_file, SCOPES
            )
            credentials = flow.run_local_server(port=0)

        self.config.token_file.parent.mkdir(parents=True, exist_ok=True)
        self.config.token_file.write_text(credentials.to_json(), encoding="utf-8")
        self.config.token_file.chmod(0o600)
        return build("sheets", "v4", credentials=credentials, cache_discovery=False)

    def ensure_tabs(self, names: list[str]) -> None:
        if self._tabs is None:
            document = self.service.spreadsheets().get(
                spreadsheetId=self.config.spreadsheet_id,
                fields="sheets.properties.title",
            ).execute()
            self._tabs = {
                sheet["properties"]["title"] for sheet in document.get("sheets", [])
            }
        missing = [name for name in names if name not in self._tabs]
        if missing:
            self.service.spreadsheets().batchUpdate(
                spreadsheetId=self.config.spreadsheet_id,
                body={"requests": [{"addSheet": {"properties": {"title": name}}} for name in missing]},
            ).execute()
            self._tabs.update(missing)

    def set_minute_recalculation(self) -> None:
        self.service.spreadsheets().batchUpdate(
            spreadsheetId=self.config.spreadsheet_id,
            body={
                "requests": [
                    {
                        "updateSpreadsheetProperties": {
                            "properties": {"autoRecalc": "MINUTE"},
                            "fields": "autoRecalc",
                        }
                    }
                ]
            },
        ).execute()

    def replace_values(self, tab_name: str, values: list[list[object]], value_input: str) -> None:
        self.service.spreadsheets().values().clear(
            spreadsheetId=self.config.spreadsheet_id,
            range=f"{tab_name}!A:Z",
            body={},
        ).execute()
        self.service.spreadsheets().values().update(
            spreadsheetId=self.config.spreadsheet_id,
            range=f"{tab_name}!A1",
            valueInputOption=value_input,
            body={"values": values},
        ).execute()


def sync_work_sessions(
    conn: sqlite3.Connection,
    gateway: SheetsGateway,
) -> int:
    gateway.ensure_tabs([WORK_SESSIONS_TAB, WORK_TODAY_TAB])
    gateway.set_minute_recalculation()
    sessions = work_session_values(conn)
    gateway.replace_values(WORK_SESSIONS_TAB, sessions, "RAW")
    gateway.replace_values(WORK_TODAY_TAB, work_today_values(conn), "USER_ENTERED")
    return len(sessions) - 1


def sync_from_config(conn: sqlite3.Connection, authorize: bool = False) -> int:
    return sync_work_sessions(conn, GoogleApiGateway(get_config(), authorize=authorize))


def sync_if_configured(conn: sqlite3.Connection) -> None:
    if not configured():
        return
    try:
        count = sync_from_config(conn)
        print(f"Google Sheets synced: {count} work sessions")
    except Exception as exc:
        print(f"Warning: Google Sheets sync failed: {exc}", file=sys.stderr)


def watch_active_work_sync(db_path: Path, interval_seconds: int = WORK_SYNC_INTERVAL_SECONDS) -> None:
    """Refresh Google Sheets periodically until work is no longer the active habit."""
    while True:
        time.sleep(interval_seconds)
        with connect(db_path) as conn:
            init_db(conn)
            active = get_active_session(conn)
            if not active or active["habit_name"] != "work":
                return
            sync_if_configured(conn)


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if len(args) != 2 or args[0] != "--watch":
        raise SystemExit("Usage: python -m habit_tracker.google_sheets --watch <database-path>")
    watch_active_work_sync(Path(args[1]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
