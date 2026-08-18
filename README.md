# CLI Engage Roster & Account Manager

A menu-driven command-line tool that converts effective-dated Skyward employee
assignment reports into validated [CLI Engage](https://www.cliengage.com/)
bulk-upload transaction files (Insert/Update/Delete/Transfer), with saved
templates, column-mapping memory, and day-over-day change detection.

Districts running Skyward as their system of record and CLI Engage as a
downstream application need a repeatable way to keep account access current:
new hires need accounts, campus transfers need to move access from the old
campus to the new one, and terminations need to be removed — every day,
without a human re-deriving the diff by hand. This tool automates that diff.

## What it does

Given a Skyward assignment export (CSV or XLSX) and a target role (for
example, `School Specialist`), the importer:

- Auto-detects the report's columns against a configurable candidate list
  (falling back to an interactive picker when a column can't be matched),
  and remembers the mapping for next time.
- Computes who is *active* in the target role on a given date, using each
  row's effective start/end dates.
- Diffs today's active set against yesterday's to produce `I` (insert),
  `U` (update — info changed or moved between campuses), `D` (delete), and
  `T` (transfer) rows in the exact column layout CLI Engage expects.
- Detects missed days (for example, after a long weekend or an outage) and
  offers to catch up the diff across every missed date, not just today's.
- Saves reusable **profiles** (role, column mapping, standardized input
  filename) and **templates** (output column layout, per-app defaults) so a
  recurring run is a single menu selection.

## Getting started

**Requirements:** Python 3.8+ and the packages in `requirements.txt`
(`pandas`; installed automatically by the launcher scripts, or manually with
`pip install -r requirements.txt`).

```bash
# macOS / Linux
bash LAUNCH_MAC_LINUX.sh

# Windows
LAUNCH_WINDOWS.bat
```

Or run the script directly once dependencies are installed:

```bash
python skyward_to_cliengage.py [--date YYYY-MM-DD] [--catchup]
```

Drop your Skyward export (CSV/XLSX) in the same folder and follow the menu.
`--date` treats a specific date as "today," which is useful for testing or
backfilling; `--catchup` skips the "process missed days?" prompt and always
includes them.

## Try it with sample data

`sample_data/sample_skyward_export.csv` is a synthetic six-employee export
(fake names, a fictional "Riverbend ISD," and `example.org` emails — no real
district data) with a mix of a role match, a non-matching role, and a campus
transfer, so you can see the daily-delta and full-export logic run without
pointing the tool at anything real:

```bash
cp sample_data/sample_skyward_export.csv .
python skyward_to_cliengage.py --date 2025-10-16
```

## Output format

Generated files use the `Action,Transaction_Type,Community_Name,...` column
layout CLI Engage's School Specialist bulk-upload template expects (see
`DEFAULT_TEMPLATE` in `skyward_to_cliengage.py`). The **Manage templates**
menu lets you clone and edit that layout for other CLI Engage transaction
types without touching code.

## Tests

```bash
pip install pytest
python -m pytest tests/
```

The test suite covers the pure data-transformation logic — date parsing,
active-role-on-a-date computation, fuzzy role matching, and daily-delta row
generation (including the campus-transfer case) — run against the sample
export in `sample_data/`. It does not attempt to test the interactive menu
loops.

## A note on data

This repository and its sample data contain no real student records,
employee records, or district-specific defaults. Point it at your own
Skyward export locally; nothing here assumes a particular district's column
names, role names, or CLI Engage community/school IDs beyond the generic
candidates listed in `DEFAULT_TEMPLATE`.

## License

MIT — see [LICENSE](LICENSE).
