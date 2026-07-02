#!/usr/bin/env python3
"""
TMDSAS public Power BI dataset extractor.

Pulls aggregate medical-school applicant statistics from the public
(no-auth) Power BI report that backs the TMDSAS stats dashboard
(https://www.tmdsas.com/stats-dashboard/medical-report.html) and writes
tidy CSV files.

It talks directly to the Power BI public "querydata" backend API. No
browser, no auth, no third-party packages -- Python 3 standard library only.

Usage:
    python3 src/extract_tmdsas.py

Outputs:
    data/raw/*.json          -- raw API responses (one per query, for audit)
    data/cleaned/*.csv       -- tidy CSVs (the deliverables), including the
                                GPA x MCAT acceptance grid (a Texas analog of
                                AAMC Table A-23) and its residency split.
    plus a printed run summary.

The data is an *unofficial* reproduction of public aggregate figures. See
docs/methodology.md and data-dictionary.md for definitions and caveats.
"""

import csv
import json
import os
import urllib.request
import urllib.error
import uuid

# ---------------------------------------------------------------------------
# Constants: the verified public Power BI model coordinates.
# ---------------------------------------------------------------------------
HOST = "https://wabi-us-north-central-h-primary-api.analysis.windows.net"
RESOURCE_KEY = "4912d801-7866-42c4-b99d-f5a08c3593ef"
DATASET_ID = "35ace578-cc42-4994-8718-91c2ad896b8f"
REPORT_ID = "821982"
MODEL_ID = 821982
ENTITY = "Sheet1"                                   # the single table
COUNT_MEASURE = "Count of Total Number of Applicants"

QUERY_URL = f"{HOST}/public/reports/querydata?synchronous=true"

# Resolve paths relative to the repo root (parent of this file's dir) so the
# script works regardless of the caller's current working directory.
_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RAW_DIR = os.path.join(_REPO_ROOT, "data", "raw")
CLEAN_DIR = os.path.join(_REPO_ROOT, "data", "cleaned")


# ---------------------------------------------------------------------------
# HTTP layer
# ---------------------------------------------------------------------------
def _post(body):
    """POST a query body to the Power BI backend and return parsed JSON."""
    data = json.dumps(body).encode("utf-8")
    req = urllib.request.Request(QUERY_URL, data=data, method="POST")
    req.add_header("X-PowerBI-ResourceKey", RESOURCE_KEY)
    req.add_header("ActivityId", str(uuid.uuid4()))
    req.add_header("RequestId", str(uuid.uuid4()))
    req.add_header("Content-Type", "application/json;charset=UTF-8")
    with urllib.request.urlopen(req, timeout=90) as resp:
        return json.load(resp)


# ---------------------------------------------------------------------------
# Query-body builders
# ---------------------------------------------------------------------------
def _col(prop):
    """A Select/expression entry referencing a column on the entity."""
    return {"Expression": {"SourceRef": {"Source": "s"}}, "Property": prop}


def build_grouped_count_query(group_props):
    """
    Build a SemanticQuery that groups the count measure by one or more
    columns. `group_props` is a list of column property names; the count
    measure is always appended last.
    """
    select = []
    for prop in group_props:
        select.append({"Column": _col(prop), "Name": prop})
    select.append({"Measure": _col(COUNT_MEASURE), "Name": "Cnt"})
    projections = list(range(len(select)))  # group cols + measure

    return {
        "version": "1.0.0",
        "queries": [{
            "Query": {"Commands": [{"SemanticQueryDataShapeCommand": {
                "Query": {
                    "Version": 2,
                    "From": [{"Name": "s", "Entity": ENTITY, "Type": 0}],
                    "Select": select,
                    "OrderBy": [{
                        "Direction": 1,
                        "Expression": {"Column": _col(group_props[0])},
                    }],
                },
                "Binding": {
                    "Primary": {"Groupings": [{"Projections": projections}]},
                    "DataReduction": {"DataVolume": 3,
                                      "Primary": {"Window": {"Count": 30000}}},
                    "Version": 1,
                },
            }}]},
            "QueryId": "",
            "ApplicationContext": {"DatasetId": DATASET_ID,
                                   "Sources": [{"ReportId": REPORT_ID}]},
        }],
        "cancelQueries": [],
        "modelId": MODEL_ID,
    }


def build_average_query(group_prop, measure_props, where=None):
    """
    Build a SemanticQuery that returns the AVERAGE of one or more numeric
    columns grouped by `group_prop`. Power BI Aggregation Function 1 ==
    Average (verified: yields plausible MCAT ~500-512 / GPA ~3.5 rather than
    a sum). `where` is an optional list of WHERE-filter expressions.
    """
    select = [{"Column": _col(group_prop), "Name": group_prop}]
    for mp in measure_props:
        select.append({
            "Aggregation": {"Expression": {"Column": _col(mp)}, "Function": 1},
            "Name": f"avg_{mp}",
        })
    projections = list(range(len(select)))

    query = {
        "Version": 2,
        "From": [{"Name": "s", "Entity": ENTITY, "Type": 0}],
        "Select": select,
        "OrderBy": [{"Direction": 1, "Expression": {"Column": _col(group_prop)}}],
    }
    if where:
        query["Where"] = where

    return {
        "version": "1.0.0",
        "queries": [{
            "Query": {"Commands": [{"SemanticQueryDataShapeCommand": {
                "Query": query,
                "Binding": {
                    "Primary": {"Groupings": [{"Projections": projections}]},
                    "DataReduction": {"DataVolume": 3,
                                      "Primary": {"Window": {"Count": 30000}}},
                    "Version": 1,
                },
            }}]},
            "QueryId": "",
            "ApplicationContext": {"DatasetId": DATASET_ID,
                                   "Sources": [{"ReportId": REPORT_ID}]},
        }],
        "cancelQueries": [],
        "modelId": MODEL_ID,
    }


def where_equals(prop, value):
    """A WHERE filter expression: column == literal string value."""
    return {"Condition": {"In": {
        "Expressions": [{"Column": _col(prop)}],
        "Values": [[{"Literal": {"Value": f"'{value}'"}}]],
    }}}


# ---------------------------------------------------------------------------
# DSR / run-length decoder  (the tricky part)
# ---------------------------------------------------------------------------
def decode_dsr(response):
    """
    Decode the Power BI "dsr" (data shape result) into a list of full,
    column-aligned rows.

    Power BI compresses rows three ways; all must be undone:

      * Type header `S` on the first row defines the columns (order matches
        descriptor.Select). We use it only to learn the column count.
      * Run-length `R` integer bitmask: if bit n is set, column n REPEATS the
        previous row's value and is OMITTED from this row's `C` array.
      * Null bitmask `Ø`: if bit n is set, column n is NULL (also omitted
        from `C`).

    A row's `C` array therefore contains only the columns NOT covered by the
    R or Ø masks, in column order. We splice them back in, carrying the prior
    row forward for repeated columns.

    String columns may be dictionary-encoded: the cell holds an integer index
    into `ValueDicts[DN]`, where DN comes from the descriptor's `S` header
    (the `DN` key on a column). We resolve those to their string values.

    Returns: (rows, column_names) where rows is a list of lists.
    """
    result = response["results"][0]["result"]["data"]
    descriptor = result["descriptor"]["Select"]
    column_names = [c["Name"] for c in descriptor]

    ds = result["dsr"]["DS"][0]
    value_dicts = ds.get("ValueDicts", {})
    dm0 = ds["PH"][0]["DM0"]

    n_cols = len(column_names)

    # Map column index -> ValueDicts key (DN), learned from the `S` header.
    # The header's entries are in the same column order as descriptor.Select.
    col_dict_name = [None] * n_cols

    rows = []
    prev = [None] * n_cols

    for raw in dm0:
        # The first row carries the type header `S`; capture dictionary names.
        if "S" in raw:
            for i, s_entry in enumerate(raw["S"]):
                if i < n_cols and "DN" in s_entry:
                    col_dict_name[i] = s_entry["DN"]

        repeat_mask = raw.get("R", 0)   # bit set -> repeat previous value
        null_mask = raw.get("Ø", 0)     # bit set -> value is null
        cells = raw.get("C", [])

        row = [None] * n_cols
        cell_idx = 0
        for col in range(n_cols):
            if repeat_mask & (1 << col):
                row[col] = prev[col]            # repeated -> carry forward
            elif null_mask & (1 << col):
                row[col] = None                 # explicitly null
            else:
                row[col] = cells[cell_idx]      # present in C array
                cell_idx += 1
        rows.append(row)
        prev = row

    # Resolve dictionary-encoded string columns (index -> label).
    for col in range(n_cols):
        dn = col_dict_name[col]
        if dn and dn in value_dicts:
            mapping = value_dicts[dn]
            for row in rows:
                v = row[col]
                if isinstance(v, int) and 0 <= v < len(mapping):
                    row[col] = mapping[v]

    return rows, column_names


# ---------------------------------------------------------------------------
# Orchestration helpers
# ---------------------------------------------------------------------------
def run_grouped_count(group_props, raw_name):
    """Run a grouped-count query, persist raw JSON, return decoded rows."""
    body = build_grouped_count_query(group_props)
    resp = _post(body)
    _save_raw(resp, raw_name)
    return decode_dsr(resp)


def _save_raw(resp, name):
    os.makedirs(RAW_DIR, exist_ok=True)
    with open(os.path.join(RAW_DIR, name), "w") as f:
        json.dump(resp, f, indent=2)


def _write_csv(filename, header, rows):
    os.makedirs(CLEAN_DIR, exist_ok=True)
    path = os.path.join(CLEAN_DIR, filename)
    with open(path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(header)
        w.writerows(rows)
    return path


# ---------------------------------------------------------------------------
# Build helpers: turn decoded (year, flag_label, count) rows into lookups
# ---------------------------------------------------------------------------
def flag_counts_by_year(rows, true_labels):
    """
    From rows of [year, flag_label, count], return:
      total[year]        -> sum of counts across all flag values
      in_group[year]     -> sum of counts where flag_label is in true_labels
    `true_labels` is the set of dict labels that mean "flag is true".
    """
    total = {}
    in_group = {}
    for year, label, count in rows:
        year = int(year)
        count = int(count)
        total[year] = total.get(year, 0) + count
        if label in true_labels:
            in_group[year] = in_group.get(year, 0) + count
    return total, in_group


# ---------------------------------------------------------------------------
# Applicant AGE distribution & outcomes
# ---------------------------------------------------------------------------
# `Age` is an integer column (conceptualschema DataType 4, FormatString "0"),
# the applicant's age, exposed at INDIVIDUAL-year granularity (e.g. 14..79).
# We pool completed cycles EY2020-2025 for the headline outcomes file and also
# emit an all-years (EY2016-2026) raw distribution.
AGE_POOL_YEARS = list(range(2020, 2026))       # 2020..2025 inclusive
AGE_POOL_LABEL = "EY2020-2025"
AGE_SMALL_N = 10                               # blank rates below this n


def _age_counts(rows, year_filter=None):
    """[year, age, count] -> {age: total count} (optionally year-filtered)."""
    out = {}
    for year, age, count in rows:
        if age is None:
            continue
        if year_filter is not None and int(year) not in year_filter:
            continue
        a = int(age)
        out[a] = out.get(a, 0) + int(count)
    return out


def _age_flag_true(rows, false_label="no", year_filter=None):
    """[year, age, flag_label, count] -> {age: count where flag is true}."""
    out = {}
    for year, age, label, count in rows:
        if age is None:
            continue
        if year_filter is not None and int(year) not in year_filter:
            continue
        if label != false_label:
            out[int(age)] = out.get(int(age), 0) + int(count)
    return out


def build_age_outputs():
    """
    Pull applicant age distribution + outcomes and write
    data/cleaned/outcomes_by_age.csv. Returns (path, all_years_age_rows).
    """
    # 1. Age distribution: EntryYear x Age (all years, one POST).
    age_year_rows, _ = run_grouped_count(["EntryYear", "Age"],
                                         "count_by_year_age.json")
    dist_all = _age_counts(age_year_rows)                       # all years
    dist_pool = _age_counts(age_year_rows, AGE_POOL_YEARS)      # EY2020-25

    # 2. Outcomes by age: EntryYear x Age x outcome flag (one POST each).
    acc_rows, _ = run_grouped_count(["EntryYear", "Age", "IsAccepted"],
                                    "count_by_year_age_accepted.json")
    mat_rows, _ = run_grouped_count(["EntryYear", "Age", "IsMatriculated"],
                                    "count_by_year_age_matriculated.json")
    accepted = _age_flag_true(acc_rows, "no", AGE_POOL_YEARS)
    matriculated = _age_flag_true(mat_rows, "no", AGE_POOL_YEARS)

    # 3. outcomes_by_age.csv (pooled EY2020-2025).
    rows = []
    for age in sorted(dist_pool):
        n = dist_pool[age]
        acc = accepted.get(age, 0)
        mat = matriculated.get(age, 0)
        if n >= AGE_SMALL_N:
            acc_rate = round(acc / n, 4)
            mat_rate = round(mat / n, 4)
        else:
            acc_rate = ""           # blank rates for small-n tail
            mat_rate = ""
        rows.append([age, n, acc, mat, acc_rate, mat_rate, AGE_POOL_LABEL])
    path = _write_csv(
        "outcomes_by_age.csv",
        ["age", "applicants", "accepted", "matriculated",
         "acceptance_rate", "matriculation_rate", "years_pooled"],
        rows)

    # 4. Age x Residency (TX vs non-TX), pooled, best-effort headline file.
    res_rows, _ = run_grouped_count(["EntryYear", "Age", "Residency"],
                                    "count_by_year_age_residency.json")
    res = {}        # (age, residency) -> count
    for year, age, residency, count in res_rows:
        if age is None or int(year) not in AGE_POOL_YEARS:
            continue
        if residency not in ("Texas Resident", "Non Resident"):
            continue
        res[(int(age), residency)] = res.get((int(age), residency), 0) + int(count)
    res_out = []
    for (age, residency) in sorted(res):
        res_out.append([age, residency, res[(age, residency)], AGE_POOL_LABEL])
    res_path = _write_csv(
        "age_by_residency.csv",
        ["age", "residency", "applicants", "years_pooled"],
        res_out)

    # --- Run summary: the TAIL is the point -------------------------------
    print(f"\nApplicant age distribution ({AGE_POOL_LABEL} pooled):")
    pool_ages = sorted(dist_pool)
    total = sum(dist_pool.values())
    print(f"  ages present: {pool_ages[0]}..{pool_ages[-1]}  "
          f"(total applicants {total})")
    modal = max(dist_pool, key=dist_pool.get)
    print(f"  modal age: {modal} (n={dist_pool[modal]})")
    # tail counts
    print("  tail (age >= 50), pooled EY2020-2025:")
    for age in pool_ages:
        if age >= 50:
            acc = accepted.get(age, 0)
            print(f"    age {age:>2}: applicants={dist_pool[age]:>3}  "
                  f"accepted={acc}")

    print(f"\nFiles written:\n  {path}\n  {res_path}")
    return path, age_year_rows


# ---------------------------------------------------------------------------
# Main extraction routine
# ---------------------------------------------------------------------------
def main():
    print("TMDSAS Power BI extractor -- starting")
    print("-" * 60)

    # --- 1. Pull the raw grouped counts (one POST per dimension) ----------
    # EntryYear x each outcome flag, plus EntryYear x Residency.
    interview_rows, _ = run_grouped_count(["EntryYear", "IsInterviewed"],
                                          "count_by_year_interviewed.json")
    accept_rows, _ = run_grouped_count(["EntryYear", "IsAccepted"],
                                       "count_by_year_accepted.json")
    matric_rows, _ = run_grouped_count(["EntryYear", "IsMatriculated"],
                                       "count_by_year_matriculated.json")
    residency_rows, _ = run_grouped_count(["EntryYear", "Residency"],
                                          "count_by_year_residency.json")
    reapply_rows, _ = run_grouped_count(["EntryYear", "Reapply"],
                                        "count_by_year_reapply.json")
    nontrad_rows, _ = run_grouped_count(["EntryYear", "NonTrad"],
                                        "count_by_year_nontrad.json")
    military_rows, _ = run_grouped_count(["EntryYear", "MilitaryYN"],
                                         "count_by_year_military.json")

    # --- 2. Build per-year totals & per-flag in-group counts --------------
    # The dict labels that mean "the outcome happened / the flag is true":
    total_iv, interviewed = flag_counts_by_year(interview_rows, {"Interviewed"})
    total_ac, accepted = flag_counts_by_year(accept_rows, {"Accepted", "Yes"})
    total_mt, matriculated = flag_counts_by_year(matric_rows, {"Matriculated"})

    # Sanity: IsAccepted dict is ['no', ...]; the "true" label is the count
    # under index that is NOT 'no'. Recompute robustly below.
    accepted = _true_counts(accept_rows, false_label="no")
    matriculated = _true_counts(matric_rows, false_label="no")
    interviewed = _true_counts(interview_rows, false_label="no")

    years = sorted(total_ac)

    # --- 3. funnel_by_entry_year.csv --------------------------------------
    funnel_rows = []
    for y in years:
        funnel_rows.append([
            y,
            total_ac[y],                       # applicants = grand total
            interviewed.get(y, 0),
            accepted.get(y, 0),
            matriculated.get(y, 0),
        ])
    funnel_path = _write_csv(
        "funnel_by_entry_year.csv",
        ["entry_year", "applicants", "interviewed", "accepted", "matriculated"],
        funnel_rows,
    )

    # --- 4. outcomes_by_residency.csv -------------------------------------
    # Residency split itself only gives applicants per (year, residency).
    # For interviewed/accepted/matriculated within residency we run a
    # 3-way grouping (year x residency x outcome flag).
    res_iv = run_grouped_count(["EntryYear", "Residency", "IsInterviewed"],
                               "count_by_year_residency_interviewed.json")[0]
    res_ac = run_grouped_count(["EntryYear", "Residency", "IsAccepted"],
                               "count_by_year_residency_accepted.json")[0]
    res_mt = run_grouped_count(["EntryYear", "Residency", "IsMatriculated"],
                               "count_by_year_residency_matriculated.json")[0]

    res_applicants = _two_key_totals(residency_rows)            # (year,res)->total
    res_interviewed = _two_key_true(res_iv, "no")
    res_accepted = _two_key_true(res_ac, "no")
    res_matriculated = _two_key_true(res_mt, "no")

    residencies = sorted({r for (_, r) in res_applicants})
    residency_out_rows = []
    for y in years:
        for res in residencies:
            key = (y, res)
            if key not in res_applicants:
                continue
            residency_out_rows.append([
                y, res,
                res_applicants[key],
                res_interviewed.get(key, 0),
                res_accepted.get(key, 0),
                res_matriculated.get(key, 0),
            ])
    residency_path = _write_csv(
        "outcomes_by_residency.csv",
        ["entry_year", "residency", "applicants",
         "interviewed", "accepted", "matriculated"],
        residency_out_rows,
    )

    # --- 5. outcomes_by_applicant_type.csv (tidy long) --------------------
    # Three INDEPENDENT (non-exclusive) flags. For each, run year x flag x
    # outcome 3-way groupings so we get outcomes within the in-group.
    type_specs = [
        # dimension label, flag column, in-group dict labels, raw-file stem
        ("reapplicant", "Reapply", {"Reapplicant"}, "reapply"),
        ("nontraditional", "NonTrad", {"Non-Traditional"}, "nontrad"),
        ("military", "MilitaryYN", {"Y"}, "military"),
    ]
    type_rows = []
    for dim, flagcol, true_labels, stem in type_specs:
        base = {"reapplicant": reapply_rows,
                "nontraditional": nontrad_rows,
                "military": military_rows}[dim]
        applicants_total, in_group = flag_counts_by_year(base, true_labels)

        # outcomes restricted to the in-group: group year x flag x outcome
        iv3 = run_grouped_count(["EntryYear", flagcol, "IsInterviewed"],
                                f"count_by_year_{stem}_interviewed.json")[0]
        ac3 = run_grouped_count(["EntryYear", flagcol, "IsAccepted"],
                                f"count_by_year_{stem}_accepted.json")[0]
        mt3 = run_grouped_count(["EntryYear", flagcol, "IsMatriculated"],
                                f"count_by_year_{stem}_matriculated.json")[0]
        iv = _flag_subset_true(iv3, true_labels, "no")
        ac = _flag_subset_true(ac3, true_labels, "no")
        mt = _flag_subset_true(mt3, true_labels, "no")

        for y in years:
            type_rows.append([
                y, dim,
                in_group.get(y, 0),
                applicants_total.get(y, 0),
                iv.get(y, 0),
                ac.get(y, 0),
                mt.get(y, 0),
            ])
    type_path = _write_csv(
        "outcomes_by_applicant_type.csv",
        ["entry_year", "dimension", "in_group", "applicants_total",
         "interviewed", "accepted", "matriculated"],
        type_rows,
    )

    # --- 6. scores_by_cohort.csv (best-effort, verified) ------------------
    scores_path = _build_scores(years)

    # --- 7. GPA × MCAT acceptance grid (pooled EY2020-2025) ---------------
    grid_path, grid_res_path = build_gpa_mcat_grid()

    # --- 7b. Applicant age distribution & outcomes (pooled EY2020-2025) ----
    age_path, _ = build_age_outputs()

    # --- 8. Run summary ----------------------------------------------------
    print("\nFunnel by entry year:")
    print(f"{'year':>6}{'applicants':>12}{'interviewed':>13}"
          f"{'accepted':>11}{'matriculated':>14}")
    for r in funnel_rows:
        print(f"{r[0]:>6}{r[1]:>12}{r[2]:>13}{r[3]:>11}{r[4]:>14}")

    # TX vs non-TX acceptance rate for the latest year with acceptances.
    latest_decided = max(y for y in years if res_accepted_any(res_accepted, y))
    print(f"\nResidency acceptance rates (EY{latest_decided}):")
    for res in residencies:
        key = (latest_decided, res)
        if key in res_applicants and res_applicants[key]:
            rate = res_accepted.get(key, 0) / res_applicants[key]
            print(f"  {res:<16} {res_accepted.get(key,0):>6}/"
                  f"{res_applicants[key]:<6} = {rate:6.1%}")

    print("\nFiles written:")
    for p in [funnel_path, residency_path, type_path, scores_path,
              grid_path, grid_res_path, age_path]:
        if p:
            print(f"  {p}")
    print("\nDone.")


# ---------------------------------------------------------------------------
# Small decoding helpers used by main()
# ---------------------------------------------------------------------------
def _true_counts(rows, false_label):
    """[year, label, count] -> {year: count where label != false_label}."""
    out = {}
    for year, label, count in rows:
        if label != false_label:
            out[int(year)] = out.get(int(year), 0) + int(count)
    return out


def _two_key_totals(rows):
    """[year, key, count] -> {(year,key): total count}."""
    out = {}
    for year, key, count in rows:
        out[(int(year), key)] = out.get((int(year), key), 0) + int(count)
    return out


def _two_key_true(rows, false_label):
    """[year, key, flag_label, count] -> {(year,key): count where flag true}."""
    out = {}
    for year, key, label, count in rows:
        if label != false_label:
            k = (int(year), key)
            out[k] = out.get(k, 0) + int(count)
    return out


def _flag_subset_true(rows, true_labels, false_label):
    """
    [year, flag_label, outcome_label, count] -> {year: count} where the
    applicant-type flag is in true_labels AND the outcome is true.
    """
    out = {}
    for year, flag_label, outcome_label, count in rows:
        if flag_label in true_labels and outcome_label != false_label:
            out[int(year)] = out.get(int(year), 0) + int(count)
    return out


def res_accepted_any(res_accepted, year):
    return any(k[0] == year and v for k, v in res_accepted.items())


# ---------------------------------------------------------------------------
# Scores (averages) -- verified plausible before shipping
# ---------------------------------------------------------------------------
SCORE_COLS = [
    ("avg_mcat_total", "MCAT"),
    ("avg_cpbs", "LastCPBS"),
    ("avg_cars", "LastCARS"),
    ("avg_bbfl", "LastBBFL"),
    ("avg_psbb", "LastPSBB"),
    ("avg_overall_gpa", "Overall GPA"),
    ("avg_bcpm_gpa", "Overall BCPM GPA"),
]


def _avg_by_year(props, raw_name, where=None):
    """Run an average query; return {year: {prop: avg_float}}."""
    body = build_average_query("EntryYear", props, where=where)
    resp = _post(body)
    _save_raw(resp, raw_name)
    rows, names = decode_dsr(resp)
    out = {}
    for row in rows:
        year = int(row[0])
        out[year] = {}
        for i, p in enumerate(props):
            val = row[i + 1]
            out[year][p] = round(float(val), 3) if val is not None else None
    return out


def _build_scores(years):
    """
    Build scores_by_cohort.csv. Cohorts: all applicants, accepted,
    matriculated (filtered via WHERE). Returns the path, or None if the
    averages fail a plausibility check.
    """
    props = [p for _, p in SCORE_COLS]
    cohorts = [
        ("all_applicants", None),
        ("accepted", [where_equals("IsAccepted", "Accepted")]),
        ("matriculated", [where_equals("IsMatriculated", "Matriculated")]),
    ]

    cohort_data = {}
    for name, where in cohorts:
        cohort_data[name] = _avg_by_year(props, f"avg_scores_{name}.json", where)

    # Plausibility gate: any year's all-applicant MCAT must be ~480-528.
    sample = [d.get("MCAT") for d in cohort_data["all_applicants"].values()
              if d.get("MCAT")]
    if not sample or not all(480 <= m <= 528 for m in sample):
        print("WARNING: MCAT averages outside plausible range -- "
              "skipping scores_by_cohort.csv")
        return None

    header = ["entry_year", "cohort"] + [c for c, _ in SCORE_COLS]
    rows = []
    for name, _ in cohorts:
        for y in years:
            if y not in cohort_data[name]:
                continue
            d = cohort_data[name][y]
            rows.append([y, name] + [d.get(p) for _, p in SCORE_COLS])
    return _write_csv("scores_by_cohort.csv", header, rows)


# ---------------------------------------------------------------------------
# GPA × MCAT acceptance grid  (the "what are my chances" cross-tab)
# ---------------------------------------------------------------------------
# The source exposes pre-binned columns:
#   * "Overall GPA (bins)"     -- bins `Overall GPA` at width 0.1 (lower edge).
#   * "MCAT B (MATRIX bins)"    -- bins total composite MCAT at width 5 (lower
#                                  edge: 470, 475, ... 525).
# The native 0.1-wide GPA bins are far too granular to publish (tiny cells), so
# we roll GPA up into coarser, publishable bands (AAMC Table A-23 style). MCAT
# keeps native 5-wide bins, with the sparse extremes collapsed into <490 and a
# 520+ top band. Rows with a missing GPA or MCAT bin are dropped (a chances
# grid needs both axes).
#
# Years EY2020-2025 are POOLED: these are completed cycles on the current bin
# scheme, which gives adequate per-cell counts. EY2026 is in progress (partial
# acceptances) and is excluded; EY2016-2019 are excluded to keep the pool to
# recent, comparable cycles.
GRID_YEARS = list(range(2020, 2026))          # 2020..2025 inclusive
GRID_YEARS_LABEL = "EY2020-2025"
SMALL_CELL_MIN = 10                            # suppress rates for n < this
GPA_BIN_PROP = "Overall GPA (bins)"
MCAT_BIN_PROP = "MCAT B (MATRIX bins)"
ACCEPTED_LABEL = "Accepted"                    # IsAccepted "true" value


def gpa_band(bin_value):
    """
    Roll a native 0.1-wide GPA bin lower-edge into a publishable band label.
    The source emits float-noisy values (e.g. 3.6000000000000001); round to
    1 dp first. Returns None for the junk 0.0 bin / missing values so those
    rows are dropped from the grid.
    """
    if bin_value is None:
        return None
    try:
        g = round(float(bin_value), 1)
    except (TypeError, ValueError):
        return None
    if g < 1.0:                  # the 0.0 catch-all bin is not a real GPA
        return None
    if g < 3.00:
        return "<3.00"
    if g < 3.20:
        return "3.00-3.19"
    if g < 3.40:
        return "3.20-3.39"
    if g < 3.60:
        return "3.40-3.59"
    if g < 3.80:
        return "3.60-3.79"
    if g < 4.00:
        return "3.80-3.99"
    return "4.00"


GPA_BAND_ORDER = ["<3.00", "3.00-3.19", "3.20-3.39", "3.40-3.59",
                  "3.60-3.79", "3.80-3.99", "4.00"]


def mcat_band(bin_value):
    """
    Roll a native 5-wide MCAT bin lower-edge into a publishable band label.
    Collapses the sparse low tail into <490 and the high tail into 520+.
    Returns None for a missing MCAT bin (row dropped from the grid).
    """
    if bin_value is None:
        return None
    try:
        m = int(bin_value)
    except (TypeError, ValueError):
        return None
    if m < 490:
        return "<490"
    if m >= 520:
        return "520+"
    return f"{m}-{m + 4}"        # 490-494, 495-499, ... 515-519


MCAT_BAND_ORDER = ["<490", "490-494", "495-499", "500-504",
                   "505-509", "510-514", "515-519", "520+"]


def _accumulate_grid(rows, key_cols, year_idx, gpa_idx, mcat_idx,
                     acc_idx, cnt_idx):
    """
    Fold decoded cross-tab rows into {key: [applicants, accepted]} where `key`
    is built from the columns at `key_cols` indices (each passed through its
    band function) PLUS any leading non-band keys (e.g. residency). Rows
    outside GRID_YEARS, or with an undefined GPA/MCAT band, are skipped.

    key_cols: list of (index, band_func_or_None) describing the grouping key.
    """
    grid = {}
    for row in rows:
        if int(row[year_idx]) not in GRID_YEARS:
            continue
        gband = gpa_band(row[gpa_idx])
        mband = mcat_band(row[mcat_idx])
        if gband is None or mband is None:
            continue
        key_parts = []
        ok = True
        for idx, fn in key_cols:
            v = fn(row[idx]) if fn else row[idx]
            if v is None:
                ok = False
                break
            key_parts.append(v)
        if not ok:
            continue
        key = tuple(key_parts)
        cell = grid.setdefault(key, [0, 0])
        cnt = int(row[cnt_idx])
        cell[0] += cnt
        if str(row[acc_idx]) == ACCEPTED_LABEL:
            cell[1] += cnt
    return grid


def _grid_rows(grid, extra_cols=()):
    """
    Turn an accumulated grid dict into output rows, applying small-cell
    suppression. `extra_cols` is the count of leading key columns before
    (gpa_band, mcat_band); for the plain grid it's 0, for residency it's 1.
    Output column order: <extra keys...>, gpa_bin, mcat_bin, applicants,
    accepted, acceptance_rate, years_pooled, note.
    """
    out = []
    suppressed = 0
    # Stable ordering: extra keys (sorted), then GPA band order, MCAT band order.
    extra_keys = sorted({k[:extra_cols] for k in grid}) if extra_cols else [()]
    for ek in extra_keys:
        for gband in GPA_BAND_ORDER:
            for mband in MCAT_BAND_ORDER:
                key = ek + (gband, mband)
                if key not in grid:
                    continue
                applicants, accepted = grid[key]
                if applicants < SMALL_CELL_MIN:
                    rate = ""
                    note = f"low_n (<{SMALL_CELL_MIN})"
                    suppressed += 1
                else:
                    rate = round(accepted / applicants, 4)
                    note = ""
                out.append(list(ek) + [gband, mband, applicants, accepted,
                                       rate, GRID_YEARS_LABEL, note])
    return out, suppressed


def build_gpa_mcat_grid():
    """
    Build the GPA × MCAT acceptance grid (pooled EY2020-2025) and its
    residency-split sibling, each from ONE grouped cross-tab query.
    Returns (overall_path, residency_path).
    """
    # --- Overall grid: EntryYear × GPA-bin × MCAT-bin × IsAccepted ----------
    rows, _ = run_grouped_count(
        ["EntryYear", GPA_BIN_PROP, MCAT_BIN_PROP, "IsAccepted"],
        "grid_gpa_mcat.json")
    grid = _accumulate_grid(
        rows, key_cols=[(1, gpa_band), (2, mcat_band)],
        year_idx=0, gpa_idx=1, mcat_idx=2, acc_idx=3, cnt_idx=4)
    out_rows, suppressed = _grid_rows(grid, extra_cols=0)
    overall_path = _write_csv(
        "acceptance_by_gpa_mcat.csv",
        ["gpa_bin", "mcat_bin", "applicants", "accepted",
         "acceptance_rate", "years_pooled", "note"],
        out_rows)

    # --- Residency grid: + Residency on the key ----------------------------
    rrows, _ = run_grouped_count(
        ["EntryYear", "Residency", GPA_BIN_PROP, MCAT_BIN_PROP, "IsAccepted"],
        "grid_gpa_mcat_residency.json")
    # Keep only the two real residency classes (drop tiny "Exception").
    rrows = [r for r in rrows if r[1] in ("Texas Resident", "Non Resident")]
    rgrid = _accumulate_grid(
        rrows, key_cols=[(1, None), (2, gpa_band), (3, mcat_band)],
        year_idx=0, gpa_idx=2, mcat_idx=3, acc_idx=4, cnt_idx=5)
    rout_rows, rsuppressed = _grid_rows(rgrid, extra_cols=1)
    residency_path = _write_csv(
        "acceptance_by_gpa_mcat_residency.csv",
        ["residency", "gpa_bin", "mcat_bin", "applicants", "accepted",
         "acceptance_rate", "years_pooled", "note"],
        rout_rows)

    # --- Run summary for the grid ------------------------------------------
    print(f"\nGPA × MCAT grid ({GRID_YEARS_LABEL}):")
    print(f"  overall cells: {len(out_rows)} "
          f"({suppressed} suppressed for n<{SMALL_CELL_MIN})")
    print(f"  residency cells: {len(rout_rows)} "
          f"({rsuppressed} suppressed for n<{SMALL_CELL_MIN})")
    # Spot-check the top-right (high GPA + high MCAT) cell.
    tr = grid.get(("4.00", "515-519"))
    if tr and tr[0]:
        print(f"  GPA 4.00 × MCAT 515-519: {tr[1]}/{tr[0]} = "
              f"{tr[1] / tr[0]:.1%} accepted")
    return overall_path, residency_path


if __name__ == "__main__":
    main()
