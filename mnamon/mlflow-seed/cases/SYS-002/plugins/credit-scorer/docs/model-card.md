# Model card: sys-002-credit-scorer

| | |
| --- | --- |
| Model | `HistGradientBoostingClassifier` (200 iterations, learning rate 0.06), MLflow pyfunc |
| Registry | `models:/sys-002-credit-scorer@champion` |
| Label | `repaid` (no 90-day default in 24 months) |
| Training / test | 4,200 / 1,800 rows, split stratified by age band |

## Evaluation (held-out test set; exact values in MLflow, experiment `seed/SYS-002`)

| Metric | Value |
| --- | --- |
| Accuracy | ~0.92 |
| ROC AUC | ~0.94 |
| Approval-rate ratio by sex | ~0.97 |
| Equal-opportunity gap by sex | < 0.01 |
| Accuracy by age band | logged as `accuracy.age_band.*` |

## Caveats

Thin credit files (mostly applicants aged 18-25) give less reliable scores.
