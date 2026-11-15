# Analyse the saved predictions
The model has already been called; its raw predictions are saved. Analyse them with your own code; never call the model.

- Inputs in `../input/`: `inference/predictions.parquet` (`_row_id, _test, _variant, score, decision, error, edge_outcome`), `inference/run.json` (hashes, model version), `data/generated/dataset.parquet` (the rows scored), `test-results.json` (synthkit's metrics over the same predictions), `test-plan.yaml`.
- Write and run short pandas/scipy scripts with `sandbox_execute` (e.g. `cat > a.py <<'X' ... X && python a.py`): subgroup decision rates, twin flip rates per mode, bootstrap CIs, score calibration. Join twins to their base rows by `_twin_of` → `_row_id`.
- `headline`: up to 6 metrics from `test-results.json` you recomputed, with YOUR value; code compares them with synthkit's.
- `observations`: what the numbers show that the headline does not (worst subgroup, proxy effect, CI width). `code_files`: the scripts you ran.
- Bar: every number comes from code you ran over the saved files.
