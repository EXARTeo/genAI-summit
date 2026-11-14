# Write the findings
Turn the test results into findings, one per requirement tested (more when tests disagree).

- `verdict`: `supports_compliance` when the evidence meets the threshold with its CI; `indicates_gap` when it clearly misses it; `inconclusive` when the CI crosses the threshold, the data is unrealistic or the test did not run; `not_assessable_by_testing` for what only documents or process can show.
- `evidence` copies numbers, CIs, thresholds and MLflow run ids from the test results exactly; `threshold_source` says the threshold is the organisation's (system card `org_thresholds`), not the Act's.
- `counter_evidence`: the strongest facts against your own verdict (synthetic population vs training data, twin realism, sample size). `would_change_if`: what result would flip it.
- `citations`: the provision ids behind the requirement, with the brief's `kb_version`. `confidence` follows the CI width and the data's realism.
- Bar: every number in a finding appears in the test results; a reviewer can trace each verdict to a test.
