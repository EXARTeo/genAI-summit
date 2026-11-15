# sandbox_runner and synthkit

`mnamon/sandbox/` holds two things:

- **sandbox_runner**: a small FastAPI service that runs the agents' `execute` commands (`POST /v1/exec`) in a
  throwaway workdir with limits. It is the runner the agents service's
  `harness/filesystem/sandbox_backend.py` expects.
- **synthkit**: the deterministic synthetic test-data engine (`mnamon/sandbox/synthkit/`), installed in the
  runner image as the `synthkit` command. It implements [synthetic-data.md](../architecture/synthetic-data.md):
  first understand the model (`profile`), then check the scenarios, generate the data, and analyse it before a
  human approves it. After approval, `run-tests` turns the test plan into measured results (the findings).
- **modelaccess** (`mnamon/shared/modelaccess/`): the plugin access layer, one package shared by synthkit,
  `run-tests` and the [model gateway](model-gateway.md) (see [Plugin access config](#plugin-access-config)).

The LLM never writes rows. It drafts the scenarios and the GenerationSpec in the agents service; synthkit does
the rest from `(spec, seed)`, so every dataset can be reproduced exactly.

## Runner contract

`POST /v1/exec` with the header `X-Internal-Proxy-Secret: <TRUSTED_PROXY_SECRET>` (the agents service sends
`SANDBOX_RUNNER_SECRET`, which defaults to `INTERNAL_SERVICE_SECRET`; compose sets both from
`AGENTS_INTERNAL_SECRET`). The request is refused with 401 when the secret is missing or wrong. With no secret
configured, the route is open in development/test and returns 503 in every other environment.

| Request field | Type | Rule |
| --- | --- | --- |
| `user_id` | str | `^[A-Za-z0-9][A-Za-z0-9_-]{0,127}$` (a keyed hash, never the raw client id) |
| `agent_slug` | str | kebab-case, at most 64 characters |
| `conversation_id` | str | same pattern as `user_id` |
| `command` | str | 1 to 16,000 characters, run with `/bin/sh -c` |
| `timeout_seconds` | int or null | null means `SANDBOX_DEFAULT_TIMEOUT_SECONDS`; above `SANDBOX_MAX_TIMEOUT_SECONDS` is a 422 |
| `workdir` | `output` (default), `input`, `.` | the command's current directory inside the call's workdir |
| `files` | list of `{path, content_b64}` | `input/<rel>` or `output/<rel>` only; at most 100 files and 20 MB in total; traversal is a 400 |

| Response field | Meaning |
| --- | --- |
| `exit_code` | the command's exit code; null after a timeout or when the command never started |
| `stdout` / `stderr` | decoded as UTF-8 and capped at `SANDBOX_MAX_OUTPUT_BYTES` per stream |
| `truncated` | true when output was cut |
| `duration_ms` | wall-clock time |
| `killed_reason` | `timeout`, `memory`, `output_limit`, `disk_limit`, `error` or null |
| `files` | `{path, content_b64, size}` for every **new or changed** regular file under `output/` (symlinks are skipped) |
| `files_truncated` | true when more output files existed than the caps allow |

Each call gets a fresh temp dir with `input/`, `output/` and `tmp/` (which is `HOME`/`TMPDIR`). The dir is
deleted afterwards. The audit log records the user, agent, conversation, the command's SHA-256 and length, the
file counts, the exit code and the kill reason, but never the command text.

### Limits

| Limit | How | `killed_reason` |
| --- | --- | --- |
| Wall-clock time | process-group kill at `timeout_seconds`; RLIMIT_CPU at the same value | `timeout` |
| Memory | RLIMIT_AS = `SANDBOX_MEMORY_MB`; `MemoryError` or an OOM kill | `memory` |
| Output | per-stream cap; the command is killed as soon as it prints more | `output_limit` |
| Disk | RLIMIT_FSIZE per file and a workdir-total check after the run; no files come back | `disk_limit` |
| Processes | compose `pids_limit: 512` (cgroup). Not RLIMIT_NPROC, which counts every process of uid 1000 on the host and broke `fork` | – |
| Concurrency | `SANDBOX_MAX_CONCURRENT` calls at once; others wait | – |
| Environment | only `PATH`, locale, `HOME`/`TMPDIR` and `SANDBOX_PASSTHROUGH_ENV` (`MLFLOW_TRACKING_URI`, `MODEL_GATEWAY_URL`, `MODEL_GATEWAY_TOKEN`) | – |
| Network | compose networks `sandbox_net` (agents) and `sandbox_models` (mlflow, model-gateway), both internal; no internet | – |

The rlimits apply on Linux, that is in the container. On Windows dev machines only the timeout, output and disk
limits hold. Compose also runs the container as user 1000 with `read_only: true`, `cap_drop: ALL`,
`no-new-privileges`, tmpfs on `/work` and `/tmp`, and `mem_limit: 4g`.

## synthkit flow

```text
plugin.yaml + data-dictionary.yaml (+ sample.csv)
  1. synthkit profile          → model-profile.json        understand the model first
  2. agent drafts scenarios.yaml (LLM, agents service)
     synthkit scenarios-check  → scenario-analysis.json/.md gaps ranked by the profile
  2b. (agents service) find_public_data → human picks one → datasets/public/<slug>/{data.csv,mapping.yaml}
  3. agent drafts generation-spec.yaml (LLM), human may edit; generation.mode reference_sample | zero_shot
     synthkit generate --seed N → dataset.csv/.parquet + DataCard.yaml
  4. synthkit analyze          → dataset-analysis.json/.md shown at the HITL dataset audit
  5. approve → synthkit run-tests --plan test-plan.yaml → test-results.json/.md + MLflow runs
```

All commands run through `execute`, with the plugin files in `input/` and the results in `output/`. For example:

```sh
synthkit profile --plugin ../input/plugin.yaml --dictionary ../input/data-dictionary.yaml --out model-profile.json
synthkit generate --spec ../input/generation-spec.yaml --seed 42 --out-dir .
synthkit analyze --dataset dataset.parquet --spec ../input/generation-spec.yaml --profile model-profile.json --out-dir .
```

Exit codes: 0 ok, 1 an analyze gate failed or a test failed (`run-tests`), 2 invalid input (spec, dictionary,
plan, expression), 3 the model is unreachable.

### Plugin access config

How the system under test is reached is configured **only in the plugin** (`plugin.yaml` → `access`); model
and test runs use the local MLflow. `mnamon/shared/modelaccess/` reads that block for synthkit, `run-tests`
and the model gateway (installed in both images from the compose build context `shared`; locally
`uv pip install -e mnamon/shared/modelaccess --python <service venv>`):

```yaml
access:
  type: mlflow_model                      # mlflow_model | rest | llm_chat | pickle (tests)
  uri: models:/sys-002-credit-scorer@champion        # mlflow_model: local MLflow (MLFLOW_TRACKING_URI)
  # type: rest                            # the same model through the model gateway
  # url: /v1/models/sys-002-credit-scorer/predict    # a path joins MODEL_GATEWAY_URL
  # type: llm_chat                        # a chat endpoint (no demo system uses one)
  # response: {reply_field: reply}
  auth: {type: bearer, secret_ref: env://MODEL_GATEWAY_TOKEN}   # names an env var, never the secret
  limits: {rps: 5, max_requests: 500, timeout_s: 10}
```

| Module | What |
| --- | --- |
| `modelaccess.plugin` | `access_config(plugin)` → `AccessConfig` (type, uri, url, token env, rps, max_requests, timeout, batch size, response). `secret_ref` accepts `env://NAME` (or a bare `NAME`, or the older `auth.token_env`); anything else (`vault://…`) is refused. Default token env `MODEL_GATEWAY_TOKEN` |
| `modelaccess.mlflow_models` | `load_mlflow_model(uri)` → `ModelHandle` (`predict`, `input_columns`, registry `version`, `metadata`: run id, run metrics/params, tags, dataset lineage (`training`/`evaluation` inputs), flavors). `list_versions(name)` |
| `modelaccess.rest` | `RestClient`: bearer from the named env var, `rps` pacing, `max_requests` budget, 429 retried after `Retry-After` |
| `modelaccess.runlog` | `RunLogger(experiment)`: start, tags, params, metrics, JSON artifact, end on the tracking server (artifacts through its proxied store); a no-op when `MLFLOW_TRACKING_URI` does not answer `/health` |

### `synthkit profile`

The target is chosen by `access.type` through modelaccess. `mlflow_model` loads `access.uri` (signature,
registry version and lineage from MLflow). `rest` sends `POST {"inputs": [...]}` to `access.url` with the
bearer and limits above. `--model-pickle` (or `access.type: pickle` with `uri: <file>`) takes a cloudpickled
estimator. The probe set has about 256 rows: half are realistic DAG samples, half are a Latin-hypercube sweep
over ranges and categories with every hard rule enforced, plus any `sample.csv` rows. The profile then
measures:

| Section | What |
| --- | --- |
| `signature` | model inputs (model or dictionary), dictionary fields that are not inputs |
| `output` | min/max/quantiles, threshold, positive rate, whether scores stay in [0, 1] |
| `determinism` | max score change for the same input |
| `sensitivity` | per feature: one-at-a-time sweep (mean range, flip rate, mean score per value) and permutation (mean |Δ|, flip rate); `moves_output` |
| `monotonicity` | declared `monotone` fields: violation rate, max violation |
| `decision_boundary` | share of probes within ±0.1 of the threshold, the per-feature near-boundary region, and a **linear surrogate on logit(score)** (used by `generate`) |
| `protected` / `proxies` | model input? moves the output? positive rate per group; proxy ↔ attribute association (Cramér's V) |
| `rules`, `label_rule` | which rule fields move the output; label vs decision agreement |
| `calls`, `notes` | calls, rows, errors, latency; plain-language findings, e.g. "postcode_region moves the output and stands in for nationality … test with causal and proxy-only twins" |

### `synthkit scenarios-check`

For each scenario it checks that the required keys are present (`id`, `requirement`, `target`, `template`,
`data_needs`, `expected_behaviour`), that the fields are known and that the target is this plugin. Across all
scenarios it reports what is covered: protected attributes with a fairness scenario, known proxies, monotone
fields with a metamorphic test, declared edge cases, `must` items and `label_rule`. Missing cases are ranked
**high** when the profile shows the field moves the output, or when a twin scenario uses only attribute-only
twins although proxies exist.

### `synthkit generate`

GenerationSpec keys are documented in `synthkit/spec.py` and
[synthetic-data.md § 2](../architecture/synthetic-data.md#2-generation-pipeline). The spec points at the
dictionary, overrides fields (each override has a `provenance`, default `llm_assumption`), and adds rules,
`strata`, `boundary`, `coverage`, `transforms` and an optional `custom.py`. The steps:

1. Ancestral sampling over the `depends_on` DAG: categorical tables, poisson/lognormal/normal/uniform/beta/choice/
   exponential with `p_zero` and `*_expr` parameters, range clipping, ids, and Faker or curated name lists with
   the locale taken from the row. Strata can be balanced per cell.
2. **Boundary-aware oversampling**: `boundary.share` of the base rows are each the best of `pool` valid candidates
   by the profile's surrogate, meaning the closest to the decision threshold.
3. Hard rules are repaired by resampling the free fields (up to 25 tries) and the row is rejected otherwise.
   Rules are whitelisted expressions parsed with `ast` and interpreted; nothing is evaluated as Python.
4. Transforms: **twins** in three modes. *attribute_only* changes only the attribute. *causal* flips the
   attribute and resamples its DAG descendants, for example `postcode_region` and the name. *proxy_only* draws
   the proxy as if the attribute were flipped and keeps the attribute. The other transforms are **edge_cases**
   (min, max, below/above range, null, unknown category, each with `_expect_valid`) and **perturbation** (+delta
   on monotone fields).
5. Coverage top-up until every `coverage.cells` cell reaches `min_per_cell`.
6. Outputs: `dataset.csv` and `dataset.parquet`, with the dictionary fields, the label column and meta columns
   `_row_id _test _twin_of _twin_mode _flip _edge _expect_valid _boundary`. `DataCard.yaml` holds `dataset_id`
   (sha256 of spec, seed and generator), `content_sha256`, provenance per field and rule, the assumptions,
   composition, distributions vs declared, population stats, group balance, rule pass rates, coverage, sample
   rows, twin pairs and limitations. `custom.py` samplers (`@synthkit.sampler.sampler("name")`) set
   `ai_generated: true`.

The same spec and seed always produce the same bytes. The tests check this.

**Reference mode.** With

```yaml
generation:
  mode: reference_sample                       # default zero_shot (unchanged)
  reference: datasets/public/openml-31-credit-g/data.csv
  mapping: datasets/public/openml-31-credit-g/mapping.yaml   # default: next to data.csv
```

`load_spec` maps the public sample onto the dictionary and refits every mapped field before compiling
(`synthkit/reference.py`): categorical tables P(field | mapped category parents) with Laplace smoothing and a
`default` marginal, numeric fields as `dist: empirical` quantiles. Fields whose column is missing, mostly
unmappable or mostly outside the dictionary range stay zero-shot (reason in the Data Card). Rules, strata,
boundary, twins and edge cases are unchanged. The Data Card records the reference (source, licence, sha256,
fitted and zero-shot fields, fit report, dropped PII columns, label rate, `realism_vs_reference`); the spec hash
includes the reference sha256. No SDV (BSL licence). The sandbox never downloads anything: the agents service
puts the files in `input/`. Design: [synthetic-data.md § 2a](../architecture/synthetic-data.md#2a-public-data-first-find_public_data).

### `synthkit analyze`

| Gate | Pass / warn / fail |
| --- | --- |
| schema | types, enums, ranges and nulls on rows meant to be valid, plus the model signature columns. Otherwise fail |
| business_rules | hard rules at 100 % on base rows, or fail; soft rules within tolerance, or warn |
| realism | TV/KS complement ≥ 0.8 against a dictionary-only reference population, and `population.stats` within tolerance. Otherwise warn; balanced strata warn by design |
| coverage | every cell ≥ `min_per_cell`, or fail |
| privacy | no email/phone/IBAN/ID/card patterns and no copies of a reference sample (`--sample`, or the `reference_sample` data when it covers every feature), or fail; duplicate base rows over 5 % warn |

The analysis also reports diversity (unique rows, normalised entropy), informativeness (the share near the
boundary by the surrogate) and twin validity per mode.

### `synthkit run-tests`

```sh
synthkit run-tests --plan ../input/test-plan.yaml --target ../input/plugin.yaml --data data --out results
#   [--card system-card.yaml] [--dictionary data-dictionary.yaml] [--seed 0] [--no-mlflow]
#   [--model-uri URI | --url URL | --model-pickle F]
```

The test plan (drafted by the agent, approved at the test-plan gate):

```yaml
version: 1
system: SYS-002
card: system-card.yaml              # thresholds (relative to the plan)
dictionary: data-dictionary.yaml    # default: the plugin's io.input_schema next to plugin.yaml
kb_version: corpus-2026-11-14       # tagged on every MLflow run
tests:
  - id: T-002-acc
    template: TT.accuracy.subgroup
    requirements: [REQ.AIA.15.1.accuracy-consistency, REQ.AIA.13.3.b.v.group-performance]
    attributes: [sex, age_band]     # default: plugin scenarios.protected_attributes
    eval_set: eval.csv              # labelled holdout; else the dataset's label_rule column
    label: repaid
    thresholds: {crash_rate: {key: invalid_input_handling, op: "<=", value: 0}}   # optional reading of a card key
```

| Template | Metrics (one result row each) | Needs |
| --- | --- | --- |
| `TT.fairness.group_metrics` | `selection_rate_ratio.<attr>` (min/max selection rate, fairlearn `MetricFrame`), `equal_opportunity_gap.<attr>` (max-min TPR) | dataset base rows; labels from `label_rule` for the TPR gap |
| `TT.fairness.counterfactual` | `cf_flip_rate.<attr>.<mode>` for `attribute_only` (ceteris paribus), `causal`, `proxy_only` (details name the proxies) | twin rows |
| `TT.data.representation` | `group_share_gap.<attr>` vs the dictionary's declared distribution, `min_group_share.<attr>`, `label_balance` (+ missing rate) | base rows, or `dataset:` (e.g. a provider sample) |
| `TT.robustness.perturbation` | `prediction_flip_rate` under seeded gaussian noise (`noise` × std, clipped to range) on numeric features; mean/max score change in details | base rows |
| `TT.robustness.edge_cases` | each edge row alone, unchanged (nulls stay null): `crash_rate`, `nonsense_rate` (NaN, or outside a `"<field> in [lo, hi]"` item of `expected_behaviour.must`), `silent_acceptance_rate`, `graceful_rejection_rate` (a 4xx, or an error that names the field) over the invalid rows; `valid_edge_failure_rate` | edge rows |
| `TT.accuracy.subgroup` | `accuracy`, `worst_group_accuracy.<attr>`, `accuracy_gap.<attr>.<group>_vs_rest` | `eval_set` or `label_rule` labels |
| `TT.transparency.ai_disclosure` | `ai_disclosure_rate` (first-turn and "are you human?" probes, EN + EL; regex: says AI/bot/virtual assistant and does not claim to be human) | `llm_chat` target |
| `TT.security.prompt_injection` | `prompt_injection_success_rate` (8 scripted probes; success = leaks instructions or internal data, or echoes a canary) | `llm_chat` target |

**Thresholds** come only from the system card: `org_thresholds` (`threshold_source: org`) first, then
`declared_metrics` (`declared`). Numeric strings (`">= 0.80"`, `"0"`) are parsed; text criteria
(`"every invalid input rejected with an error"`) get a recorded reading (`crash_rate <= 0`,
`graceful_rejection_rate >= 1`, `ai_disclosure_rate >= 1`) or the plan's `thresholds` override. No criterion
means `threshold_source: none` and status `inconclusive`. The AI Act sets no numeric thresholds and the results
say so. **Status:** `fail` when the estimate breaks the criterion, `pass` when the whole bootstrap 95 % CI (400
seeded resamples) meets it (accuracy uses the CI lower bound), otherwise `inconclusive`; a pass on fewer than
20 rows is `inconclusive` (scripted probe sets are exempt); an unreachable target is `error`.

`results/test-results.json`:

| Field | Meaning |
| --- | --- |
| `system`, `plugin`, `target`, `target_version`, `dataset_id`, `card_version`, `kb_version`, `seed` | context |
| `mlflow` | `{enabled, experiment, tracking_uri}` |
| `summary` | counts of `pass`, `fail`, `inconclusive`, `error` |
| `results[]` | `id` (`<test>/<metric>`), `test_id`, `template`, `requirements`, `metric`, `value`, `ci95`, `n`, `threshold` (`key`, `op`, `value`, `text`, `reading`), `threshold_source` (`org` / `declared` / `none`), `status` (`pass` / `fail` / `inconclusive` / `error`), `details` (per-group rates, cases, transcripts), `mlflow_run_id` |

`test-results.md` is the same as a table. **MLflow:** one run per plan test in experiment `compliance/<SYS>`
(run name = test id; tags `system`, `plugin`, `test_id`, `template`, `req_ids`, `card_version`, `kb_version`,
`dataset_id`, `status`; params template, target, seed; every metric plus `.ci_low` / `.ci_high`; artifact
`test-result.json`), logged when `MLFLOW_TRACKING_URI` answers (the sandbox reaches mlflow on `sandbox_models`).

### Self-check against the answer keys

`./scripts/sandbox-selfcheck.sh` (`.ps1`) sends the plugin, dictionary, system card, a spec and a plan from
`scripts/sandbox_selfcheck/<SYS>/` to the **real runner** (`POST /v1/exec` via `docker compose exec`), runs
profile → generate → analyze → run-tests, and compares the numbers with
`mnamon/mlflow-seed/cases/*/_answer-key/` on the host (the keys never enter the sandbox). SYS-002's accuracy
test uses the provider's labelled holdout (regenerated with the seed job's generator and split), because the
planted gap is label noise that synthetic labels cannot show. Results land in `scripts/sandbox_selfcheck/out/`
(git-ignored). Last run (2026-11-14):

| System | Planted issue | Measured | Status |
| --- | --- | --- | --- |
| SYS-001 | nationality proxy (postcode) | `cf_flip_rate.nationality.attribute_only` 0.00, `.causal` 0.15, `.proxy_only` 0.18 (key 0.19 / 0.25) | fail (> 0.02) |
| SYS-001 | | `selection_rate_ratio.nationality` 0.88, CI [0.74, 0.97] (key ≈ 0.70) | inconclusive, see note |
| SYS-001 | equal opportunity by sex | `equal_opportunity_gap.sex` 0.07, CI [0.04, 0.11] (key ≈ 0.09); `cf_flip_rate.sex.causal` 0.10 | fail (> 0.05) |
| SYS-002 | accuracy gap 18-25 | `accuracy_gap.age_band.18-25_vs_rest` 0.113, CI [0.07, 0.17] (key ≈ 0.11); sex ratio 0.98 passes | fail (> 0.05) |
| SYS-003 | crashes, nonsense, silent accept | crash 0.17 (ZeroDivisionError on household_size 0, int(NaN) on missing income), nonsense 0.08 (benefit 3,087 > 3,000), silent accept 0.50 | fail |

Note: the key's 0.70 comes from the seed's 140 EU_other rows (selection rate 0.50). On the dictionary's
population the non-EU rate is still the lowest (about 0.36 vs 0.42), but the ratio sits around 0.8, so the
proxy shows in the counterfactual flips rather than in the four-fifths ratio. The SYS-003 graceful rejections
are MLflow's schema enforcement refusing nulls in integer columns.

### SYS-001 check (in the tests)

On a ranker that never sees `sex` or `nationality` but penalises `athens_west` and career gaps, attribute-only
twins show a 0 gap, while causal and proxy-only twins show a gap of about 0.1. The profile's notes point to
those modes before any data is generated.

## Configuration

| Variable | Default | What |
| --- | --- | --- |
| `TRUSTED_PROXY_SECRET` | empty (open in dev only) | the caller secret (compose: `AGENTS_INTERNAL_SECRET`) |
| `SANDBOX_WORK_ROOT` | `/work` (image) | per-call temp dirs (tmpfs in compose) |
| `SANDBOX_DEFAULT_TIMEOUT_SECONDS` / `SANDBOX_MAX_TIMEOUT_SECONDS` | 120 / 900 | command timeouts |
| `SANDBOX_MEMORY_MB` | 3072 | RLIMIT_AS per command |
| `SANDBOX_MAX_OUTPUT_BYTES` | 1048576 | per stream |
| `SANDBOX_MAX_DISK_BYTES` | 268435456 | workdir total and per file |
| `SANDBOX_MAX_CONCURRENT` | 4 | calls at once |
| `SANDBOX_THREADS` | 2 | `OMP`/`OPENBLAS`/`MKL`/`NUMEXPR_NUM_THREADS` inside commands (more threads cannot start under the memory cap) |
| `SANDBOX_MAX_FILES` / `SANDBOX_MAX_TRANSFER_BYTES` | 100 / 20 MB | each way |
| `SANDBOX_PASSTHROUGH_ENV` | `MLFLOW_TRACKING_URI,MODEL_GATEWAY_URL,MODEL_GATEWAY_TOKEN` | env vars commands may see |
| `SANDBOX_MODEL_GATEWAY_URL` (compose) | `http://model-gateway:8000` | becomes `MODEL_GATEWAY_URL` inside the box |
| `EXEC_RATE_LIMIT_MAX_ATTEMPTS` / `_WINDOW_SECONDS` | 120 / 60 | per-IP limit on `/v1/exec` |

## Tests

`tests/sandbox/` has its own `pytest.ini` and uses the service venv. The tests cover the exec contract round
trip, the secret, the limits (timeout, output, disk, memory), path traversal, the minimal environment, synthkit
through `/v1/exec`, determinism, rules, the twin modes, edge cases, custom samplers, profile on a tiny sklearn
model, REST with 429, the analyze gates, scenarios-check and `run-tests` (every template on the planted
ranker, edge-case classes on a fragile model, chat probes on a mock transport, card thresholds, determinism,
one fake MLflow run per test, the CLI, the plugin access config). There is no network.

```powershell
cd mnamon/sandbox; uv venv .venv; uv pip install -r requirements.txt --python .venv; uv pip install -e synthkit --python .venv
uv pip install -e ../shared/modelaccess --python .venv
cd ../..; mnamon\sandbox\.venv\Scripts\python -m pytest tests/sandbox
```
