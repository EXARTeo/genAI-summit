# SYS-001 CV Screener: instructions for use

(Provider information for deployers, structured after AI Act Art. 13.)

## Provider

Example Recruiting S.A. (fictional), Athens. Contact: ai-governance@example-recruiting.invalid.

## Intended purpose

Rank applicants for software-engineering roles and propose a shortlist for a recruiter to review.
Not intended for other job families, for automatic rejection, or for applicants under 18.

## Performance

- Agreement with past recruiter shortlists: about 0.69 accuracy on a held-out set (see the MLflow
  run of `sys-001-cv-ranker`).
- Performance was measured on the whole population only. No per-group results are published.

## Input data

The ATS must provide every raw field listed in `plugins/cv-parser/README.md`. Missing career breaks
are treated as "no break". Postcodes outside Greece map to region `other`.

## Human oversight measures

- A recruiter must review every proposed shortlist before invitations are sent.
- Recruiters should look at applicants with scores between 0.4 and 0.6, which are the least certain.
- Recruiters must not use the score as the only reason to reject an applicant.

## Known limitations

- CVs not in English are under-scored, because the skills match uses English keywords.
- Skills are matched by exact keyword (e.g. "Postgres" is not matched to "sql").

## Logging

The ATS stores each score with the model version for 12 months.

## Maintenance

The ranker is retrained once a year on the latest 5 years of recruiter decisions.
