# Judge a regulation change for one system
Decide what a change to the regulation means for this system's existing evidence.

- `no_impact`: the change does not touch a requirement the system's findings or tests rely on, or only its wording changed.
- `reinterpret_existing_evidence`: the existing test results still stand, but their reading against the law changes (a threshold, a scope, a date).
- `rerun_tests`: the same tests must run again (the requirement behind them changed in substance).
- `new_tests_needed`: the change creates an obligation or a case no existing test covers.
- Ground the decision in the diff and the impacted requirements in the brief; name the affected findings and requirements.
- `strongest_counter_argument`: the best case for a different decision. Old decisions are never rewritten; you only propose.
