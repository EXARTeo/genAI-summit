# SYS-003 Benefits Eligibility Triage: risk management summary (Art. 9)

Status: **draft** by the provider, 2026-01-15. The deployer has not added its own risks.

| # | Risk | Likelihood | Severity | Mitigation | Status |
| --- | --- | --- | --- | --- | --- |
| R1 | Eligible households placed at the end of the queue | Low | High | Caseworker reviews every case | Mitigated |
| R2 | Wrong income threshold after a change in the law | Medium | High | Threshold is a configuration value | Mitigated |
| R3 | Discrimination by nationality | Low | High | Nationality not used by the rules or the score | Mitigated |

## Testing performed

Unit tests of the eligibility rule on 40 hand-made cases (all valid inputs). Accuracy of the priority
score on a held-out set.

## Not covered yet

- Robustness to invalid, missing or extreme inputs (Art. 15): not tested.
- Cybersecurity of the intake form.
- Fundamental-rights impact of queue order on vulnerable applicants (see the FRIA).
