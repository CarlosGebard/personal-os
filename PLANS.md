# Plans

## Manual habit time entries and GitHub publish

Goal: let the CLI add manual hours to any habit on any local calendar day, then publish the repository to `CarlosGebard/personal-os`.

Scope:
- Add `habit add <habit_name> <hours> --date YYYY-MM-DD`.
- Store manual time as closed `habit_sessions` rows using the existing totals pipeline.
- Update README command documentation.
- Validate the CLI against a temporary SQLite database.
- Commit and push the project to the GitHub repository.

Assumptions:
- The provided date is interpreted in the system local timezone.
- Manual entries can overlap existing sessions because totals are event-based and this is an explicit adjustment.
- Hours are decimal-friendly, for example `1.5` for 1 hour 30 minutes.

Steps:
- Add a query helper that creates a closed manual session for the requested local day.
- Add parser and command handler for `habit add`.
- Document usage and examples in `README.md`.
- Run compile and smoke-test commands.
- Add the GitHub remote, commit, and push.

Validation:
- `uv run python -m compileall src`
- `VICTUS_HABITS_DB=/tmp/... uv run habit init`
- `VICTUS_HABITS_DB=/tmp/... uv run habit add work 1.5 --date YYYY-MM-DD`
- `VICTUS_HABITS_DB=/tmp/... uv run habit today work`

Risks:
- Publishing requires network access and GitHub credentials configured locally.

## Habit weekly and monthly summaries

Goal: add CLI summaries that show how much time was tracked for each habit on each day of the current week and current month.

Scope:
- Add `habit week [habit_name]`.
- Add `habit month [habit_name]`.
- Reuse SQLite session data and local timezone day boundaries.
- Render days as rows and habits as columns.
- Show only days up to the current local date.
- Update README command documentation.

Assumptions:
- Week starts on Monday in the system local timezone.
- Month means the current local calendar month through today.
- Session timestamps remain stored in UTC and are clipped into local-day buckets at read time.

Steps:
- Add range-boundary and daily aggregation helpers in `src/habit_tracker/queries.py`.
- Add parser entries, command handlers, and tabular rendering in `src/habit_tracker/cli.py`.
- Document the new commands in `README.md`.
- Validate with compile checks and CLI smoke tests against a temporary database.

Validation:
- `uv run python -m compileall src`
- `VICTUS_HABITS_DB=/tmp/... uv run habit init`
- `VICTUS_HABITS_DB=/tmp/... uv run habit week`
- `VICTUS_HABITS_DB=/tmp/... uv run habit month`

Risks:
- Monthly output can be wide in narrow terminals because it has one column per day.

## Habit tracker project-local data

Goal: keep the habit tracker database inside the project under `data/`, ignore that runtime data in Git, remove old Timewarrior scripts, and make daily totals follow the local timezone.

Scope:
- Change the default SQLite path.
- Update local-day query boundaries.
- Remove legacy shell scripts.
- Initialize Git for `personal-os`.

Assumptions:
- Session timestamps stay stored in UTC.
- The system local timezone is the source of truth for "today".
- `data/` contains runtime state and should not be committed.

Steps:
- Update `src/habit_tracker/db.py` default path.
- Update `src/habit_tracker/queries.py` to calculate local day boundaries and clip daily totals.
- Update README and `.gitignore`.
- Delete legacy Timewarrior scripts.
- Initialize Git and validate the CLI.

Validation:
- `habit init`
- `habit start work`
- `habit today work`
- `habit-timer work ... --once`
- `habit stop`

Risks:
- Existing data in `~/.local/share/victus-habits/tracker.db` will not move automatically.
