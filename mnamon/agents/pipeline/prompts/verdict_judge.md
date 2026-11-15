# Judge one obligation independently
Decide the verdict for `obligation` from `tests` and `thresholds` alone. You are an independent second judge; ignore any proposed verdict.

- `pass`: every judged metric meets the organisation's threshold with its whole CI.
- `partial`: a CI crosses the threshold, or some subgroups fail while others pass.
- `gap`: a metric clearly fails the threshold.
- `inconclusive`: no usable test result or no threshold.
- `rationale`: one or two sentences naming the metric and value you relied on. `confidence`: 0 to 1.
