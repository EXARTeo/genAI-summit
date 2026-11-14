# SYS-001 CV Screener: change log

| Date | Component | Version | Change |
| --- | --- | --- | --- |
| 2025-03-01 | cv-ranker | 1.0 | First pilot: logistic regression on 2019-2023 recruiter decisions |
| 2025-03-01 | cv-parser | 1.0 | Rule-based parser for the ATS fields |
| 2025-09-15 | cv-ranker | 2.0 | Switched to gradient boosting (+3 points accuracy); removed sex, age and nationality from the features |
| 2026-01-10 | cv-parser | 1.1 | Added postcode-to-region mapping and the career-break field |
| 2026-03-20 | cv-ranker | 3.0 | Retrained on 2019-2024 decisions; added `postcode_region` and `career_gap_months` features |
| 2026-11-14 | both | registry | Registered in MLflow as `sys-001-cv-parser` / `sys-001-cv-ranker`, alias `champion` |
