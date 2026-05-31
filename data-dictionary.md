# Data Dictionary

All figures are an **unofficial reproduction** of public aggregate statistics
published by TMDSAS (Texas Medical and Dental Schools Application Service) via
their public Power BI stats dashboard
(<https://www.tmdsas.com/stats-dashboard/medical-report.html>). One row in the
source corresponds to one medical-school applicant in a given entry-year cohort;
this project only ever reads pre-aggregated counts and averages, never
individual records.

**Data as of Entry Year 2026 (latest). Extracted 2026-05-30.**

## General notes

- **`entry_year`** is the cohort's intended matriculation year (the source
  field `EntryYear`).
- **Counts are exact integers** as returned by the source measure
  `Count of Total Number of Applicants`.
- **Entry Year 2026 is in progress.** It reports applicant data only; final
  acceptance / matriculation statuses are not assigned until fall 2026, so
  EY2026 `accepted` is partial and `matriculated` is 0.
- **Rate definitions** (computable from the columns, not stored in the files):
  - acceptance rate = `accepted / applicants`
  - interview rate  = `interviewed / applicants`
  - matriculation rate = `matriculated / applicants`
  - yield = `matriculated / accepted`

---

## `data/cleaned/funnel_by_entry_year.csv`

The headline admissions funnel, one row per entry year.

| column | type | definition / derivation |
|---|---|---|
| `entry_year` | int | Cohort year (`EntryYear`). |
| `applicants` | int | Total applicants in the cohort = grand total of the count measure per year. |
| `interviewed` | int | Applicants with `IsInterviewed` = "Interviewed" (i.e. not "no"). |
| `accepted` | int | Applicants with `IsAccepted` not "no". |
| `matriculated` | int | Applicants with `IsMatriculated` = "Matriculated" (not "no"). |

## `data/cleaned/outcomes_by_residency.csv`

Funnel broken out by Texas-residency classification, one row per
(entry year, residency).

| column | type | definition / derivation |
|---|---|---|
| `entry_year` | int | Cohort year. |
| `residency` | string | `Residency` value: `Texas Resident`, `Non Resident`, or `Exception`. |
| `applicants` | int | Applicants in that (year, residency) cell. |
| `interviewed` | int | Of those, count interviewed. From a 3-way group year × residency × `IsInterviewed`. |
| `accepted` | int | Of those, count accepted. From year × residency × `IsAccepted`. |
| `matriculated` | int | Of those, count matriculated. From year × residency × `IsMatriculated`. |

> Sanity-checked: Texas Resident acceptance rate (~40-45% in recent completed
> years) is far higher than Non Resident (~17%), as expected for TMDSAS.

## `data/cleaned/outcomes_by_applicant_type.csv`

Tidy **long** format: one block of rows per applicant-type dimension.

| column | type | definition / derivation |
|---|---|---|
| `entry_year` | int | Cohort year. |
| `dimension` | string | One of `reapplicant`, `nontraditional`, `military`. |
| `in_group` | int | Count of applicants for whom this flag is TRUE in the cohort. |
| `applicants_total` | int | Total applicants in the cohort (same as funnel `applicants`; repeated for convenience). |
| `interviewed` | int | Interviewed applicants **within the in-group**. |
| `accepted` | int | Accepted applicants within the in-group. |
| `matriculated` | int | Matriculated applicants within the in-group. |

Flag derivation (source column → "true" value):

- `reapplicant`: `Reapply` = "Reapplicant"
- `nontraditional`: `NonTrad` = "Non-Traditional"
- `military`: `MilitaryYN` = "Y"

> **The three applicant-type flags are INDEPENDENT and NOT mutually
> exclusive** — a single applicant can be a reapplicant *and* non-traditional
> *and* military. The blocks must not be summed together as if they
> partitioned the cohort.
>
> **Non-traditional was not tracked before Entry Year 2020.** For EY2016-2019
> the non-traditional `in_group` (and its outcomes) are 0 because every
> applicant is recorded as "Traditional" in the source for those years; this
> is a source-data limitation, not a zero count of real non-trad applicants.

## `data/cleaned/scores_by_cohort.csv`

Average academic metrics by cohort and entry year.

| column | type | definition / derivation |
|---|---|---|
| `entry_year` | int | Cohort year. |
| `cohort` | string | `all_applicants`, `accepted`, or `matriculated`. The latter two are filtered with a WHERE on `IsAccepted`/`IsMatriculated`. |
| `avg_mcat_total` | float | Average total MCAT (`MCAT`), Power BI Average aggregation. ~500-512 — verified plausible. |
| `avg_cpbs` | float | Average MCAT Chem/Phys (`LastCPBS`) section score. |
| `avg_cars` | float | Average MCAT CARS (`LastCARS`) section score. |
| `avg_bbfl` | float | Average MCAT Bio/Biochem (`LastBBFL`) section score. |
| `avg_psbb` | float | Average MCAT Psych/Soc (`LastPSBB`) section score. |
| `avg_overall_gpa` | float | Average overall GPA (`Overall GPA`), ~3.5-3.8. |
| `avg_bcpm_gpa` | float | Average science (BCPM) GPA (`Overall BCPM GPA`). |

> Averages use the Power BI Aggregation Function `1` (Average). Verified: the
> four MCAT section averages sum to approximately the total MCAT average, the
> total sits in the valid 472-528 MCAT band (~506 all-applicants), and the
> accepted/matriculated cohorts score higher than all-applicants — all
> consistent with real admissions data. Values are rounded to 3 decimals.
