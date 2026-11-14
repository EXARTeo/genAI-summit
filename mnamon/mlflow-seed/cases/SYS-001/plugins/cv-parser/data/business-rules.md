# CV parser: business rules

- Every application has a candidate id, sex, age and nationality; the ATS rejects forms without them.
- Age is 18-67. Years of experience are 0-45 and at most (age - 16).
- Postcodes are 5-digit Greek postcodes; spaces are allowed ("121 34").
- A career break is given in months; empty means no break.
- Skills and languages are comma-separated lists as typed by the applicant.
- The same CV must always give the same features.
