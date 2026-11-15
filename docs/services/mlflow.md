# MLflow and the seed job

Two containers in `mnamon/docker-compose.yaml`:

| Service | Folder | What it does |
| --- | --- | --- |
| `mlflow` | `mnamon/mlflow/` | MLflow 3.17.2 tracking server + model registry. Long-running. |
| `mlflow-seed` | `mnamon/mlflow-seed/` | One-shot job: generates synthetic data, trains, evaluates and registers the demo systems' models, then exits 0. |

## `mlflow` server

- `entrypoint.py` creates the `mlflow` database on the product `postgres` if missing (psycopg2, same
  idea as the agents service's `agent_runtime`), then execs
  `mlflow server --artifacts-destination /mlartifacts --serve-artifacts --host 0.0.0.0 --port 5000`.
  The backend store URI goes through `MLFLOW_BACKEND_STORE_URI` (env, not argv, so the password is not
  visible in `ps`).
- Artifacts are proxied: clients upload/download through the server (`mlflow-artifacts:/`), stored in
  the `mlflow_artifacts` volume. Nobody needs direct file or S3 access.
- Internal URI `http://mlflow:5000` (network `backend`); UI and API on the host at
  <http://localhost:5500> (`MLFLOW_PORT`).
- MLflow 3 rejects unknown `Host` headers (DNS-rebinding guard): `MLFLOW_ALLOWED_HOSTS` (fnmatch
  patterns) allows `mlflow:*`, `localhost:*` and `127.0.0.1:*` by default.
- Healthcheck: `GET /health`. Runs as uid 1000, no capabilities.
- Why 3.17.2: the newest release at least two weeks old on 2026-11-14 (3.18.0 is from 2026-11-03).
  The gateway uses `mlflow-skinny==3.18.0`; models logged with 3.17.2 load there (verified).

## `mlflow-seed` job

`python seed.py` (the container's command), for each case folder `cases/SYS-00X/`:

1. **Idempotency:** `seed_hash` = sha256 of the case folder + the seed code (`seedlib/`,
   `seedmodels/`, `seed.py`, `requirements.txt`; line endings normalised). If every model of the case
   already has a `champion` version tagged with that hash, the case is skipped.
2. **Generate** (docs/architecture/synthetic-data.md): `seedlib/sampler.py` reads the plugin's
   `data/data-dictionary.yaml` and does ancestral sampling over the causal graph (`depends_on` +
   `conditional`, distributions `choice | poisson | normal | lognormal | uniform | beta | bernoulli`),
   enforces the `hard` rules (resample the row up to 10 times, then drop), adds the `label_rule`
   column. Rule expressions go through a whitelist AST evaluator (`seedlib/expr.py`, no `eval`).
   Fixed seed per case (`scenarios.generation.seed` in `plugin.yaml`). Synthetic only: names come from
   curated fake lists.
3. **Label + train:** each `seedlib/systems/sys00X.py` adds the outcome (with the planted mechanism)
   and trains a scikit-learn model wrapped in an MLflow pyfunc from `seedmodels/` (shipped with the
   model via `code_paths`).
4. **Evaluate:** overall and per-subgroup metrics (`<metric>.<attribute>.<group>`: `selection_rate`,
   `accuracy`, `tpr`; summaries `selection_rate_ratio.<attr>`, `accuracy_gap.<attr>`,
   `equal_opportunity_gap.<attr>`), counterfactual flip rates (`cf_flip_rate.<attr>.cp|causal`,
   `cf_flip_rate.postcode_region.proxy_only`), robustness rates for SYS-003.
5. **Register** in experiment `seed/SYS-00X`: params, metrics, `mlflow.data` dataset inputs
   (training / evaluation / edge_cases), `evaluation/data-card.yaml` + `sample.csv`, the model with
   signature + input example + pinned pip requirements (the gateway's versions), model-version tags
   `system_id`, `annex_basis`, `intended_purpose`, `risk_class`, `plugin`, `seed_hash`, `run_id`, and
   alias `champion`.
6. **Export** (`SEED_CASES_DIR=/seed-cases`, volume `seed_cases`): `systems/SYS-00X/` = the dossier
   **without** `_answer-key/`; `answer-keys/SYS-00X/` = the answer key, kept apart so it is never
   imported into the folder the agent reads.

Audit test runs land next to the seed runs: `synthkit run-tests` (sandbox) logs one run per test in
experiment `compliance/SYS-00X` (tags `template`, `req_ids`, `card_version`, `kb_version`,
`dataset_id`, `status`; metrics with `.ci_low` / `.ci_high`; artifact `test-result.json`). See
[sandbox.md § run-tests](sandbox.md#synthkit-run-tests).

Flags: `--only SYS-002`, `--force` (or `SEED_FORCE=true`), `--write-samples` (refresh each plugin's
`data/sample.csv` and `data/generated-stats.yaml` from the generator; no MLflow; run it after changing
a dictionary or generator, then commit the files).

## Cases

| System | Annex / article | Models (alias `champion`) | Planted issue (answer key) | Measured (seed run) |
| --- | --- | --- | --- | --- |
| SYS-001 CV Screener | Annex III 4(a), provider | `sys-001-cv-parser` (rules) → `sys-001-cv-ranker` (HistGradientBoosting) | Indirect nationality bias via `postcode_region`; career-gap penalty hits women (equal opportunity) | `selection_rate_ratio.nationality` 0.70, `equal_opportunity_gap.sex` 0.09, `cf_flip_rate.*.cp` 0.00, `cf_flip_rate.nationality.causal` 0.19, `cf_flip_rate.sex.causal` 0.09 |
| SYS-002 Credit Scorer | Annex III 5(b), provider | `sys-002-credit-scorer` (HistGradientBoosting) | Nearly clean; accuracy gap for age 18-25 (thin files) | accuracy 0.92, `selection_rate_ratio.sex` 0.97, `accuracy_gap.age_band.18-25_vs_rest` 0.11 |
| SYS-003 Benefits triage | Annex III 5(a), deployer | `sys-003-benefits-triage` (rules + LogisticRegression) | Art. 15 robustness: crashes on `household_size=0` / missing income, nonsense or silent acceptance on negative/huge values | `robustness.crash_rate` 0.33, `nonsense_rate` 0.17, `silent_acceptance_rate` 0.50, graceful 0 |

Each case folder (agent-context.md § 2/§ 3): `system-card.yaml`, `architecture.yaml`, `gaps.yaml`,
`docs/` (system specification, instructions for use, risk-management summary, DPIA or FRIA summary,
change log), `evidence/README.md`, and per plugin `plugin.yaml`, `README.md`,
`docs/{model-card,api,known-issues}.md`, `data/{data-dictionary.yaml,training-data.md,business-rules.md,sample.csv,generated-stats.yaml}`.
`_answer-key/expected-findings.yaml` lists each planted finding with requirement ids
(`REQ.AIA.…`), metric, direction, threshold and expected magnitude.

## Model naming contract (with `mnamon/model-gateway`)

| Name | Input | Output |
| --- | --- | --- |
| `sys-001-cv-parser` | raw CV fields | exactly the ranker's input columns |
| `sys-001-cv-ranker` | parser output | `shortlist` (0/1), `proba` |
| `sys-002-credit-scorer` | applicant row | `score`, `decision` |
| `sys-003-benefits-triage` | case row | `eligible`, `triage`, `priority_score`, `estimated_benefit_eur` |

All load with `mlflow.pyfunc.load_model("models:/<name>@champion")` and carry a signature. Each
`plugin.yaml` has `access.type: mlflow_model`, `uri: models:/<name>@champion`, plus the alternative
REST block (commented) `http://model-gateway:8000/v1/models/<name>/predict`. Renaming a model breaks
the gateway: change both, and `MODEL_NAMES` in `seed.py`.

## Add a case

1. Create `cases/SYS-00N/` with the files above (copy SYS-002 as the simplest template) and the answer
   key in `_answer-key/`.
2. Write `seedlib/systems/sys00N.py` with `build(case_dir, n=None) -> CaseResult` (generate with
   `seedlib.sampler.generate`, train, evaluate with `seedlib.metrics`, return `ModelSpec`s) and, if
   needed, a pyfunc class in `seedmodels/`.
3. Register it in `BUILDERS` and `MODEL_NAMES` in `seed.py`; run `python seed.py --write-samples`.
4. Add tests in `tests/mlflow_seed/` (planted issue present, schema + rules hold).

## Run and test locally (no Docker)

```bash
cd mnamon/mlflow-seed
uv venv .venv && uv pip install -r requirements.txt --python .venv
.venv/Scripts/python -m mlflow server --backend-store-uri sqlite:///.local/mlflow.db \
  --artifacts-destination .local/artifacts --serve-artifacts --port 5577     # .local/ is git-ignored
MLFLOW_TRACKING_URI=http://127.0.0.1:5577 .venv/Scripts/python seed.py
cd ../.. && mnamon/mlflow-seed/.venv/Scripts/python -m pytest tests/mlflow_seed
```

The suite (34 tests, ~10 s) needs no server and no network: small builds, and one registration
round-trip into a sqlite store in `tmp_path`.

## Configuration

| Variable | Default | Used by |
| --- | --- | --- |
| `MLFLOW_PORT` | `5500` | Host port of the UI/API |
| `MLFLOW_WORKERS` | `2` | Server workers |
| `MLFLOW_ALLOWED_HOSTS` | `mlflow,mlflow:*,localhost,localhost:*,127.0.0.1,127.0.0.1:*` | Host-header allow-list |
| `POSTGRES_USER` / `POSTGRES_PASSWORD` | product Postgres | `mlflow` database credentials |
| `SEED_FORCE` | `false` | Retrain even when the hash matches |
| `SEED_CASES_DIR` | `/seed-cases` (compose) | Export target |
| `MLFLOW_TRACKING_URI` | `http://mlflow:5000` (compose) | Seed job |
