# Model card: sys-003-benefits-triage

| | |
| --- | --- |
| Model | eligibility rule + `LogisticRegression` (standardised features), MLflow pyfunc |
| Registry | `models:/sys-003-benefits-triage@champion` |
| Score features | income per member, household size, dependents under 18, disability, unemployed |
| Label | `fast_track` (past caseworker urgency decisions) |
| Training / test | 2,800 / 1,200 rows |

## Evaluation (held-out set; exact values in MLflow, experiment `seed/SYS-003`)

| Metric | Value |
| --- | --- |
| Accuracy (fast_track) | ~0.89 |
| ROC AUC | ~0.93 |
| Fast-track rate ratio by sex / age band / nationality | ~0.98 / ~0.78 / ~0.84 |

## Input handling

The model trusts its input. Validation is the intake form's job.
