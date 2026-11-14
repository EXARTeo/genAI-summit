# SYS-001 candidate ranker

`sys-001-cv-ranker` (MLflow pyfunc around a scikit-learn HistGradientBoostingClassifier). Input:
the CV parser's output columns. It uses only `postcode_region, education_level, years_experience,
career_gap_months, skills_match, languages`; `sex`, `age_band` and `nationality` are accepted but
ignored. Output: `shortlist` (0/1, threshold 0.5) and `proba`.

The recruiter reviews every shortlist. The provider states that the model "does not use protected
attributes", which is true for direct use.
