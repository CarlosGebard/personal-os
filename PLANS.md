# Plans

## Google Sheets work-session sync

Goal: keep a Google Spreadsheet current with the global `work` session history and an automatically calculated total for today, while SQLite remains the source of truth.

Scope:
- Add an explicit `habit sync google-sheets` command, configured by environment variables and OAuth files that remain outside Git.
- Export only `work` sessions into a managed `work_sessions` tab and create a `work_today` summary tab.
- Trigger a best-effort sync after commands that create or change a `work` session; local tracking must still succeed when the network or Google is unavailable.
- While a `work` timer is active, run a single local background watcher that refreshes the managed tabs every 10 minutes and exits when `work` stops.
- Add focused unit tests using a fake Sheets gateway and document installation/configuration.

Assumptions:
- The user will provide a Google OAuth desktop-client JSON file and the target Spreadsheet ID locally.
- Google Sheets is a read-only replica for ChatGPT; manual edits to the managed tabs are overwritten by the next full sync.

Validation:
- Run the focused Google Sheets sync tests.
- Run the complete unit-test suite and `uv run python -m compileall src`.
- Smoke-test a manual sync against a temporary database; live Google authorization requires the user's credentials and is not run automatically.
- Smoke-test watcher lifecycle with a temporary database and confirm no duplicate watcher is started.

Risks:
- Google credentials and refresh tokens are sensitive, so they must live in ignored paths and never be committed.

## Health Auto Export step import

Goal: add an idempotent `habit import health` command that finds the most recent Health Auto Export JSON file and imports its daily step totals into `daily_metrics`.

Scope:
- Receive pending Taildrop files into `data/imports/taildrop/`, then search it for the most recently modified `HealthAutoExport-*.json` file and identify daily step records.
- Upsert the resulting local-calendar-day totals through the existing daily-metrics storage.
- Report imported, updated, skipped, and invalid records without changing unrelated metrics.
- Add focused tests and README usage.

Assumptions:
- Tailscale is configured with the local user as its operator so `tailscale file get` can receive Taildrop files without `sudo`.
- The exact Health Auto Export schema will be verified from a sample before implementation.
- A repeat import of the same file must be safe and produce the same stored daily totals.

Validation:
- Run focused import tests with a representative fixture.
- Run `uv run python -m compileall src`.
- Smoke-test the CLI with a temporary SQLite database and confirm `habit today`/exports show the imported steps.

Risks:
- Health export formats vary by app/version; unsupported or ambiguous records must be reported rather than guessed.

## Obsidian seven-day habit heatmap

Goal: provide an Obsidian dashboard driven by exported habit JSON data.

Scope:
- Export monthly JSON files for the imported 2026 data.
- Add a DataviewJS dashboard with a seven-day activity heatmap.
- Show a compact year-to-date `work` total.

Assumptions:
- The Obsidian vault has Dataview enabled.
- Future `habit update obsidian` runs keep the current-month JSON current.

Validation:
- Validate each generated JSON file.
- Confirm the dashboard reads the exported JSON paths and contains the expected DataviewJS block.

## Obsidian daily-note migration

Goal: import the March–June 2026 daily habit notes into SQLite using the Markdown filename as the canonical day.

Scope:
- Import `gym`, `steps`, `TalkCamera`, and `deep_work` from daily Markdown notes.
- Interpret `deep_work` values as `hours.minutes` (for example, `3.55` is 3 h 55 min) and store them as closed `work` sessions.
- Preserve each note body as the daily note.
- Replace the obsolete `workout_note` database column with `daily_note`.
- Make the importer idempotent by replacing only sessions previously created by this importer.

Assumptions:
- Only files named `YYYY-MM-DD.md` are daily notes.
- The filename, not the stale `date:` frontmatter, identifies the day.
- `TalkCamera` is the historical name for the `streamed` metric.

Validation:
- Run a dry-run against the vault.
- Import into a temporary database and verify daily-metric and `work` session totals.
- Back up the live SQLite database before importing the requested range.

Risks:
- Importing again replaces prior `obsidian_import` sessions for the same days, but does not affect manually tracked or live sessions.

## Waybar habit timer indicator

Goal: show a single Waybar icon that reflects whether any habit timer is active.

Scope:
- Add a custom Waybar module that queries the existing `habit status` command.
- Show a distinct active/inactive icon and a tooltip with the active habit name.
- Document the required Waybar configuration and styling.

Assumptions:
- `uv` is available in the Waybar process environment.
- The database remains the source of truth; no timer state is duplicated.

Steps:
- Add the module to the active Waybar configuration.
- Add focused CSS classes for active and inactive timer states.
- Document the module in the README.

Validation:
- Run the module command with and without an active habit.
- Validate the Waybar JSON configuration.

Risks:
- Waybar's environment must be able to run `uv`; the configuration uses its absolute path to avoid relying on shell PATH.

## Daily habit metrics and Obsidian export

Goal: add CLI-driven daily habit metrics for workout, steps, and streams, then export dashboard data that DataviewJS can read from an Obsidian vault.

Scope:
- Add a persistent daily metrics table keyed by local calendar date.
- Add CLI commands for workout done/not done with an optional note, steps count, stream done/not done, and sequential week/month fill including work hours.
- Add a JSON export that writes one structured monthly/range file for DataviewJS dashboards.
- Keep the Obsidian Markdown day-file export available as a secondary option.
- Keep existing timer/session tracking unchanged.
- Update README command documentation.
- Validate with compile and smoke tests against a temporary SQLite database.

Assumptions:
- `workout` maps to the Dataview-friendly `gym` boolean field on export.
- `streamed` is the canonical stream boolean field; dashboard scripts can use that instead of `TalkCamera`.
- `habit fill week|month` should only prompt for missing fields by default, including days with zero tracked work hours.
- Exported data files are generated artifacts and may overwrite existing files at the target path.

Steps:
- Extend SQLite schema with `daily_metrics`.
- Add query helpers to upsert and read daily metrics.
- Wire metric commands and sequential fill into argparse and handlers, reusing manual session insertion for work hours.
- Add JSON export helpers and keep Markdown/frontmatter export helpers.
- Document the new commands and Dataview field names.
- Run compile and CLI smoke tests.

Validation:
- `uv run python -m compileall src`
- `VICTUS_HABITS_DB=/tmp/... uv run habit init`
- `VICTUS_HABITS_DB=/tmp/... uv run habit workout --date YYYY-MM-DD --yes --note "..."`
- `VICTUS_HABITS_DB=/tmp/... uv run habit steps 10000 --date YYYY-MM-DD`
- `VICTUS_HABITS_DB=/tmp/... uv run habit stream --date YYYY-MM-DD --yes`
- `VICTUS_HABITS_DB=/tmp/... uv run habit export json /tmp/...`

Risks:
- Interactive fill is terminal-oriented and should be smoke-tested manually only where stdin behavior matters.
- Obsidian folder naming conventions vary; the export defaults should be simple and overrideable.

## Explicit habit creation and deletion

Goal: prevent typos like `habit start woek` from creating habits, add explicit creation, and allow deleting a habit with all its sessions.

Scope:
- Add `habit create <habit_name> [--category <category>]`.
- Add `habit delete <habit_name>`.
- Make `habit start`, `habit switch`, and `habit add` require an existing habit.
- Make `habit start` fail when another habit is already running; use `habit switch` for intentional replacement.
- Update README command documentation.
- Validate CLI behavior with a temporary SQLite database.

Assumptions:
- Deleting a habit removes all related `habit_sessions`.
- Delete is intentionally direct for terminal speed; data recovery is via backups/git is not involved because SQLite runtime data is ignored.
- Existing databases do not need schema migration.
- Only one active session is allowed globally.

Steps:
- Split habit lookup from habit creation in query helpers.
- Wire create/delete commands into argparse and command dispatch.
- Remove auto-create behavior from session creation paths.
- Keep active-session replacement explicit through `habit switch`.
- Update README examples and command list.
- Run compile and smoke tests.

Validation:
- `uv run python -m compileall src`
- Run one focused CLI smoke check only when the touched behavior requires it.

Risks:
- Existing scripts that relied on `habit start <new_name>` auto-creating habits must now call `habit create` once first.

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
