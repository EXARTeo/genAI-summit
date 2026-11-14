# SYS-002 Consumer Credit Scorer: change log

| Date | Version | Change |
| --- | --- | --- |
| 2024-06-01 | 1.0 | Scorecard (logistic regression) on 2018-2023 loans |
| 2025-06-15 | 2.0 | Gradient boosting; added `credit_history_months`; removed `age` as a feature |
| 2026-06-01 | 2.1 | Retrained on 2018-2024 loans (120,000 applications) |
| 2026-11-14 | registry | Registered in MLflow as `sys-002-credit-scorer`, alias `champion` |
