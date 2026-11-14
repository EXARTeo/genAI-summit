# SYS-003 Benefits Eligibility Triage: system specification

Deployer: Social Services Unit, Municipality of Kallithea (fictional deployment).
Provider: CivicLogic Software IKE (fictional). Version 1.2, 2026-08.

## Purpose

Pre-check applications for the national minimum-income benefit, estimate the monthly amount and
order the caseworker queue, so urgent cases (families with children, persons with disability, very
low income) are seen first. About 600 applications a month; 9 caseworkers.

## Users

- **Caseworkers**: see the queue ordered by triage (`fast_track` first), the eligibility pre-check
  and the estimated amount; they decide every case.
- **Applicants**: apply online or at the counter; a caseworker enters counter applications.

## Workflow

1. Intake form (online or counter) → case row (household size, dependents, income, employment,
   disability, region).
2. **Benefits triage** (`sys-003-benefits-triage`):
   - eligibility rule: income per household member below EUR 550 a month (EUR 800 with a
     recognised disability);
   - estimated benefit: half the shortfall below the threshold, times household size;
   - priority score (logistic regression trained on past caseworker urgency decisions);
   - triage: `fast_track` if eligible and score >= 0.5, `standard` if eligible, else `not_eligible`.
3. Caseworkers work the queue in triage order and decide.

## Decisions it influences

How quickly an application is handled and the first estimate of the benefit shown to the applicant.

## Human oversight

Every application is decided by a caseworker. `not_eligible` cases are still reviewed, but at the
end of the queue (median wait 19 days vs 4 days for `fast_track`).
