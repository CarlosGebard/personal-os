# ADR 0001: Store a daily note separately from workout status

## Context

Historical Obsidian habit notes contain one free-form note per calendar day. The existing `workout_note` field incorrectly implies that this text belongs only to a workout.

## Decision

Replace `workout_note` with `daily_note` in `daily_metrics`. During initialization, existing `workout_note` values are copied into `daily_note`, then SQLite rebuilds the table without the obsolete column. The `habit workout --note` option now records the daily note for backwards-compatible CLI use. Obsidian imports write note bodies to `daily_note`.

The importer treats a daily Markdown filename as the source of truth for its date and records imported work sessions with source `obsidian_import`. Re-importing replaces only those imported sessions.

## Consequences

Exports use the `daily_note` field. The database migration removes the obsolete `workout_note` column after preserving its values.
