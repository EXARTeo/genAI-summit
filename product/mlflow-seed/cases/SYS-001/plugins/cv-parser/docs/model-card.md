# Model card: sys-001-cv-parser

| | |
| --- | --- |
| Model | rule-based MLflow pyfunc (no learned parameters) |
| Registry | `models:/sys-001-cv-parser@champion` |
| Input | raw CV fields (11 columns, see `../data/data-dictionary.yaml`) |
| Output | exactly the ranker's 10 input columns |

## Rules

| Output | Rule |
| --- | --- |
| `age_band` | 18-24, 25-34, 35-44, 45-54, 55-67 (`unknown` otherwise) |
| `nationality` | `GR`; EU member-state ISO code → `EU_other`; anything else → `non_EU` |
| `postcode_region` | first 3 digits of the Greek postcode → athens_centre, athens_north, athens_west, piraeus, thessaloniki; else `other` |
| `education_level` | PhD/doctorate → `phd`; MSc/master/MBA/MEng → `master`; BSc/BA/BEng/bachelor/ptychio → `bachelor`; else `secondary` |
| `career_gap_months` | the career break in months; missing → 0 |
| `skills_match` | share of python, sql, docker, kubernetes, aws, git, linux, pytorch found in the skills list |
| `languages` | number of listed languages (at least 1) |

## Evaluation

Field-level exact match against the structured ground truth of 6,000 synthetic CVs: 1.00 for every
categorical field (MLflow metrics `parse_exact_match.*`); skills match is quantised to 1/8.
