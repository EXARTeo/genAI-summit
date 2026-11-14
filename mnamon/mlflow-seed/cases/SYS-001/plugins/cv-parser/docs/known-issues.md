# sys-001-cv-parser: known issues

| # | Issue | Status |
| --- | --- | --- |
| KI-1 | Skills are matched by exact keyword: "PostgreSQL" does not count as "sql", "K8s" not as "kubernetes" | Open |
| KI-2 | Non-Greek postcodes (applicants abroad) all map to region `other` | Accepted |
| KI-3 | A missing age gives `age_band = unknown`, which the ranker ignores | Accepted |
