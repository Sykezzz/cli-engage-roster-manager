"""
Unit tests for skyward_to_cliengage.py.

These tests exercise the pure data-transformation logic (date parsing,
role matching, column resolution, and daily-delta computation) without
touching any interactive menu code or real Skyward/CLIEngage data.

Run with:  python -m pytest tests/
"""

import sys
from datetime import date
from pathlib import Path

import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import skyward_to_cliengage as sc  # noqa: E402


# ── parse_date / is_active_on ────────────────────────────────────────────────

@pytest.mark.parametrize(
    "raw,expected",
    [
        ("08/01/2025", date(2025, 8, 1)),
        ("2025-08-01", date(2025, 8, 1)),
        ("08-01-2025", date(2025, 8, 1)),
        ("", None),
        (None, None),
        ("nan", None),
    ],
)
def test_parse_date(raw, expected):
    assert sc.parse_date(raw) == expected


def test_is_active_on_open_ended():
    start = date(2025, 8, 1)
    assert sc.is_active_on(start, None, date(2026, 1, 1)) is True
    assert sc.is_active_on(start, None, date(2025, 7, 1)) is False


def test_is_active_on_bounded_range():
    start, end = date(2025, 8, 1), date(2025, 10, 15)
    assert sc.is_active_on(start, end, date(2025, 9, 1)) is True
    assert sc.is_active_on(start, end, date(2025, 10, 15)) is True
    assert sc.is_active_on(start, end, date(2025, 10, 16)) is False


# ── role matching ─────────────────────────────────────────────────────────────

def test_role_matches_exact():
    assert sc.role_matches("School Specialist", ["School Specialist"]) is True
    assert sc.role_matches("Classroom Teacher", ["School Specialist"]) is False


def test_role_matches_fuzzy():
    roles = ["School Specialist"]
    assert sc.role_matches("school specialist (interim)", roles, fuzzy=True) is True
    assert sc.role_matches("bus driver", roles, fuzzy=True) is False


def test_fuzzy_match_text_threshold():
    assert sc.fuzzy_match_text("school specialist", "school specialist campus lead")
    assert not sc.fuzzy_match_text("school specialist", "bus driver")


# ── normalize / payload_differs ────────────────────────────────────────────────

def test_normalize_handles_nan_like_values():
    assert sc.normalize("nan") == ""
    assert sc.normalize(None) == ""
    assert sc.normalize("  Ana  ") == "Ana"


def test_payload_differs_detects_email_change():
    a = {"School_Specialist_Primary_Email": "old@example.org"}
    b = {"School_Specialist_Primary_Email": "new@example.org"}
    assert sc.payload_differs(a, b) is True
    assert sc.payload_differs(a, dict(a)) is False


# ── column resolution against the sample export ───────────────────────────────

SAMPLE_CSV = Path(__file__).resolve().parent.parent / "sample_data" / "sample_skyward_export.csv"


@pytest.fixture
def sample_df():
    df = pd.read_csv(SAMPLE_CSV, dtype=str)
    df.columns = df.columns.str.strip()
    return df


def test_find_column_autodetects_known_headers(sample_df):
    template = sc.DEFAULT_TEMPLATE
    col = sc.find_column(
        sample_df, template["column_candidates"]["employee_id"], "Employee ID"
    )
    assert col == "Employee ID"

    col = sc.find_column(
        sample_df, template["column_candidates"]["Community_Name"], "Community Name"
    )
    assert col == "District Name"


# ── end-to-end: active sets and daily delta rows on the sample export ─────────

def _resolve_sample_column_map(df):
    template = sc.DEFAULT_TEMPLATE
    candidates = template["column_candidates"]
    col_map = {
        "employee_id": sc.find_column(df, candidates["employee_id"], "Employee ID"),
        "assignment": sc.find_column(df, candidates["assignment"], "Assignment"),
        "start_date": sc.find_column(df, candidates["start_date"], "Start Date"),
        "end_date": sc.find_column(df, candidates["end_date"], "End Date"),
    }
    for field in template["output_columns"]:
        if field in ("Action", "Transaction_Type") or field in template["field_defaults"]:
            continue
        col_map[field] = sc.find_column(
            df, candidates.get(field, []), field, required=False
        )
    return col_map


def test_active_sets_for_date_only_includes_matching_role(sample_df):
    col_map = _resolve_sample_column_map(sample_df)
    active, non_target, _ = sc.active_sets_for_date(
        sample_df, sc.DEFAULT_TEMPLATE, col_map, ["School Specialist"], date(2025, 9, 15)
    )
    # 10001, 10002, 10004, and 10006 are active School Specialists on this
    # date; the Classroom Teacher (10003) must not appear in the target set.
    emp_ids = {key[0] for key in active}
    assert emp_ids == {"10001", "10002", "10004", "10006"}
    assert "10003" in non_target


def test_build_daily_rows_detects_campus_move():
    """
    Employee 10004 ends at Roosevelt Middle on 2025-10-15 and the same person
    (10005 in the sample data models a re-assignment row) starts at the same
    campus on 2025-10-16. Diffing those two days should show a removal (D)
    and an addition (I) rather than silently dropping the change.
    """
    df = pd.read_csv(SAMPLE_CSV, dtype=str)
    df.columns = df.columns.str.strip()
    col_map = _resolve_sample_column_map(df)

    rows, _, _, changes = sc.build_daily_rows(
        df, sc.DEFAULT_TEMPLATE, col_map, ["School Specialist"], date(2025, 10, 16)
    )
    actions = {(emp, action) for emp, action, _school in changes}
    assert ("10004", "D") in actions
    assert ("10005", "I") in actions


def test_build_full_rows_only_includes_active_role(sample_df):
    col_map = _resolve_sample_column_map(sample_df)
    rows, snapshot, _ = sc.build_full_rows(
        sample_df, sc.DEFAULT_TEMPLATE, col_map, ["School Specialist"], date(2025, 9, 15)
    )
    assert all(row["Transaction_Type"] == "School Specialist" for row in rows)
    assert len(rows) == len(snapshot)
