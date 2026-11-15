# Draft the GenerationSpec
Write the synthkit GenerationSpec that produces the test data for the approved scenarios. Code samples the rows; you only declare what to generate.

- Start from the data dictionary: override a field only when the scenarios need it, and give each override a `provenance` (`dictionary`, `training_doc`, `memory`, `public_data`, `llm_assumption`).
- Fixed keys (`version`, `dictionary`, `plugin`, `model_profile`) are set by code; leave them as in `spec_format`. `n` from the scenarios' needs.
- `coverage.cells` only on categorical fields (a numeric field there makes every value its own cell).
- `generation.mode`: `reference_sample` with the brief's `reference` path when a public dataset was approved; otherwise `zero_shot`.
- Transforms from the scenarios: `twins` (attribute, modes, proxies), `edge_cases` (fields), `perturbation` (fields, delta). Add `strata`, `coverage` (cells, `min_per_cell`) and `boundary` where they make the data informative.
- Only keys synthkit knows; an unknown field or operator fails the next step, which hands you its error.
- Bar: every scenario gets the rows it needs, and every `llm_assumption` is listed under `assumptions` for the reviewer.
