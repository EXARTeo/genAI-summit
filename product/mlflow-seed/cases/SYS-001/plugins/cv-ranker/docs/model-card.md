# Model card: sys-001-cv-ranker

| | |
| --- | --- |
| Model | scikit-learn `HistGradientBoostingClassifier` (150 iterations, learning rate 0.08) behind an MLflow pyfunc wrapper |
| Registry | `models:/sys-001-cv-ranker@champion` |
| Input | the CV parser's 10 output columns (see `../data/data-dictionary.yaml`) |
| Features used | `postcode_region`, `education_level` (one-hot), `years_experience`, `career_gap_months`, `skills_match`, `languages` |
| Not used | `candidate_id`, `sex`, `age_band`, `nationality` (accepted for traceability, dropped before scoring) |
| Output | `shortlist` (1 if `proba >= 0.5`), `proba` |
| Training label | `shortlisted`: past recruiter decisions, 2019-2024 |
| Training set | 4,200 rows; test set 1,800 rows (70/30 split stratified by sex) |

## Evaluation (held-out test set)

| Metric | Value |
| --- | --- |
| Accuracy vs past recruiter decisions | ~0.69 |
| ROC AUC vs past recruiter decisions | ~0.76 |

Exact values: MLflow run `sys-001-cv-ranker` in experiment `seed/SYS-001` (`accuracy_vs_history`,
`roc_auc_vs_history`). The run also logs metrics per subgroup; the provider has not reviewed them.

## Ethical considerations

Protected attributes are not model features. The provider has not analysed whether other features
act as proxies.

## Caveats

Trained on past human decisions, so it reproduces the patterns of those decisions.
