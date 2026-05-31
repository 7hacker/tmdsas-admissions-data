# Methodology

**Data as of Entry Year 2026 (latest). Extracted 2026-05-30.**

This document explains how `src/extract_tmdsas.py` obtains the TMDSAS medical
applicant statistics and how to reproduce the CSV outputs.

## What this is

An **unofficial** reproduction of the public aggregate figures behind the
TMDSAS stats dashboard: <https://www.tmdsas.com/stats-dashboard/medical-report.html>.
The dashboard is a Power BI report embedded with a **public ("publish to web")
resource key**, which means its backing dataset can be queried over HTTP
**without any authentication**. We only ever request pre-aggregated counts and
averages — never row-level applicant data.

## How extraction works

### 1. The API path (no auth, public embed)

The dashboard embeds a Power BI report. Public embeds expose a backend
"querydata" endpoint that accepts the report's `X-PowerBI-ResourceKey` instead
of a user token:

- Host: `https://wabi-us-north-central-h-primary-api.analysis.windows.net`
- Endpoint: `POST /public/reports/querydata?synchronous=true`
- Headers: `X-PowerBI-ResourceKey: <key>`, `ActivityId` + `RequestId` (any
  GUIDs), `Content-Type: application/json;charset=UTF-8`.
- Model coordinates carried in the body: DatasetId
  `35ace578-cc42-4994-8718-91c2ad896b8f`, ReportId / modelId `821982`.

The dataset is a single table, `Sheet1`. Each query is a
`SemanticQueryDataShapeCommand` that groups the measure
`Count of Total Number of Applicants` by one or more columns, or computes an
`Aggregation` (Average) of a numeric column.

### 2. The dsr / run-length decoding (the tricky part)

Results come back in Power BI's compact "data shape result" (`dsr`) form at
`results[0].result.data.dsr.DS[0].PH[0].DM0`. Three layers of compression must
be undone, which `decode_dsr()` handles:

1. **Type header `S`** — the first row carries column metadata (order matches
   `descriptor.Select`: `G0,G1,…` group columns then `M0,…` measures).
2. **Run-length `R` bitmask** — on later rows, if bit *n* of the integer `R`
   is set, column *n* **repeats the previous row's value** and is omitted from
   that row's `C` (cell) array. The decoder carries the previous full row
   forward and splices repeated values back in.
3. **Null `Ø` bitmask** — bit *n* set means column *n* is null (also omitted
   from `C`).

So each row's `C` array holds only the columns not covered by `R`/`Ø`, in
column order; the decoder rebuilds full, aligned rows.

**Dictionary encoding (`ValueDicts`):** string group columns come back as
integer indices. The `S` header tags such a column with a `DN` key (e.g.
`"DN":"D0"`); `decode_dsr()` resolves each index against
`DS[0].ValueDicts["D0"]`. Example: `Residency` → `["Non Resident",
"Texas Resident", "Exception"]`.

### 3. Building the CSVs

- **Funnel**: one grouped-count query per outcome flag (`IsInterviewed`,
  `IsAccepted`, `IsMatriculated`) by `EntryYear`; the "true" bucket is the
  non-`no` dictionary value. Applicants = grand total per year (matches the
  year-only count exactly).
- **Residency**: 3-way groupings `EntryYear × Residency × <outcome flag>`.
- **Applicant type**: independent flags `Reapply`, `NonTrad`, `MilitaryYN`,
  each with a 3-way grouping for in-group outcomes. Long/tidy output.
- **Scores**: Average aggregation (Power BI Function `1`) of `MCAT`, the four
  section scores, and the two GPAs, by `EntryYear`, with optional `WHERE`
  filters for the accepted / matriculated cohorts.

## How to reproduce

No dependencies beyond Python 3 standard library:

```bash
python3 src/extract_tmdsas.py
```

This makes ~20 polite POST requests (one per grouped/averaged query), writes
the raw JSON responses to `data/raw/`, the tidy CSVs to `data/cleaned/`, and
prints a run summary including the funnel table and residency acceptance rates.

## Verification performed

- **Applicant totals match the live dashboard exactly** for every year:
  2016=7323, 2017=7324, 2018=7373, 2019=7715, 2020=7783, 2021=9482, 2022=9173,
  2023=8875, 2024=9005, 2025=9518, 2026=10240. (If the decoder were wrong these
  would misalign — they don't.)
- **Residency split is directionally correct**: Texas Resident acceptance rate
  (~40-45% in recent completed years) ≫ Non Resident (~17%).
- **Score averages are plausible**: total MCAT ~506 for all applicants, higher
  (~512) for accepted/matriculated; section scores sum to the total; GPAs
  ~3.5-3.8. Averages were confirmed to be averages (not sums) before shipping.

## Known caveats

- **EY2026 is in progress / applicant-only.** Final statuses are assigned at
  matriculation in fall 2026, so EY2026 acceptances are partial and
  matriculations are 0. Treat EY2026 rates as not-yet-meaningful.
- **Non-traditional flag begins EY2020.** Earlier cohorts record everyone as
  "Traditional", so non-trad in-group counts are 0 for EY2016-2019 (a source
  limitation, see the data dictionary).
- **Applicant-type flags are non-exclusive** — do not sum the three blocks.
- **Rounding**: score averages are rounded to 3 decimals.
- **Unofficial reproduction.** These numbers are not an official TMDSAS
  publication; they reproduce the public dashboard's aggregates. The public
  resource key and model IDs can change if TMDSAS republishes the report, which
  would require re-confirming them via the report's `conceptualschema`
  endpoint.
