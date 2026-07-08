from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class Habit:
    id: str
    name: str
    category: str
    color: str | None
    icon: str | None
    is_active: bool
    created_at: str


@dataclass(frozen=True)
class HabitSession:
    id: str
    habit_id: str
    habit_name: str
    started_at: datetime
    ended_at: datetime | None
    source: str
    note: str | None
    metadata_json: str | None
