# SYS-001 CV parser

Rule-based extractor (MLflow pyfunc `sys-001-cv-parser`). Input: one row per applicant with the
raw CV fields `candidate_id, full_name, sex, age, nationality_code, postcode, highest_degree,
years_experience, career_break_months (null = none), skills (comma list), languages (comma list)`.
Output: exactly the ranker's input columns (`candidate_id, sex, age_band, nationality,
postcode_region, education_level, years_experience, career_gap_months, skills_match, languages`).

Mappings: age to 5 bands; ISO country to `GR | EU_other | non_EU`; Greek postcode prefix to
region; degree text to `secondary | bachelor | master | phd`; skills_match = share of the 8
required skills (python, sql, docker, kubernetes, aws, git, linux, pytorch).
