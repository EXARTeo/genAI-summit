# SYS-002 Consumer Credit Scorer: risk management summary (Art. 9)

Status: approved 2026-05-30 by the Model Risk Committee.

| # | Risk | Likelihood | Severity | Mitigation | Status |
| --- | --- | --- | --- | --- | --- |
| R1 | Discrimination by sex | Low | High | Sex not a feature; approval-rate ratio monitored monthly | Mitigated |
| R2 | Discrimination by age | Medium | High | Age not a feature; reviewed yearly | Partly mitigated |
| R3 | Unreliable scores for thin credit files | Medium | Medium | Officer guidance for < 24 months history | Partly mitigated |
| R4 | Data drift (interest-rate changes) | Medium | Medium | Monthly PSI monitoring, retraining trigger 0.2 | Mitigated |
| R5 | Over-reliance on the score | Low | Medium | Second signature for overrides; officer training | Mitigated |

## Testing performed

Accuracy and AUC on a held-out set; approval-rate ratio by sex. Accuracy per age band: not reviewed
against a threshold.

## Residual risk

Acceptable.
