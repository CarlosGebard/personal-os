from __future__ import annotations

import json
import subprocess
from collections import defaultdict
from datetime import date
from pathlib import Path


HEALTH_EXPORT_PATTERN = "HealthAutoExport-*.json"


def receive_taildrop_files(target: Path) -> str | None:
    """Move pending Taildrop files to *target*, returning a failure description if any."""
    target.mkdir(parents=True, exist_ok=True)
    try:
        result = subprocess.run(
            ["tailscale", "file", "get", str(target)],
            capture_output=True,
            check=False,
            text=True,
        )
    except FileNotFoundError:
        return "Tailscale CLI was not found on PATH"

    if result.returncode == 0:
        return None
    details = (result.stderr or result.stdout).strip()
    return details or f"tailscale file get exited with status {result.returncode}"


def latest_health_export(folder: Path) -> Path | None:
    candidates = [
        path for path in folder.glob(HEALTH_EXPORT_PATTERN) if path.is_file()
    ]
    return max(candidates, key=lambda path: path.stat().st_mtime, default=None)


def load_step_totals(path: Path) -> dict[date, int]:
    """Read daily step totals from the documented Health Auto Export JSON format."""
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"Invalid JSON in {path.name}: {exc.msg}") from exc

    if not isinstance(payload, dict):
        raise ValueError(f"Unsupported Health Auto Export format in {path.name}")
    data = payload.get("data")
    metrics = data.get("metrics") if isinstance(data, dict) else None
    if not isinstance(metrics, list):
        raise ValueError(f"No health metrics found in {path.name}")

    totals: defaultdict[date, float] = defaultdict(float)
    for metric in metrics:
        if not isinstance(metric, dict) or not _is_step_metric(metric.get("name")):
            continue
        rows = metric.get("data")
        if not isinstance(rows, list):
            continue
        for row in rows:
            if not isinstance(row, dict):
                continue
            raw_day = row.get("date")
            raw_quantity = row.get("qty")
            if not isinstance(raw_day, str) or isinstance(raw_quantity, bool):
                continue
            try:
                day = date.fromisoformat(raw_day[:10])
                quantity = float(raw_quantity)
            except (TypeError, ValueError):
                continue
            if quantity < 0:
                continue
            totals[day] += quantity

    if not totals:
        raise ValueError(f"No step records found in {path.name}")
    return {day: round(total) for day, total in totals.items()}


def _is_step_metric(name: object) -> bool:
    if not isinstance(name, str):
        return False
    normalized = "".join(char for char in name.lower() if char.isalnum())
    return normalized in {"steps", "stepcount", "hkquantitytypeidentifierstepcount"}
