# TMDSAS Admissions Data

**An open, machine-readable reproduction of TMDSAS medical-school admissions
statistics — extracted from the official public Power BI dashboard and published
as clean CSVs, with a fully reproducible extraction script.**

> **Data as of Entry Year 2026 (latest cycle). Extracted 2026-05-30.**
> Code: MIT · Data: CC0 1.0 · Unofficial reproduction — see [DATA_SOURCE.md](DATA_SOURCE.md).

The Texas Medical & Dental Schools Application Service (TMDSAS) publishes 10+
years of admissions statistics, but only inside an interactive
[Power BI dashboard](https://www.tmdsas.com/stats-dashboard/medical-report.html)
that search engines can't read and you can't download. This repo **liberates
that data** into plain CSVs anyone can use, and ships the script that pulls it
so the extraction is fully reproducible.

## What's inside

| File | What it covers |
|---|---|
| [`data/cleaned/funnel_by_entry_year.csv`](data/cleaned/funnel_by_entry_year.csv) | Applicants → interviewed → accepted → matriculated, per entry year |
| [`data/cleaned/outcomes_by_residency.csv`](data/cleaned/outcomes_by_residency.csv) | Same funnel split by **Texas resident vs. non-resident** |
| [`data/cleaned/outcomes_by_applicant_type.csv`](data/cleaned/outcomes_by_applicant_type.csv) | Funnel for **reapplicant / non-traditional / military** applicants |
| [`data/cleaned/scores_by_cohort.csv`](data/cleaned/scores_by_cohort.csv) | Average **MCAT** (total + 4 sections) and **GPA** (overall + BCPM) by cohort |
| [`data/raw/`](data/raw/) | Verbatim API responses, kept for audit/trust |
| [`data-dictionary.md`](data-dictionary.md) | Every column defined, with derivation notes |
| [`docs/methodology.md`](docs/methodology.md) | Exactly how the data is extracted + caveats |

### A taste of the data — the medical applicant funnel

| Entry year | Applicants | Interviewed | Accepted | Matriculated |
|---:|---:|---:|---:|---:|
| 2020 | 7,783 | 4,217 | 2,749 | 2,284 |
| 2021 | 9,482 | 4,966 | 2,914 | 2,340 |
| 2022 | 9,173 | 4,516 | 3,235 | 2,774 |
| 2023 | 8,875 | 4,973 | 3,338 | 2,863 |
| 2024 | 9,005 | 5,543 | 3,300 | 2,871 |
| 2025 | 9,518 | 5,568 | 3,295 | 2,900 |

*(Texas residents are accepted at roughly **2.5×** the rate of non-residents —
e.g. EY2024: 42.5% vs 17.6%. See `outcomes_by_residency.csv`. Entry Year 2026 is
in progress and excluded from rate comparisons.)*

## Use the data

The CSVs are tidy and need no special tooling. Quick look with pandas:

```python
import pandas as pd
funnel = pd.read_csv("data/cleaned/funnel_by_entry_year.csv")
funnel["acceptance_rate"] = funnel["accepted"] / funnel["applicants"]
print(funnel)
```

Rate definitions and all caveats are in [`data-dictionary.md`](data-dictionary.md).

## Reproduce the extraction

No browser and no login required — the extractor uses only the Python standard
library and the public resource key embedded in the dashboard URL.

```bash
make setup     # optional: creates a local .venv (the extractor itself needs no deps)
make extract   # pulls fresh data into data/raw/ and data/cleaned/
# or directly:
python3 src/extract_tmdsas.py
```

How it works (and why it's allowed) is documented in
[`docs/methodology.md`](docs/methodology.md).

## Source, attribution & disclaimer

Data originally published by **TMDSAS** at
<https://www.tmdsas.com/stats-dashboard/medical-report.html>. This is an
**independent, unofficial reproduction**, not affiliated with or endorsed by
TMDSAS or The University of Texas System. Full provenance and disclaimer:
[DATA_SOURCE.md](DATA_SOURCE.md).

## Licensing

- **Code** — [MIT](LICENSE)
- **Data** — [CC0 1.0](LICENSE-DATA) (raw facts aren't copyrightable under
  *Feist v. Rural*; we dedicate rather than license)

## Related analysis

A narrative breakdown of these trends — acceptance rates, the Texas-resident
advantage, and the reapplicant question — is published at
[GradPilot](https://gradpilot.com/news/tmdsas-match-system-explained-how-it-works).

## Contributing

Spot a discrepancy against the official dashboard, or want another breakdown?
Please open an issue or PR.
