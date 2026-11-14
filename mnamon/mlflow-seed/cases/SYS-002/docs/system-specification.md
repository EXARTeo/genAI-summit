# SYS-002 Consumer Credit Scorer: system specification

Owner: Aegean Consumer Finance S.A. (fictional), Credit Risk department. Version 2.1, 2026-07.

## Purpose

Estimate, for each application for an unsecured consumer loan (EUR 500 to 100,000, 12 to 60
months), the probability that the applicant repays without a 90-day default. About 4,000
applications a month through 85 branches in Greece and Cyprus and the online channel.

## Users

- **Credit officers** in branches: see the score, the recommendation (approve / decline) and the
  applicant file in the loan-origination system (LOS).
- **Credit Risk analysts**: monitor approval rates and defaults monthly.

## Workflow

1. The applicant fills in the application (income, employment, loan amount and term).
2. The LOS adds bureau data (credit history length, late payments in the last 12 months, existing
   debt) and calls the scorer.
3. **Credit scorer** (`sys-002-credit-scorer`): returns `score` = P(repaid) and `decision` =
   `approve` when `score >= 0.5`, else `decline`.
4. The credit officer decides. Overrides of a `decline` need a second signature.

## Decisions it influences

Approval or decline of consumer loans; indirectly, the applicant's access to credit.

## Human oversight

Every application is decided by a credit officer; about 6% of recommendations are overridden.
Applicants can ask for a human review of a decline (Consumer Credit Directive).
