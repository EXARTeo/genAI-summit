# sandbox_runner and synthkit

`product/sandbox/` holds two things:

- **sandbox_runner**: a small FastAPI service that runs the agents' `execute` commands (`POST /v1/exec`) in a
  throwaway workdir with limits. It is the runner the agents service's
  `harness/filesystem/sandbox_backend.py` expects.
- **synthkit**: the deterministic synthetic test-data engine (`product/sandbox/synthkit/`), installed in the
  runner image as the `synthkit` command. It implements [synthetic-data.md](../architecture/synthetic-data.md):
  first understand the model (`profile`), then check the scenarios, generate the data, and analyse it before a
  human approves it.

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
| Processes | RLIMIT_NPROC = `SANDBOX_MAX_PROCESSES`; compose `pids_limit: 512` | – |
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
  3. agent drafts generation-spec.yaml (LLM), human may edit
     synthkit generate --seed N → dataset.csv/.parquet + DataCard.yaml
  4. synthkit analyze          → dataset-analysis.json/.md shown at the HITL dataset audit
  5. approve → execute the tests on the dataset (twins paired by _twin_of)
```

All commands run through `execute`, with the plugin files in `input/` and the results in `output/`. For example:

```sh
synthkit profile --plugin ../input/plugin.yaml --dictionary ../input/data-dictionary.yaml --out model-profile.json
synthkit generate --spec ../input/generation-spec.yaml --seed 42 --out-dir .
synthkit analyze --dataset dataset.parquet --spec ../input/generation-spec.yaml --profile model-profile.json --out-dir .
```

Exit codes: 0 ok, 1 an analyze gate failed, 2 invalid input (spec, dictionary, expression), 3 the model is
unreachable.

### `synthkit profile`

The target is chosen by `access.type`. `mlflow_model` loads `access.uri` with `mlflow.pyfunc.load_model` (the
signature comes from the model). `rest` sends `POST {"inputs": [...]}` to `access.url`; a path is joined to
`MODEL_GATEWAY_URL`, the request carries `Authorization: Bearer $MODEL_GATEWAY_TOKEN`, `limits.rps` and
`max_requests` are respected, and a 429 is retried after `Retry-After`. `--model-pickle` takes a cloudpickled
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

### `synthkit analyze`

| Gate | Pass / warn / fail |
| --- | --- |
| schema | types, enums, ranges and nulls on rows meant to be valid, plus the model signature columns. Otherwise fail |
| business_rules | hard rules at 100 % on base rows, or fail; soft rules within tolerance, or warn |
| realism | TV/KS complement ≥ 0.8 against a dictionary-only reference population, and `population.stats` within tolerance. Otherwise warn; balanced strata warn by design |
| coverage | every cell ≥ `min_per_cell`, or fail |
| privacy | no email/phone/IBAN/ID/card patterns and no copies of a reference sample, or fail; duplicate base rows over 5 % warn |

The analysis also reports diversity (unique rows, normalised entropy), informativeness (the share near the
boundary by the surrogate) and twin validity per mode.

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
| `SANDBOX_MAX_PROCESSES` / `SANDBOX_MAX_CONCURRENT` | 256 / 4 | |
| `SANDBOX_MAX_FILES` / `SANDBOX_MAX_TRANSFER_BYTES` | 100 / 20 MB | each way |
| `SANDBOX_PASSTHROUGH_ENV` | `MLFLOW_TRACKING_URI,MODEL_GATEWAY_URL,MODEL_GATEWAY_TOKEN` | env vars commands may see |
| `SANDBOX_MODEL_GATEWAY_URL` (compose) | `http://model-gateway:8000` | becomes `MODEL_GATEWAY_URL` inside the box |
| `EXEC_RATE_LIMIT_MAX_ATTEMPTS` / `_WINDOW_SECONDS` | 120 / 60 | per-IP limit on `/v1/exec` |

## Tests

`tests/sandbox/` has its own `pytest.ini` and uses the service venv. The tests cover the exec contract round
trip, the secret, the limits (timeout, output, disk, memory), path traversal, the minimal environment, synthkit
through `/v1/exec`, determinism, rules, the twin modes, edge cases, custom samplers, profile on a tiny sklearn
model, REST with 429, the analyze gates and scenarios-check. There is no network.

```powershell
cd product/sandbox; uv venv .venv; uv pip install -r requirements.txt --python .venv; uv pip install -e synthkit --python .venv
cd ../..; product\sandbox\.venv\Scripts\python -m pytest tests/sandbox
```
