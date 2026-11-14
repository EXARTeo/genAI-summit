# Review one test scenario
Judge whether this scenario is a sound test of this system before a human approves the plan. You judge; you do not redesign the plan.

- `relevant`: it tests a requirement in `applicable_requirements`, through inputs and an output the plugin really has, with a metric that measures the expected behaviour, and it covers the proxies in `model_profile`.
- `needs_change`: the right requirement, but the test misses (a detected proxy without `causal`/`proxy_only` twins, a field the plugin lacks, a metric that misses the behaviour). `suggested_change`: the fix, one sentence.
- `not_relevant`: its requirement is not applicable to this system, or the test cannot touch this model's decision.
- `rationale`: one or two sentences naming the requirement id, field or proxy you relied on. `confidence`: 0 to 1.
