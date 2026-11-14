# SYS-002 credit scorer

`sys-002-credit-scorer` (MLflow pyfunc around a scikit-learn HistGradientBoostingClassifier).
Input: one applicant row (`applicant_id`, `sex`, `age_band` and seven financial fields). Uses only
`monthly_income, employment_years, credit_history_months, debt_to_income, late_payments_12m,
loan_amount, loan_term_months`; `sex` and `age_band` are accepted for monitoring and ignored.
Output: `score` = P(repaid) and `decision` (`approve` at `score >= 0.5`, else `decline`).

A credit officer takes every decision.
