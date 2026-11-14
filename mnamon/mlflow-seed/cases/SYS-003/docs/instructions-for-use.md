# SYS-003 Benefits Eligibility Triage: instructions for use

(Provider information for the deployer, structured after AI Act Art. 13.)

## Intended purpose

Pre-check eligibility for the minimum-income benefit and order the caseworker queue. Not for
automatic approval or refusal of benefits.

## Performance

Priority score vs past caseworker urgency decisions: accuracy ~0.89, ROC AUC ~0.93 (held-out set).
Eligibility pre-check: identical to the statutory income rule on valid inputs.

## Input data

All fields are required. **The system assumes the intake form validates the data**: household size
1 to 8, dependents fewer than the household size, monthly income EUR 0 to 6,000.

## Human oversight

- Caseworkers decide every case; the estimate shown to the applicant is provisional.
- Caseworkers should open `not_eligible` cases with dependents within 10 working days.

## Known limitations

None reported.
