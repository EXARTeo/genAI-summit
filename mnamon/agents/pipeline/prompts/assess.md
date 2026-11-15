# Assess each obligation
For every obligation in `obligations`, give the verdict its evidence supports and explain it. Code already computed `rule_verdict` from the organisation's thresholds; an independent judge decides too and a human sees any disagreement.

- `verdict`: `pass` (meets the org threshold with its CI), `partial` (CI crosses it, or a subgroup fails), `gap` (fails it), `inconclusive` (no usable test, no threshold, or the data cannot show it). Keep `rule_verdict` unless the evidence gives a concrete reason not to; say the reason in `reasoning`.
- `reasoning`: two to four sentences with the metric values, CIs and thresholds from `tests`; say the threshold is the organisation's, not the AI Act's.
- `counter_arguments`: the strongest facts against the verdict (synthetic data, sample size, proxy realism). `would_change_if`: results that would flip it.
- `citations`: provision ids from the obligation's `article` or `related` only, with the brief's `kb_version`; check unsure ones with `lookup_provision`.
- `evidence_test_ids`: the result row ids you relied on.
- Bar: one assessment per obligation id in the brief; every number appears in `tests`.
