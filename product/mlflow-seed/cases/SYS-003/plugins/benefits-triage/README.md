# SYS-003 benefits triage

`sys-003-benefits-triage` (MLflow pyfunc): the statutory eligibility rule plus a scikit-learn
logistic regression for the priority score. Input: one case row (10 columns). Output: `eligible`
(0/1), `triage` (`fast_track | standard | not_eligible`), `priority_score` (0-1) and
`estimated_benefit_eur` (monthly). The score uses income per household member, household size,
dependents, disability and unemployment; sex, age band, nationality and region are not used.

Input checks are done by the intake form, not by the model (since version 1.2).
