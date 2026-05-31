# Data source, provenance & disclaimer

## Source

All figures in `data/` are reproduced from the **Texas Medical & Dental Schools
Application Service (TMDSAS)** public statistics dashboard:

- Dashboard page: https://www.tmdsas.com/stats-dashboard/medical-report.html
- The page embeds a Microsoft Power BI report published with **"Publish to
  web"** — an intentionally public, unauthenticated embed. The numbers in this
  repository were retrieved from that report's public query API (no login, no
  credential other than the public resource key contained in the embed URL).
  See `docs/methodology.md` for the exact, reproducible method.

## Coverage / "data as of"

- **Entry years 2016–2026** for medical-school applicants to TMDSAS member
  institutions.
- **Data as of Entry Year 2026** (the latest cycle present in the dashboard).
  **Extracted: 2026-05-30.**
- **Entry Year 2026 is in progress** — its acceptance counts are partial and
  matriculation is not yet recorded (shown as 0). Do not compute final rates
  from EY2026.

## Disclaimer (please read)

This is an **independent, unofficial reproduction** of publicly published
statistics. This project is **not affiliated with, authorized by, or endorsed
by TMDSAS or The University of Texas System.** "TMDSAS" is named here only to
identify the factual source of the data (nominative use); no TMDSAS branding,
logo, or trademark is used or implied.

Figures are reproduced as published and may contain extraction, rounding, or
interpretation differences. For authoritative numbers, consult the official
dashboard linked above. If you find a discrepancy, please open an issue.

## Licensing

- **Code** (`src/`, `scripts/`, Makefile, config): MIT — see `LICENSE`.
- **Data** (`data/`): CC0 1.0 public-domain dedication — see `LICENSE-DATA`.
  (Raw facts are not copyrightable under *Feist v. Rural*, 499 U.S. 340.)
