"""
Multi-App Role Importer (CLIEngage starter)

A robust, menu-driven importer modeled after the Skyward -> Eduphoria workflow.
Supports saved templates + profiles, column mapping memory, catch-up processing,
optional fuzzy role matching, and CLIEngage School Specialist export generation.
"""

import argparse
import csv
import json
import platform
import re
import subprocess
import sys
from copy import deepcopy
from datetime import date, datetime, timedelta
from pathlib import Path


def _ensure_pandas():
    try:
        import pandas as _pd
        return _pd
    except ImportError:
        pass

    print("\npandas is not installed — attempting automatic installation...")
    try:
        subprocess.check_call(
            [sys.executable, "-m", "pip", "install", "pandas", "--quiet"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        print("pandas installed successfully.\n")
        import pandas as _pd
        return _pd
    except Exception as exc:
        print(f"Could not install pandas automatically: {exc}")
        print("Please install pandas manually with: python -m pip install pandas")
        sys.exit(1)


pd = _ensure_pandas()

VERSION = "1.0.0"
SCRIPT_DIR = Path(__file__).resolve().parent
STATE_FILE = SCRIPT_DIR / "cliengage_memory.json"

DEFAULT_TEMPLATE_KEY = "cliengage_school_specialist"

DEFAULT_TEMPLATE = {
    "app": "CLIEngage",
    "name": "School Specialist Template",
    "transaction_type": "School Specialist",
    "filename_prefix": "cliengage_school_specialist",
    "output_columns": [
        "Action",
        "Transaction_Type",
        "Community_Name",
        "Community_Engage_ID",
        "School_Name",
        "School_Engage_ID",
        "School_Specialist_First_Name",
        "School_Specialist_Middle_Name",
        "School_Specialist_Last_Name",
        "School_Specialist_Engage_ID",
        "School_Specialist_Internal_ID",
        "School_Specialist_Phone_Number",
        "School_Specialist_Phone_Type",
        "School_Specialist_Primary_Email",
        "School_Specialist_Secondary_Email",
        "Status",
        "Reset_Account",
    ],
    "field_defaults": {
        "Transaction_Type": "School Specialist",
        "School_Specialist_Engage_ID": "",
        "Status": "",
        "Reset_Account": "",
    },
    # output column -> expected source column labels list
    "column_candidates": {
        "employee_id": ["employee id", "employee number", "emp id", "staff id", "id"],
        "assignment": ["assignment type description", "assignment description", "job description", "position description"],
        "start_date": ["start date", "effective date", "begin date"],
        "end_date": ["end date", "termination date"],
        "Community_Name": ["community name", "district name"],
        "Community_Engage_ID": ["community engage id", "district engage id", "community id"],
        "School_Name": ["school name", "campus name", "building name"],
        "School_Engage_ID": ["school engage id", "campus id", "building code", "school id"],
        "School_Specialist_First_Name": ["first name", "employee first name"],
        "School_Specialist_Middle_Name": ["middle name", "employee middle name"],
        "School_Specialist_Last_Name": ["last name", "employee last name"],
        "School_Specialist_Internal_ID": ["employee id", "employee number", "internal id", "staff id"],
        "School_Specialist_Phone_Number": ["phone", "phone number", "work phone", "mobile phone"],
        "School_Specialist_Phone_Type": ["phone type"],
        "School_Specialist_Primary_Email": ["email", "email address", "work email"],
        "School_Specialist_Secondary_Email": ["secondary email", "personal email", "alternate email"],
    },
}

DEFAULT_STATE = {
    "templates": {DEFAULT_TEMPLATE_KEY: DEFAULT_TEMPLATE},
    "profiles": {},
    "snapshots": {},
    "run_logs": {},
}


def ask(question, default=""):
    suffix = f" [{default}]" if default else ""
    try:
        ans = input(f"\n  {question}{suffix}: ").strip()
    except (KeyboardInterrupt, EOFError):
        print()
        sys.exit(0)
    return ans if ans else default


def ask_yn(question, default=True):
    hint = "(Y/n)" if default else "(y/N)"
    ans = ask(f"{question} {hint}", "").lower()
    if ans in ("y", "yes"):
        return True
    if ans in ("n", "no"):
        return False
    return default


def section(title):
    print("\n" + "=" * 68)
    print(f"  {title}")
    print("=" * 68)


def pick_from_list(options, title, allow_custom=False, allow_skip=False):
    section(title)
    for i, option in enumerate(options, 1):
        print(f"  {i}. {option}")
    idx_custom = None
    idx_skip = None
    top = len(options)
    if allow_custom:
        idx_custom = top + 1
        print(f"  {idx_custom}. Enter custom value")
        top += 1
    if allow_skip:
        idx_skip = top + 1
        print(f"  {idx_skip}. Skip")
        top += 1

    while True:
        raw = ask(f"Choose 1-{top}")
        if not raw.isdigit():
            print("  Please enter a number.")
            continue
        n = int(raw)
        if 1 <= n <= len(options):
            return options[n - 1]
        if allow_custom and n == idx_custom:
            return ask("Enter custom value").strip()
        if allow_skip and n == idx_skip:
            return None
        print(f"  Please enter a number between 1 and {top}.")


def normalize(value):
    if value is None:
        return ""
    s = str(value).strip()
    return "" if s.lower() in {"nan", "none", "nat"} else s


def parse_date(value):
    if value is None:
        return None
    s = normalize(value)
    if not s:
        return None
    for fmt in ("%m/%d/%Y", "%Y-%m-%d", "%m/%d/%y", "%m-%d-%Y", "%Y/%m/%d", "%d/%m/%Y"):
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            pass
    try:
        return pd.to_datetime(s).date()
    except Exception:
        return None


def is_active_on(start, end, target):
    if start is None or target < start:
        return False
    if end is not None and target > end:
        return False
    return True


def fuzzy_match_text(needle, haystack, threshold=0.4):
    needle = needle.lower().strip()
    if not needle:
        return False
    if needle in haystack.lower():
        return True
    needle_tokens = set(re.split(r"\W+", needle))
    hay_tokens = set(re.split(r"\W+", haystack.lower()))
    needle_tokens.discard("")
    hay_tokens.discard("")
    if not needle_tokens or not hay_tokens:
        return False
    overlap = needle_tokens & hay_tokens
    return (len(overlap) / len(needle_tokens | hay_tokens)) >= threshold


def role_matches(assignment, roles, fuzzy=False):
    assignment = assignment.lower().strip()
    if fuzzy:
        return any(fuzzy_match_text(role, assignment) for role in roles)
    return assignment in {r.lower().strip() for r in roles}


def load_state():
    if not STATE_FILE.exists():
        return deepcopy(DEFAULT_STATE)
    raw = json.loads(STATE_FILE.read_text(encoding="utf-8"))
    state = deepcopy(DEFAULT_STATE)
    state.update(raw)
    # nested merge for safety
    for key in ("templates", "profiles", "snapshots", "run_logs"):
        state.setdefault(key, {})
    if DEFAULT_TEMPLATE_KEY not in state["templates"]:
        state["templates"][DEFAULT_TEMPLATE_KEY] = deepcopy(DEFAULT_TEMPLATE)
    return state


def save_state(state):
    STATE_FILE.write_text(json.dumps(state, indent=2), encoding="utf-8")


def find_column(df, candidates, label, required=True, existing_map=None):
    if existing_map and existing_map in df.columns:
        return existing_map

    lower_map = {c.lower().strip(): c for c in df.columns}
    for candidate in candidates:
        key = candidate.lower().strip()
        if key in lower_map:
            return lower_map[key]

    if not required:
        return None

    print(f"\n  Could not auto-detect '{label}'.")
    for i, col in enumerate(df.columns, 1):
        print(f"    {i}. {col}")
    while True:
        raw = ask(f"Which column maps to '{label}'? Enter number")
        if raw.isdigit() and 1 <= int(raw) <= len(df.columns):
            return df.columns[int(raw) - 1]
        print("  Please enter a valid number.")


def list_report_files():
    files = sorted(
        list(SCRIPT_DIR.glob("*.csv"))
        + list(SCRIPT_DIR.glob("*.xlsx"))
        + list(SCRIPT_DIR.glob("*.xls"))
    )
    files = [f for f in files if not f.name.startswith("cliengage_")]
    return files


def choose_report_file(profile):
    files = list_report_files()
    if not files:
        print("\n  No CSV/XLS/XLSX files found in script folder.")
        return None

    standardized = (profile or {}).get("standardized_input_filename", "").strip()
    if standardized:
        exact = [f for f in files if f.name.lower() == standardized.lower()]
        if exact:
            print(f"\n  Found standardized file: {exact[0].name}")
            if ask_yn("Use this file?", default=True):
                return exact[0]
        else:
            print(f"\n  Standardized file '{standardized}' not detected.")

    print("\n  Available report files:")
    names = [f.name for f in files]
    chosen_name = pick_from_list(names, "Select report file")
    return SCRIPT_DIR / chosen_name


def load_report(path):
    print(f"\n  Loading report: {path.name}")
    if path.suffix.lower() in {".xlsx", ".xls"}:
        df = pd.read_excel(path, dtype=str)
    else:
        df = None
        for encoding in ("utf-8-sig", "utf-8", "latin-1", "cp1252"):
            try:
                df = pd.read_csv(path, dtype=str, encoding=encoding)
                break
            except UnicodeDecodeError:
                continue
        if df is None:
            raise RuntimeError("Unable to decode CSV with supported encodings.")
    df.columns = df.columns.str.strip()
    print(f"  Loaded {len(df):,} rows and {len(df.columns)} columns.")
    return df


def resolve_column_map(df, template, saved_column_map=None):
    candidates = template.get("column_candidates", {})
    col_map = {}

    # technical fields
    col_map["employee_id"] = find_column(
        df,
        candidates.get("employee_id", []),
        "Employee ID",
        required=True,
        existing_map=(saved_column_map or {}).get("employee_id"),
    )
    col_map["assignment"] = find_column(
        df,
        candidates.get("assignment", []),
        "Assignment Description",
        required=True,
        existing_map=(saved_column_map or {}).get("assignment"),
    )
    col_map["start_date"] = find_column(
        df,
        candidates.get("start_date", []),
        "Start Date",
        required=True,
        existing_map=(saved_column_map or {}).get("start_date"),
    )
    col_map["end_date"] = find_column(
        df,
        candidates.get("end_date", []),
        "End Date",
        required=True,
        existing_map=(saved_column_map or {}).get("end_date"),
    )

    # template output fields that should map from source
    mapped_output_fields = [
        c
        for c in template["output_columns"]
        if c not in {"Action", "Transaction_Type"}
        and c not in template.get("field_defaults", {})
    ]
    for field in mapped_output_fields:
        required = field not in {
            "School_Specialist_Middle_Name",
            "School_Specialist_Phone_Number",
            "School_Specialist_Phone_Type",
            "School_Specialist_Secondary_Email",
        }
        col_map[field] = find_column(
            df,
            candidates.get(field, []),
            field,
            required=required,
            existing_map=(saved_column_map or {}).get(field),
        )

    print("\n  Column mapping resolved:")
    for k, v in col_map.items():
        print(f"    {k} -> {v}")

    if not ask_yn("Do these mappings look correct?", default=True):
        print("\n  Re-run and remap columns.")
        return None
    return col_map


def build_payload(row, template, col_map):
    payload = {}
    defaults = template.get("field_defaults", {})
    for output_col in template["output_columns"]:
        if output_col == "Action":
            continue
        if output_col in defaults:
            payload[output_col] = defaults[output_col]
        elif output_col in col_map and col_map[output_col]:
            payload[output_col] = normalize(row.get(col_map[output_col]))
        else:
            payload[output_col] = ""
    return payload


def active_sets_for_date(df, template, col_map, roles, target_date, fuzzy_mode=False):
    role_lc = [r.lower().strip() for r in roles]
    target_map = {}
    non_target_active_emp = set()
    previous_position = {}

    for _, row in df.iterrows():
        emp = normalize(row.get(col_map["employee_id"]))
        if not emp:
            continue

        assignment = normalize(row.get(col_map["assignment"]))
        start = parse_date(row.get(col_map["start_date"]))
        end = parse_date(row.get(col_map["end_date"]))
        active = is_active_on(start, end, target_date)

        if start and start < target_date and (end is None or end < target_date):
            cur = previous_position.get(emp)
            if cur is None or cur[0] < start:
                previous_position[emp] = (start, assignment)

        if not active:
            continue

        if role_matches(assignment, role_lc, fuzzy=fuzzy_mode):
            school_id_col = col_map.get("School_Engage_ID")
            school_id = normalize(row.get(school_id_col)) if school_id_col else ""
            key = (emp, school_id)
            payload = build_payload(row, template, col_map)
            existing = target_map.get(key)
            if existing is None:
                target_map[key] = {
                    "payload": payload,
                    "start": start or date.min,
                    "assignment": assignment,
                }
            else:
                if (start or date.min) >= existing["start"]:
                    target_map[key] = {
                        "payload": payload,
                        "start": start or date.min,
                        "assignment": assignment,
                    }
        else:
            non_target_active_emp.add(emp)

    final = {k: v["payload"] for k, v in target_map.items()}
    prev = {emp: value[1] for emp, value in previous_position.items()}
    return final, non_target_active_emp, prev


def payload_differs(a, b):
    compare_fields = [
        "Community_Name",
        "Community_Engage_ID",
        "School_Name",
        "School_Engage_ID",
        "School_Specialist_First_Name",
        "School_Specialist_Middle_Name",
        "School_Specialist_Last_Name",
        "School_Specialist_Phone_Number",
        "School_Specialist_Phone_Type",
        "School_Specialist_Primary_Email",
        "School_Specialist_Secondary_Email",
    ]
    for field in compare_fields:
        if normalize(a.get(field)) != normalize(b.get(field)):
            return True
    return False


def build_row(action, template, payload):
    row = {"Action": action}
    for col in template["output_columns"]:
        if col == "Action":
            continue
        row[col] = payload.get(col, "")
    return row


def build_daily_rows(df, template, col_map, roles, process_date, fuzzy_mode=False):
    today_map, _, prev_position_map = active_sets_for_date(df, template, col_map, roles, process_date, fuzzy_mode=fuzzy_mode)
    yday_map, y_non_target_emp, _ = active_sets_for_date(
        df,
        template,
        col_map,
        roles,
        process_date - timedelta(days=1),
        fuzzy_mode=fuzzy_mode,
    )

    rows = []
    change_summary = []

    today_keys = set(today_map)
    yday_keys = set(yday_map)

    # D rows for removals first
    for key in sorted(yday_keys - today_keys):
        emp, _ = key
        rows.append(build_row("D", template, yday_map[key]))
        change_summary.append((emp, "D", yday_map[key].get("School_Name", "")))

    yday_by_emp = {}
    for emp, school in yday_keys:
        yday_by_emp.setdefault(emp, set()).add(school)

    # Added today: I, T, or U (campus move continuation)
    for key in sorted(today_keys - yday_keys):
        emp, school = key
        payload = today_map[key]
        if emp in yday_by_emp:
            action = "U"  # after D from old campus
        elif emp in y_non_target_emp:
            action = "T"
        else:
            action = "I"
        rows.append(build_row(action, template, payload))
        change_summary.append((emp, action, payload.get("School_Name", "")))

    # Stayed: if user info changed, mark U
    for key in sorted(today_keys & yday_keys):
        if payload_differs(yday_map[key], today_map[key]):
            rows.append(build_row("U", template, today_map[key]))
            emp, _ = key
            change_summary.append((emp, "U", today_map[key].get("School_Name", "")))

    # dedupe preserving order
    seen = set()
    deduped = []
    for row in rows:
        marker = tuple((c, row.get(c, "")) for c in template["output_columns"])
        if marker in seen:
            continue
        seen.add(marker)
        deduped.append(row)

    return deduped, today_map, prev_position_map, change_summary


def build_full_rows(df, template, col_map, roles, process_date, fuzzy_mode=False):
    today_map, _, prev_position_map = active_sets_for_date(df, template, col_map, roles, process_date, fuzzy_mode=fuzzy_mode)
    rows = [build_row("I", template, payload) for _, payload in sorted(today_map.items())]
    return rows, today_map, prev_position_map


def run_dates_for_profile(state, profile_name, today, catchup=False):
    run_log = state["run_logs"].setdefault(profile_name, {"last_run": None, "processed": []})
    last_run = run_log.get("last_run")
    dates = [today]

    if last_run:
        last_date = date.fromisoformat(last_run)
        missed = []
        d = last_date + timedelta(days=1)
        processed = {x["date"] for x in run_log.get("processed", [])}
        while d < today:
            if d.isoformat() not in processed:
                missed.append(d)
            d += timedelta(days=1)

        if missed:
            print(f"\n  Missed dates found: {', '.join(x.isoformat() for x in missed)}")
            if catchup or ask_yn(f"Process {len(missed)} missed day(s) too?", default=True):
                dates = missed + [today]

    return dates


def record_run(state, profile_name, run_date, had_changes):
    run_log = state["run_logs"].setdefault(profile_name, {"last_run": None, "processed": []})
    ds = run_date.isoformat()
    run_log["processed"] = [e for e in run_log.get("processed", []) if e["date"] != ds]
    run_log["processed"].append({"date": ds, "had_changes": had_changes})
    run_log["last_run"] = ds


def write_rows(path, rows, columns):
    with open(path, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=columns)
        writer.writeheader()
        writer.writerows(rows)


def timestamp_label():
    return datetime.now().strftime("%Y%m%d_%H%M%S")


def profile_filename(prefix, mode, process_date, dynamic=True):
    if dynamic:
        return f"{prefix}_{mode}_{process_date.isoformat()}_{timestamp_label()}.csv"
    return f"{prefix}_{mode}_{process_date.isoformat()}.csv"


def generate_export_flow(state, today, catchup=False):
    section("GENERATE EXPORT")

    profiles = sorted(state["profiles"].keys())
    use_profile = False
    profile_name = "adhoc"
    profile = {}

    if profiles and ask_yn("Use a saved profile?", default=True):
        picked = pick_from_list(profiles, "Saved profiles", allow_skip=True)
        if picked:
            profile_name = picked
            profile = deepcopy(state["profiles"][profile_name])
            use_profile = True

    if not use_profile:
        template_key = pick_from_list(sorted(state["templates"].keys()), "Choose template key")
        roles_raw = ask("Role(s) to include (comma separated)", "School Specialist")
        roles = [x.strip() for x in roles_raw.split(",") if x.strip()]
        fuzzy_mode = ask_yn("Enable fuzzy role matching?", default=False)
        profile = {
            "template_key": template_key,
            "roles": roles,
            "fuzzy_mode": fuzzy_mode,
            "column_map": {},
            "standardized_input_filename": "",
            "dynamic_timestamp_filename": True,
        }

    template_key = profile["template_key"]
    template = state["templates"][template_key]

    report_path = choose_report_file(profile)
    if report_path is None:
        return

    df = load_report(report_path)

    col_map = resolve_column_map(df, template, saved_column_map=profile.get("column_map", {}))
    if col_map is None:
        return
    profile["column_map"] = col_map

    mode = pick_from_list(
        ["Daily delta export", "Full export", "Generate both"],
        "Output mode",
    )

    dates = run_dates_for_profile(state, profile_name, today, catchup=catchup)
    all_daily_rows = []
    last_snapshot = {}
    last_previous_position = {}

    for d in dates:
        if mode in {"Daily delta export", "Generate both"}:
            rows, snapshot, previous_position, changes = build_daily_rows(
                df,
                template,
                col_map,
                profile["roles"],
                d,
                fuzzy_mode=profile.get("fuzzy_mode", False),
            )
            all_daily_rows.extend(rows)
            last_snapshot = snapshot
            last_previous_position = previous_position
            record_run(state, profile_name, d, bool(rows))
            print(f"\n  {d}: Daily changes detected = {len(rows)} row(s).")

        if mode in {"Full export", "Generate both"} and d == dates[-1]:
            full_rows, snapshot, previous_position = build_full_rows(
                df,
                template,
                col_map,
                profile["roles"],
                d,
                fuzzy_mode=profile.get("fuzzy_mode", False),
            )
            full_name = profile_filename(
                template["filename_prefix"],
                "full",
                d,
                dynamic=profile.get("dynamic_timestamp_filename", True),
            )
            write_rows(SCRIPT_DIR / full_name, full_rows, template["output_columns"])
            print(f"\n  Wrote full export: {full_name} ({len(full_rows)} rows)")
            last_snapshot = snapshot
            last_previous_position = previous_position

    if all_daily_rows and mode in {"Daily delta export", "Generate both"}:
        day_for_name = dates[-1]
        daily_name = profile_filename(
            template["filename_prefix"],
            "daily",
            day_for_name,
            dynamic=profile.get("dynamic_timestamp_filename", True),
        )
        write_rows(SCRIPT_DIR / daily_name, all_daily_rows, template["output_columns"])
        print(f"\n  Wrote daily export: {daily_name} ({len(all_daily_rows)} rows)")
    elif mode in {"Daily delta export", "Generate both"}:
        print("\n  No daily role changes found; daily file not created.")

    state["snapshots"][profile_name] = {
        "date": dates[-1].isoformat(),
        "data": last_snapshot,
        "previous_positions": last_previous_position,
    }

    if ask_yn("Show up to 25 previous-position hints from this run?", default=False):
        shown = 0
        for emp, pos in sorted(last_previous_position.items()):
            print(f"  {emp}: previous position -> {pos}")
            shown += 1
            if shown >= 25:
                print("  ...truncated to 25")
                break

    # Save / update profile prompts
    if not use_profile:
        if ask_yn("Save these answers as a quick-run profile?", default=True):
            new_name = ask("Profile name")
            if new_name:
                profile["standardized_input_filename"] = ask(
                    "Standardized report filename to prefer (blank = none)",
                    profile.get("standardized_input_filename", ""),
                )
                profile["dynamic_timestamp_filename"] = ask_yn(
                    "Use dynamic timestamps in output filenames?",
                    default=True,
                )
                state["profiles"][new_name] = profile
                print(f"\n  Saved profile: {new_name}")
    else:
        if ask_yn("Update this profile with current column mappings/settings?", default=True):
            profile["standardized_input_filename"] = ask(
                "Standardized report filename",
                profile.get("standardized_input_filename", ""),
            )
            profile["dynamic_timestamp_filename"] = ask_yn(
                "Use dynamic timestamps in output filenames?",
                default=profile.get("dynamic_timestamp_filename", True),
            )
            state["profiles"][profile_name] = profile
            print(f"\n  Profile '{profile_name}' updated.")


def manage_profiles(state):
    while True:
        choice = pick_from_list(
            [
                "View profiles",
                "Create profile",
                "Edit profile",
                "Delete profile",
                "Back",
            ],
            "MANAGE PROFILES",
        )

        if choice == "Back":
            return

        if choice == "View profiles":
            section("SAVED PROFILES")
            if not state["profiles"]:
                print("  No profiles saved.")
            for name, p in sorted(state["profiles"].items()):
                print(f"\n  {name}")
                print(f"    template_key: {p.get('template_key')}")
                print(f"    roles: {', '.join(p.get('roles', []))}")
                print(f"    fuzzy_mode: {p.get('fuzzy_mode')}")
                print(f"    standardized_input_filename: {p.get('standardized_input_filename', '')}")

        elif choice == "Create profile":
            name = ask("New profile name")
            if not name:
                continue
            template_key = pick_from_list(sorted(state["templates"].keys()), "Select template key")
            roles = [x.strip() for x in ask("Roles (comma separated)", "School Specialist").split(",") if x.strip()]
            state["profiles"][name] = {
                "template_key": template_key,
                "roles": roles,
                "fuzzy_mode": ask_yn("Enable fuzzy role matching?", default=False),
                "column_map": {},
                "standardized_input_filename": ask("Standardized input filename (optional)", ""),
                "dynamic_timestamp_filename": ask_yn("Dynamic timestamped output filenames?", default=True),
            }
            print(f"\n  Profile '{name}' created.")

        elif choice == "Edit profile":
            if not state["profiles"]:
                print("\n  No profiles to edit.")
                continue
            name = pick_from_list(sorted(state["profiles"].keys()), "Select profile")
            p = state["profiles"][name]
            p["template_key"] = pick_from_list(sorted(state["templates"].keys()), "Template key")
            p["roles"] = [x.strip() for x in ask("Roles (comma separated)", ", ".join(p.get("roles", []))).split(",") if x.strip()]
            p["fuzzy_mode"] = ask_yn("Enable fuzzy role matching?", default=p.get("fuzzy_mode", False))
            p["standardized_input_filename"] = ask(
                "Standardized input filename",
                p.get("standardized_input_filename", ""),
            )
            p["dynamic_timestamp_filename"] = ask_yn(
                "Dynamic timestamped output filenames?",
                default=p.get("dynamic_timestamp_filename", True),
            )
            if ask_yn("Clear saved column mappings for this profile?", default=False):
                p["column_map"] = {}
            print(f"\n  Profile '{name}' updated.")

        elif choice == "Delete profile":
            if not state["profiles"]:
                print("\n  No profiles to delete.")
                continue
            name = pick_from_list(sorted(state["profiles"].keys()), "Select profile to delete")
            if ask_yn(f"Delete profile '{name}'?", default=False):
                del state["profiles"][name]
                state["run_logs"].pop(name, None)
                state["snapshots"].pop(name, None)
                print("\n  Profile deleted.")


def manage_templates(state):
    while True:
        choice = pick_from_list(
            [
                "View templates",
                "Create template from existing",
                "Edit template",
                "Delete template",
                "Back",
            ],
            "MANAGE TEMPLATES",
        )

        if choice == "Back":
            return

        if choice == "View templates":
            section("TEMPLATES")
            for key, t in sorted(state["templates"].items()):
                print(f"\n  {key}")
                print(f"    app={t.get('app')} name={t.get('name')}")
                print(f"    transaction_type={t.get('transaction_type')}")
                print(f"    filename_prefix={t.get('filename_prefix')}")
                print(f"    output_columns={len(t.get('output_columns', []))}")

        elif choice == "Create template from existing":
            source_key = pick_from_list(sorted(state["templates"].keys()), "Clone which template?")
            new_key = ask("New template key")
            if not new_key:
                continue
            if new_key in state["templates"]:
                print("\n  Template key already exists.")
                continue
            state["templates"][new_key] = deepcopy(state["templates"][source_key])
            state["templates"][new_key]["name"] = ask("Template display name", state["templates"][new_key].get("name", ""))
            print(f"\n  Template '{new_key}' created.")

        elif choice == "Edit template":
            key = pick_from_list(sorted(state["templates"].keys()), "Select template")
            t = state["templates"][key]
            t["app"] = ask("Application", t.get("app", ""))
            t["name"] = ask("Template name", t.get("name", ""))
            t["transaction_type"] = ask("Transaction type", t.get("transaction_type", ""))
            t["filename_prefix"] = ask("Filename prefix", t.get("filename_prefix", "export"))

            # edit column candidates for key fields
            while ask_yn("Edit auto-detect candidates for a field?", default=False):
                fields = sorted(t.get("column_candidates", {}).keys())
                field = pick_from_list(fields, "Field to edit")
                current = t["column_candidates"].get(field, [])
                print(f"\n  Current candidates: {current}")
                raw = ask("Enter comma-separated candidates", ", ".join(current))
                t["column_candidates"][field] = [x.strip() for x in raw.split(",") if x.strip()]

            print(f"\n  Template '{key}' updated.")

        elif choice == "Delete template":
            keys = [k for k in state["templates"].keys() if k != DEFAULT_TEMPLATE_KEY]
            if not keys:
                print("\n  Only default template exists; cannot delete it.")
                continue
            key = pick_from_list(sorted(keys), "Select template to delete")
            if ask_yn(f"Delete template '{key}'?", default=False):
                del state["templates"][key]
                print("\n  Template deleted.")


def view_run_history(state):
    section("RUN HISTORY")
    if not state["run_logs"]:
        print("  No run history yet.")
        return

    for profile, log in sorted(state["run_logs"].items()):
        print(f"\n  Profile: {profile}")
        print(f"    Last run: {log.get('last_run')}")
        for entry in sorted(log.get("processed", []), key=lambda x: x["date"])[-20:]:
            print(f"    {entry['date']}  changes={entry['had_changes']}")


def main_menu(state, today, catchup=False):
    while True:
        choice = pick_from_list(
            [
                "Generate export",
                "Manage profiles",
                "Manage templates",
                "View run history",
                "Exit",
            ],
            f"MAIN MENU  |  v{VERSION}",
        )

        if choice == "Generate export":
            generate_export_flow(state, today=today, catchup=catchup)
            save_state(state)
        elif choice == "Manage profiles":
            manage_profiles(state)
            save_state(state)
        elif choice == "Manage templates":
            manage_templates(state)
            save_state(state)
        elif choice == "View run history":
            view_run_history(state)
        else:
            print("\n  Goodbye!")
            return


def main(args):
    today = date.fromisoformat(args.date) if args.date else date.today()
    state = load_state()

    if platform.system() == "Windows":
        # Keep Windows terminal title helpful
        try:
            subprocess.run(["cmd", "/c", "title", "CLIEngage Import Builder"], check=False)
        except Exception:
            pass

    main_menu(state, today=today, catchup=args.catchup)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="CLIEngage Import Builder")
    parser.add_argument("--date", metavar="YYYY-MM-DD", help="Treat this date as today")
    parser.add_argument("--catchup", action="store_true", help="Automatically include missed dates")
    main(parser.parse_args())
