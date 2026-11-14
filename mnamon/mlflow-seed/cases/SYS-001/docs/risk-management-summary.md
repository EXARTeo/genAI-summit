# SYS-001 CV Screener: risk management summary (Art. 9)

Status: **draft**, last reviewed 2026-06-12. Owner: Head of Talent Acquisition.

| # | Risk | Affected | Likelihood | Severity | Mitigation | Status |
| --- | --- | --- | --- | --- | --- | --- |
| R1 | Qualified applicants not shortlisted (false negatives) | Applicants | Medium | High | Recruiter reviews every shortlist | Mitigated |
| R2 | Model uses protected attributes (sex, age, nationality) | Applicants | Low | High | Protected attributes removed from the ranker's features | Mitigated |
| R3 | Parser errors on unusual CV formats | Applicants | Medium | Medium | Parser falls back to safe defaults (region `other`, gap 0) | Mitigated |
| R4 | Over-reliance on the score by recruiters | Applicants | Medium | Medium | Training session for recruiters (planned) | Open |
| R5 | Model drift after hiring-market changes | Provider | Medium | Low | Yearly retraining | Mitigated |

## Testing

- Accuracy against past decisions on a held-out set.
- Bias testing: **not yet performed**. Planned for Q4 2026.

## Residual risk

Judged acceptable by the steering committee, on the condition that recruiters review every shortlist.

## Not yet covered

- Risks from indirect discrimination (features correlated with protected attributes).
- Foreseeable misuse (e.g. using the ranker for other job families).
- Post-market monitoring plan.
