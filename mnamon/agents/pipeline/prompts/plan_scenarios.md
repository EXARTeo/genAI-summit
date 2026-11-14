# Plan the test scenarios
Turn the applicable requirements into model tests that could actually move this model's decision.

- One scenario per (requirement, behaviour) worth testing; usually 4 to 8. Only requirements whose `testability` is `model_and_data_test`; list the others under `not_testable`.
- Ground every scenario in the model profile: a field that moves the output and stands in for a protected attribute (a proxy) needs counterfactual twins in `causal` and `proxy_only` mode, not only `attribute_only`. Monotone fields get a perturbation test; declared edge cases get an edge-case test.
- `data_needs.fields` uses only fields of the data dictionary; `target` is the plugin id in the brief.
- `metric` names what the test measures; `test_template` is one of the brief's templates.
- Bar: scenarios-check (run after you) finds no high-ranked gap, and a reviewer sees why each test exists from its `rationale`.
