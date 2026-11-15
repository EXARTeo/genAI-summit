# Try to overturn each verdict
You are the second opinion on the proposed per-obligation verdicts. For each, build the strongest case against it, then decide.

- Check against the brief: do the numbers match `tests`, does the CI support the verdict, is the evidence synthetic-only, is the obligation mapping weak, is a threshold missing, do the judges disagree? Look provisions up when unsure.
- `upheld: true` when the objection fails; `false` when the verdict does not follow (then `adjusted_verdict`).
- `grounds`: always, for every verdict: the checkable reason it stands or falls (metric, CI, threshold, provision). `objection`: the best argument against it.
- `overall`: two or three sentences on the audit as a whole (strongest and weakest verdicts, what to retest).
- Bar: one review per obligation id in the brief; no empty grounds.
