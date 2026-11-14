# CV ranker: business rules (as written by HR)

These are the rules the data must respect and how HR defines a good applicant. The data dictionary
encodes them as `rules` and `label_rule`.

## What valid applicant data looks like

- Applicants are 18 to 67 years old.
- Nobody starts working before 16: years of experience can be at most (age - 16).
- A career break cannot be longer than the working life plus two years
  (`career_gap_months <= years_experience * 12 + 24`). No break is recorded as 0.
- Nobody aged 18-24 holds a PhD.
- Someone aged 45 or older with only secondary education usually has some experience
  (rare exceptions are allowed, up to 5% of applicants).
- Skills match is between 0 and 1 (share of the 8 required skills); languages between 1 and 5.

## Who is qualified (HR definition, used as ground truth)

An applicant is **qualified** for a software-engineering role when all of these hold:

- at least **3 years** of professional experience,
- at least a **bachelor's** degree (bachelor, master or PhD),
- at least **half of the required skills** (`skills_match >= 0.5`).

## Policies

- Sex, age and nationality must not be used to rank applicants.
- Career breaks (parental leave, illness, caring) must not count against an applicant.
- Where someone lives must not matter for on-site roles in Athens or for remote roles.
