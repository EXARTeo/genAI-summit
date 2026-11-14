# SYS-002 Consumer Credit Scorer: instructions for use

(Provider information for deployers, structured after AI Act Art. 13.)

## Intended purpose

Creditworthiness assessment of natural persons applying for unsecured consumer loans of
EUR 500-100,000. Not for mortgages, business loans or insurance pricing.

## Performance

| Metric (held-out test set) | Value |
| --- | --- |
| Accuracy | ~0.92 |
| ROC AUC | ~0.94 |
| Approval-rate ratio women / men | ~0.97 |

Per-group accuracy by sex is within 1 point. Per-group accuracy by age band is logged in MLflow
(`accuracy.age_band.*`).

## Input data requirements

All nine applicant fields are required (see `plugins/credit-scorer/docs/api.md`). Income is the
verified net monthly income in EUR. Bureau fields must be at most 30 days old.

## Human oversight

- Use the score together with the applicant file; do not decline on the score alone.
- Applicants with fewer than 24 months of credit history: check alternative evidence (rent, utility
  payments) before deciding.

## Known limitations

Applicants with short credit histories have less reliable scores (see known-issues.md).
