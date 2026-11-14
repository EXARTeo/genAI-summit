# SYS-001 CV Screener: system specification

Owner: Example Recruiting S.A. (fictional), Talent Acquisition / Data team. Version 1.3, 2026-09.

## Purpose

The CV Screener helps in-house recruiters handle the volume of applications for software-engineering
roles (about 800 applications a month across 25-30 open positions). For each application it extracts
structured facts from the CV and proposes whether the applicant should be on the shortlist for a
first interview.

## Users

- **Recruiters** (12 people, Athens and Thessaloniki offices): see the ranked list and the
  shortlist proposal in the applicant-tracking system (ATS).
- **Hiring managers**: see only the shortlist the recruiter approved.
- **Applicants** do not interact with the system; they submit a CV through the careers page.

## Workflow

1. The applicant submits a CV on the careers page. The ATS extracts the raw fields (age, nationality,
   postcode, degree, years of experience, career breaks, skills, languages).
2. **CV parser** (`sys-001-cv-parser`): normalises the raw fields into features (age band,
   nationality group, postcode region, education level, skills match against the role's 8 required
   skills, number of languages).
3. **Candidate ranker** (`sys-001-cv-ranker`): scores each applicant (`proba`) and proposes
   `shortlist = 1` when the score is at least 0.5.
4. The recruiter reviews the ranked list, can add or remove anyone, and approves the shortlist.
5. Applicants not shortlisted receive a standard e-mail after the recruiter closes the position.

## Decisions it influences

Who is invited to a first interview. The system does not reject anyone by itself, but in practice
recruiters rarely look beyond the proposed shortlist when a position has more than 60 applicants.

## Human oversight

- Every shortlist is approved by a recruiter.
- Recruiters can see the score but not the reasons behind it (no explanations are provided yet).
- There is no periodic review of shortlist outcomes by group.

## Out of scope

Salary decisions, internal promotions, and roles other than software engineering.
